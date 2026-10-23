"""Convert [[face:ID]] and [[bqf(:keyword)]] markers in LLM replies into QQ faces / sticker images."""

import json
import random
import re
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Face, Image, Plain

MARKER = re.compile(
    r"\[\[face:(?P<face>\d{1,3})\]\]"
    r"|\[\[bqf(?::(?P<kw>[^\[\]]{1,20}))?\]\]"
)

IMAGE_SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webp"}


class FaceSender(star.Star):
    """把 [[face:14]] 变成 QQ 小黄脸，把 [[bqf]] / [[bqf:关键词]] 变成表情包图片。"""

    def __init__(self, context: star.Context) -> None:
        super().__init__(context)
        self.sticker_dir = Path("")
        self.max_bytes = 4 * 1024 * 1024
        self.max_stickers_per_message = 1
        cfg_path = Path(__file__).with_name("config.json")
        try:
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.sticker_dir = Path(cfg.get("sticker_dir", str(self.sticker_dir)))
                self.max_bytes = int(cfg.get("max_bytes", self.max_bytes))
                self.max_stickers_per_message = int(
                    cfg.get("max_stickers_per_message", self.max_stickers_per_message)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("face_sender: bad config.json: %s", exc)
        self._stickers: list[Path] | None = None
        self._load_stickers()

    def _load_stickers(self) -> list[Path]:
        if self._stickers is not None:
            return self._stickers
        if not str(self.sticker_dir).strip() or not self.sticker_dir.is_dir():
            logger.info("face_sender: sticker_dir not configured, sticker sending disabled")
            self._stickers = []
            return self._stickers
        items: list[Path] = []
        try:
            for path in self.sticker_dir.rglob("*"):
                if path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > self.max_bytes:
                        continue
                except OSError:
                    continue
                items.append(path)
        except OSError as exc:
            logger.warning("face_sender: cannot read %s: %s", self.sticker_dir, exc)
        items.sort()
        self._stickers = items
        logger.info(
            "face_sender: loaded %s stickers (<= %s MB) from %s",
            len(items),
            self.max_bytes // (1024 * 1024),
            self.sticker_dir,
        )
        return items

    def _pick_sticker(self, keyword: str | None) -> Path | None:
        items = self._load_stickers()
        if not items:
            return None
        if keyword:
            kw = keyword.strip().lower()
            matched = [p for p in items if kw in p.stem.lower()]
            if matched:
                return random.choice(matched)
        return random.choice(items)

    @filter.on_decorating_result()
    async def convert_markers(self, event: AstrMessageEvent) -> None:
        result = event.get_result()
        if result is None or not result.chain:
            return
        plains = [c for c in result.chain if isinstance(c, Plain)]
        if not any("[[face:" in c.text or "[[bqf" in c.text for c in plains):
            return

        new_chain: list = []
        changed = False
        stickers = 0
        for comp in result.chain:
            if not isinstance(comp, Plain):
                new_chain.append(comp)
                continue
            text = comp.text
            cursor = 0
            for match in MARKER.finditer(text):
                if match.start() > cursor:
                    new_chain.append(Plain(text[cursor : match.start()]))
                cursor = match.end()
                if match.group("face") is not None:
                    face_id = int(match.group("face"))
                    if 0 <= face_id <= 400:
                        new_chain.append(Face(id=face_id))
                        changed = True
                else:
                    if stickers >= self.max_stickers_per_message:
                        continue
                    path = self._pick_sticker(match.group("kw"))
                    if path is None:
                        continue
                    new_chain.append(Image.fromFileSystem(str(path)))
                    stickers += 1
                    changed = True
            if cursor < len(text):
                new_chain.append(Plain(text[cursor:]))

        if changed:
            result.chain = new_chain
            logger.debug("face_sender: markers converted (stickers=%s)", stickers)
