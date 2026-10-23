"""Group chat pacing, speaker attribution and reply continuity.

- Keeps a persistent per-group transcript (nickname + QQ number per line).
- Injects recent transcript + participants when the bot is about to speak.
- Lets the model decide whether to join at all (it can answer %%SKIP%%).
- Replies once every few messages, but always when @'d or a keyword hits.
"""

import asyncio
import json
import random
import re
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Face, Image, Plain

MEMORY_COMMAND = re.compile(
    r"^[/／]?(?:记住|记一下|记下|记着|帮我记住|忘记|忘掉|删掉记忆|别记)"
)

SKIP_MARK = "%%SKIP%%"

DEFAULTS = {
    "keywords": ["seedseek", "deepseek", "ds", "大肥鱼", "肥鱼", "ai"],
    "min_gap": 3,
    "max_gap": 4,
    "context_messages": 40,
    "max_keep": 120,
    "participants_shown": 8,
    "engage_ttl_seconds": 120,
    "other_question_gap": 6,
    "min_reply_interval_seconds": 6,
}

QUESTION_RE = re.compile(
    r"[?？]|(?:吗|呢)[\s。！!~]*$|怎么|为什么|为啥|啥|什么|多少|哪[里个儿]?|谁|几点|"
    r"能不能|可不可以|是不是|有没有|如何|怎么办|求推荐"
)


class GroupChatter(star.Star):
    """控制群聊回复频率，带上「谁说了什么」，并允许她判断要不要接话。"""

    def __init__(self, context: star.Context) -> None:
        super().__init__(context)
        self.cfg = dict(DEFAULTS)
        cfg_path = Path(__file__).with_name("config.json")
        try:
            if cfg_path.exists():
                self.cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter: bad config.json: %s", exc)
        self.keywords = [str(k) for k in self.cfg.get("keywords", []) if str(k).strip()]
        self.min_gap = max(1, int(self.cfg.get("min_gap", 3)))
        self.max_gap = max(self.min_gap, int(self.cfg.get("max_gap", 4)))
        self.context_messages = max(3, int(self.cfg.get("context_messages", 40)))
        self.max_keep = max(self.context_messages, int(self.cfg.get("max_keep", 120)))
        self.participants_shown = max(2, int(self.cfg.get("participants_shown", 8)))
        self.engage_ttl = max(30, int(self.cfg.get("engage_ttl_seconds", 120)))
        self.other_question_gap = max(2, int(self.cfg.get("other_question_gap", 6)))
        self.min_reply_interval = max(
            0.0, float(self.cfg.get("min_reply_interval_seconds", 6))
        )
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0
        self._busy_until = 0.0
        self._question_counters: dict[str, int] = {}
        self._engaged: dict[str, dict] = {}

        self.store_path = Path(__file__).with_name("group_memory.json")
        self._groups: dict[str, dict] = self._load_store()
        self._counters: dict[str, int] = {}
        self._thresholds: dict[str, int] = {}
        logger.info(
            "group_chatter: gap=%s~%s context=%s keep=%s groups=%s",
            self.min_gap,
            self.max_gap,
            self.context_messages,
            self.max_keep,
            len(self._groups),
        )

    # ---------------- persistence ----------------

    def _load_store(self) -> dict[str, dict]:
        try:
            if self.store_path.exists():
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter: cannot read %s: %s", self.store_path, exc)
        return {}

    def _save_store(self) -> None:
        try:
            tmp = self.store_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._groups, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self.store_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter: cannot save %s: %s", self.store_path, exc)

    def _group(self, group_id: str) -> dict:
        group = self._groups.get(group_id)
        if group is None:
            group = {"entries": [], "names": {}, "last_reply": "", "last_speaker": ""}
            self._groups[group_id] = group
        group.setdefault("entries", [])
        group.setdefault("names", {})
        group.setdefault("last_reply", "")
        group.setdefault("last_speaker", "")
        return group

    # ---------------- helpers ----------------

    def _next_threshold(self, group_id: str) -> int:
        value = random.randint(self.min_gap, self.max_gap)
        self._thresholds[group_id] = value
        return value

    def _matched_keyword(self, text: str) -> str | None:
        lower = text.lower()
        for keyword in self.keywords:
            kw = keyword.strip()
            if not kw:
                continue
            if kw.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(kw.lower())}(?![a-z0-9])", lower):
                    return kw
            elif kw in text:
                return kw
        return None

    @staticmethod
    def _is_at_me(event: AstrMessageEvent) -> bool:
        try:
            self_id = str(event.get_self_id())
            for comp in event.get_messages():
                if isinstance(comp, At) and str(comp.qq) == self_id:
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    @staticmethod
    def _sender(event: AstrMessageEvent) -> tuple[str, str]:
        qq, name = "", "群友"
        try:
            qq = str(event.get_sender_id() or "")
        except Exception:  # noqa: BLE001
            pass
        try:
            name = event.message_obj.sender.nickname or name
        except Exception:  # noqa: BLE001
            pass
        return qq, name

    @staticmethod
    def _result_text(event: AstrMessageEvent) -> str:
        result = event.get_result()
        if result is None:
            return ""
        pieces: list[str] = []
        for comp in result.chain or []:
            if isinstance(comp, Plain):
                pieces.append(comp.text)
            elif isinstance(comp, Image):
                pieces.append("[图片]")
            elif isinstance(comp, Face):
                pieces.append("[表情]")
        return "".join(pieces).strip()

    # ---------------- hooks ----------------

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def pace_group_reply(self, event: AstrMessageEvent) -> None:
        try:
            group_id = str(event.get_group_id() or "")
            if not group_id:
                return
            text = (event.message_str or "").strip()
            if text.startswith("/") or MEMORY_COMMAND.match(text):
                return

            qq, name = self._sender(event)
            group = self._group(group_id)
            if qq:
                group["names"][qq] = name
                group["last_speaker"] = qq
            group["entries"].append(
                {
                    "qq": qq,
                    "name": name,
                    "text": text or "[非文本消息]",
                    "ts": int(time.time()),
                }
            )
            if len(group["entries"]) > self.max_keep:
                del group["entries"][: len(group["entries"]) - self.max_keep]
            self._save_store()

            now = time.time()
            engaged = self._engaged.get(group_id)
            if engaged and now > engaged.get("until", 0):
                self._engaged.pop(group_id, None)
                engaged = None

            if self._is_at_me(event):
                self._counters[group_id] = 0
                self._next_threshold(group_id)
                if engaged:
                    engaged["until"] = now + self.engage_ttl
                return

            keyword = self._matched_keyword(text)
            if keyword:
                logger.info("group_chatter: keyword '%s' hit, reply", keyword)
                self._counters[group_id] = 0
                self._next_threshold(group_id)
                if engaged:
                    engaged["until"] = now + self.engage_ttl
                return

            if engaged and qq and qq == engaged.get("qq"):
                engaged["until"] = now + self.engage_ttl
                logger.debug("group_chatter: free chat with %s, reply", qq)
                return

            # 别人互相提问（没 @ 她、没提关键词、也没问“你”）：更少接话
            if QUESTION_RE.search(text) and "你" not in text:
                count = self._question_counters.get(group_id, 0) + 1
                if count < self.other_question_gap:
                    self._question_counters[group_id] = count
                    event.stop_event()
                    return
                self._question_counters[group_id] = 0
                event.set_extra("group_other_question", True)
                logger.info(
                    "group_chatter: other-question quota %s hit, let model decide",
                    self.other_question_gap,
                )
                return

            threshold = self._thresholds.get(group_id) or self._next_threshold(group_id)
            self._counters[group_id] = self._counters.get(group_id, 0) + 1
            if self._counters[group_id] < threshold:
                event.stop_event()
                return
            logger.info(
                "group_chatter: reached %s/%s, let model decide",
                self._counters[group_id],
                threshold,
            )
            self._counters[group_id] = 0
            self._next_threshold(group_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter pace hook failed: %s", exc)

    async def _wait_for_pending_send(self) -> None:
        """上一条回复还在等发送时，先别开始判断新消息。"""
        busy_until = self._busy_until
        now = time.time()
        if busy_until > now:
            logger.info("group_chatter: previous reply pending, wait %.1fs", busy_until - now)
            await asyncio.sleep(busy_until - now + 0.2)

    @filter.on_llm_request()
    async def inject_group_context(self, event: AstrMessageEvent, req) -> None:
        try:
            await self._wait_for_pending_send()
            if event.is_private_chat():
                return
            group_id = str(event.get_group_id() or "")
            if not group_id:
                return
            group = self._group(group_id)
            qq, name = self._sender(event)
            at_me = self._is_at_me(event)

            sections: list[str] = []
            names = list(group["names"].items())[-self.participants_shown :]
            if names:
                roster = "\n".join(f"- {n}({q})" for q, n in names)
                sections.append(f"群成员（昵称(QQ号)）：\n{roster}")

            last_reply = group.get("last_reply") or ""
            if last_reply:
                sections.append(f"你上一次在这个群的回复：{last_reply}")

            entries = group["entries"][-self.context_messages :]
            if entries:
                lines = "\n".join(
                    f"{e['name']}({e['qq']}): {e['text']}" for e in entries
                )
                sections.append(
                    "最近的群聊记录（每行开头是说话人，格式 昵称(QQ号)）：\n" + lines
                )

            if not sections and not at_me:
                return
            current = f"昵称：{name}，QQ号：{qq}" if qq else f"昵称：{name}"
            if at_me:
                current += "（这条在 @ 你）"

            body = "\n\n".join(sections) if sections else "（没有前文，只是有人 @ 你）"
            engaged = self._engaged.get(group_id)
            free_chat = bool(engaged and qq and qq == engaged.get("qq"))
            mode_rule = (
                "4. 你现在和这个人聊起来了：可以自由接话，像真群友一样多聊几句，不用拘束；"
                "聊到没话说了就自然停。\n"
                if free_chat
                else "4. 你自己判断该不该插话：觉得这个话题不需要你，就只输出 " + SKIP_MARK + "（不要带其他任何内容）；"
                "被 @ 时不要用这个，正常回复。\n"
            )
            extra_rule = ""
            if event.get_extra("group_other_question"):
                extra_rule = (
                    "6. 这条不是问你的，是群里别人在互相提问：不想答就只输出 "
                    + SKIP_MARK
                    + "；想插一句就短短接一下，别长篇。\n"
                )
            rules = (
                "\n\n<群聊规则>\n"
                f"当前说话人：{current}\n"
                "1. 每行开头的“昵称(QQ号)”才是说话人。严禁把 A 说的话当成 B 说的，"
                "引用或回应某人前先看清他的昵称和 QQ 号；昵称重复时以 QQ 号区分。\n"
                "2. 回复要承接「你上一次的回复」到「现在」这整段话题，不要只针对最后一句；话题聊完了就自然接新的。\n"
                "3. 如果前文在聊你、问你、提到你的名字或大肥鱼/deepseek，就直接接那个话题，"
                "不要问“干什么/咋了/找我干嘛/有事吗”。\n"
                + mode_rule
                + "5. 没什么想说的、想敷衍，就发「ws」两个字。保持短句风格。\n"
                + extra_rule
                + "</群聊规则>"
            )
            req.system_prompt = (
                (getattr(req, "system_prompt", "") or "")
                + "\n\n<群聊上下文>\n"
                + body
                + rules
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter context hook failed: %s", exc)

    @filter.on_decorating_result()
    async def drop_skip_marker(self, event: AstrMessageEvent) -> None:
        try:
            result = event.get_result()
            if result is None or not result.chain:
                return
            if not event.is_private_chat():
                text = "".join(
                    comp.text for comp in result.chain if isinstance(comp, Plain)
                ).strip()
                if SKIP_MARK in text:
                    result.chain = []
                    logger.info("group_chatter: model chose to skip this one")
                    return

            # 生成完了先等一会儿再发；这段时间里的新消息会等到这次发送结束再处理
            async with self._send_lock:
                now = time.time()
                send_at = max(now, self._last_send_at + self.min_reply_interval)
                self._last_send_at = send_at
                self._busy_until = send_at
            wait = send_at - now
            if wait > 0.05:
                logger.info("group_chatter: hold reply for %.1fs before sending", wait)
                await asyncio.sleep(wait)
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter skip hook failed: %s", exc)

    @filter.after_message_sent()
    async def remember_last_reply(self, event: AstrMessageEvent) -> None:
        try:
            self._busy_until = 0.0
            if event.is_private_chat():
                return
            group_id = str(event.get_group_id() or "")
            if not group_id:
                return
            text = self._result_text(event)
            if not text or SKIP_MARK in text:
                return
            group = self._group(group_id)
            group["last_reply"] = text[:300]
            speaker = str(group.get("last_speaker") or "")
            if speaker:
                self._engaged[group_id] = {
                    "qq": speaker,
                    "until": time.time() + self.engage_ttl,
                }
                logger.info(
                    "group_chatter: free chat with %s for %ss",
                    speaker,
                    self.engage_ttl,
                )
            self._save_store()
        except Exception as exc:  # noqa: BLE001
            logger.warning("group_chatter after-send hook failed: %s", exc)
