"""Formatting and timestamp conversion helpers."""
from __future__ import annotations
import re
from .errors import YTError

def fmt_size(n) -> str:
    if not n or n <= 0:
        return "?"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if (v >= 100 or unit == "B") else f"{v:.1f} {unit}"
        v /= 1024
    return "?"

def fmt_time(sec) -> str:
    if sec is None:
        return "?"
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fmt_count(n) -> str:
    if not n:
        return ""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + suffix
    return str(int(n))

def parse_time(raw: str) -> float:
    s = str(raw).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", s)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", s)
    if m and any(m.groups()):
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
    raise YTError(f"Couldn't read the time '{raw}'.", "Use seconds (90), mm:ss (1:30), hh:mm:ss or 1h2m3s.")

def tag_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return (f"{h}h" if h else "") + f"{m:02d}m{s:02d}s"
