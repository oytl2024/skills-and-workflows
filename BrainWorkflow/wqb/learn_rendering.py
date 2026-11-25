"""Pure canonical Learn text rendering shared by capture and offline source verification."""
import html
import re
from typing import Any


def clean_text(value: Any) -> str:
    """Input: arbitrary content value. Output: compact str; preserve the existing HTML/list/dict rendering contract."""
    if isinstance(value, str):
        without_style = re.sub(r"<style.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
        without_tags = re.sub(r"<[^>]+>", " ", without_style)
        return " ".join(html.unescape(without_tags).split())
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(clean_text(item.get("value") or item.get("content") or item.get("text") or ""))
            else:
                parts.append(clean_text(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return " ".join(clean_text(item) for item in value.values())
    return ""


def markdown_record_value(value: Any) -> str:
    """Input: arbitrary source value. Output: Markdown str; byte-compatible fallback for nontext values."""
    text = clean_text(value)
    return text if text else str(value or "")
