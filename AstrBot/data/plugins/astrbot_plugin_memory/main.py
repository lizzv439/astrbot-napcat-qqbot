"""Long-term memory for the bot.

Owner can teach facts with "记住 xxx" / "记一下 xxx" (also "/记住 xxx"),
remove them with "忘记 xxx", and every memory is injected into the system prompt.
"""

import json
import re
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter

REMEMBER_RE = re.compile(
    r"^[/／]?(?:记住|记一下|记下|记着|帮我记住)[：:，,\s]*(?P<text>.+)$",
    re.S,
)
FORGET_RE = re.compile(
    r"^[/／]?(?:忘记|忘掉|删掉记忆|别记)[：:，,\s]*(?P<text>.+)$",
    re.S,
)
LIST_WORDS = {"/记忆", "/记忆列表", "记忆列表"}


class MemoryStore(star.Star):
    """把主人交代的事情长期记住，并在每次对话时带进上下文。"""

    def __init__(self, context: star.Context) -> None:
        super().__init__(context)
        base = Path(__file__).with_name("config.json")
        self.admin_ids: set[str] = set()
        self.max_memories = 60
        try:
            if base.exists():
                cfg = json.loads(base.read_text(encoding="utf-8"))
                self.admin_ids = {str(i) for i in cfg.get("admin_ids", [])}
                self.max_memories = int(cfg.get("max_memories", 60))
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory: bad config.json: %s", exc)
        self.path = Path(__file__).with_name("memories.json")
        self.memories = self._load()
        logger.info("memory: loaded %s memories from %s", len(self.memories), self.path)

    # ---------------- storage ----------------

    def _load(self) -> list[dict]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict) and item.get("text")]
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory: cannot read %s: %s", self.path, exc)
        return []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.memories, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    def _add(self, text: str) -> str:
        text = text.strip().strip("。.，, ")
        if not text:
            return ""
        for item in self.memories:
            if item.get("text") == text:
                return "already"
        self.memories.append({"text": text, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        if len(self.memories) > self.max_memories:
            self.memories = self.memories[-self.max_memories :]
        self._save()
        logger.info("memory: saved '%s'", text)
        return "saved"

    def _forget(self, keyword: str) -> int:
        keyword = keyword.strip()
        before = len(self.memories)
        self.memories = [m for m in self.memories if keyword not in m.get("text", "")]
        removed = before - len(self.memories)
        if removed:
            self._save()
            logger.info("memory: removed %s entries matching '%s'", removed, keyword)
        return removed

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        try:
            if str(event.get_sender_id()) in self.admin_ids:
                return True
            return getattr(event, "role", "") == "admin"
        except Exception:  # noqa: BLE001
            return False

    # ---------------- hooks ----------------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def capture_command(self, event: AstrMessageEvent) -> None:
        try:
            if not self._is_admin(event):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            if text in LIST_WORDS:
                listing = (
                    "\n".join(f"- {m['text']}" for m in self.memories)
                    or "（还没有记任何东西）"
                )
                event.set_extra("memory_note", f"主人查看了记忆列表，当前记忆：\n{listing}")
                return

            match = REMEMBER_RE.match(text)
            if match:
                result = self._add(match.group("text"))
                note = (
                    "这条已经记过了，不用重复记。"
                    if result == "already"
                    else f"刚刚把「{match.group('text').strip()}」记住了。"
                )
                event.set_extra("memory_note", note)
                return

            match = FORGET_RE.match(text)
            if match:
                removed = self._forget(match.group("text"))
                note = (
                    f"刚刚删掉了和「{match.group('text').strip()}」有关的 {removed} 条记忆。"
                    if removed
                    else f"没找到和「{match.group('text').strip()}」有关的记忆，没删。"
                )
                event.set_extra("memory_note", note)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory command hook failed: %s", exc)

    @filter.on_llm_request()
    async def inject_memories(self, event: AstrMessageEvent, req) -> None:
        try:
            parts: list[str] = []
            if self.memories:
                lines = "\n".join(
                    f"- {m['text']}" for m in self.memories[-self.max_memories :]
                )
                parts.append(f"<你记住的事>\n{lines}\n</你记住的事>")
            note = event.get_extra("memory_note")
            if note:
                parts.append(f"<记忆更新>\n{note}\n</记忆更新>")
            if not parts:
                return
            block = (
                "\n\n"
                + "\n\n".join(parts)
                + "\n（这些是你记住的信息：自然地在对话里用，不要罗列、不要说“根据我的记忆”。"
                "如果 <记忆更新> 存在，就用你的口吻简短回应一句。）"
            )
            req.system_prompt = (getattr(req, "system_prompt", "") or "") + block
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory inject hook failed: %s", exc)
