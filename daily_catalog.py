"""Load the curated daily-pig catalogue independently of PigHub refreshes."""

import json
from pathlib import Path


def load_daily_catalog(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []

    pigs = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("id", "name", "description", "analysis", "filename")
        ):
            continue
        pig_id = item["id"]
        filename = item["filename"]
        if (
            pig_id in seen
            or any(char in pig_id + filename for char in ("/", "\\", "\x00"))
            or Path(filename).stem != pig_id
            or Path(filename).suffix.lower()
            not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        ):
            continue
        seen.add(pig_id)
        pigs.append({**item, "source": "curated-rollpig"})
    return pigs
