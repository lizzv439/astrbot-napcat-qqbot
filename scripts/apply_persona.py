"""Apply persona text to AstrBot and tune a few platform settings.

Usage:
    python apply_persona.py <db_path> <persona.txt> <persona_extra.txt> <cmd_config.json> [owner_qq]

The `{OWNER_QQ}` placeholder inside persona_extra.txt is replaced with owner_qq
(falls back to scripts/config.local.json -> {"owner_qq": "..."}).
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def load_owner_qq(explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    local = Path(__file__).with_name("config.local.json")
    if local.exists():
        try:
            data = json.loads(local.read_text(encoding="utf-8"))
            return str(data.get("owner_qq", "")).strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


def main() -> None:
    db_path, persona_path, extra_path, config_path = sys.argv[1:5]
    owner_qq = load_owner_qq(sys.argv[5] if len(sys.argv) > 5 else None)

    prompt = Path(persona_path).read_text(encoding="utf-8").strip()
    extra = Path(extra_path).read_text(encoding="utf-8").strip()
    if "{OWNER_QQ}" in extra:
        if not owner_qq:
            raise SystemExit(
                "owner QQ is required: pass it as the 5th argument or put "
                '{"owner_qq": "123456"} into scripts/config.local.json'
            )
        extra = extra.replace("{OWNER_QQ}", owner_qq)
    full = prompt + "\n\n" + extra

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "update personas set system_prompt = ?, updated_at = ? where persona_id = 'default'",
        (full, datetime.now().isoformat(sep=" ")),
    )
    con.commit()
    cur.execute("select persona_id, length(system_prompt) from personas")
    print("personas:", cur.fetchall())
    con.close()

    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    ps = cfg["platform_settings"]
    cfg["wake_prefix"] = ["/", ""]
    ps["empty_mention_waiting"] = False
    ps["reply_with_mention"] = False
    cfg["provider_settings"]["identifier"] = True
    Path(config_path).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "wake_prefix:",
        cfg["wake_prefix"],
        "| identifier:",
        cfg["provider_settings"]["identifier"],
    )


if __name__ == "__main__":
    main()
