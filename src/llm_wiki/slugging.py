from __future__ import annotations

import re


def slugify(value: str, *, fallback: str) -> str:
    cleaned = value.strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    cleaned = re.sub(r"[\\/<>:\"|?*\x00-\x1f]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-. ")
    if not cleaned:
        cleaned = fallback.strip().lower()
    return cleaned[:180] or "note"
