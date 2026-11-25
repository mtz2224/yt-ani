"""WebVTT cleanup and caption format conversion."""
from __future__ import annotations
import html
import re
import unicodedata

def _clean_cue(lines) -> str:
    t = html.unescape(" ".join(lines))
    t = re.sub(r"</?(?:c(?:\.[^ >]+)?|v(?:\s+[^>]*)?|lang(?:\s+[^>]*)?|ruby|rt|b|i|u|s|br)(?:\s+[^>]*)?>", " ", t, flags=re.I)
    t = re.sub(r"<\d{1,2}:\d{2}(?::\d{2})?\.\d{3}>", " ", t)
    t = re.sub(r"<[^>]*>", " ", t)
    t = re.sub("[\u200b\u200e\u200f\ufeff]", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,.;:!?،؛؟])", r"\1", t)
    return t.strip()

def _parse_ts(v: str):
    parts = v.strip().replace(",", ".").split(":")
    if len(parts) not in (2, 3):
        return None
    sp = parts[-1].split(".")
    if len(sp) != 2:
        return None
    try:
        sec, ms = int(sp[0]), int((sp[1] + "000")[:3])
        mn = int(parts[-2])
        hr = int(parts[0]) if len(parts) == 3 else 0
    except ValueError:
        return None
    if mn >= 60 or sec >= 60:
        return None
    return hr * 3600 + mn * 60 + sec + ms / 1000

def _fmt_ts(sec: float, sep: str = ".") -> str:
    total = max(0, int(round(sec * 1000)))
    h, rem = divmod(total, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"

def _norm(v: str) -> str:
    v = "".join(ch for ch in v.lower() if unicodedata.category(ch)[0] not in ("P", "S"))
    return re.sub(r"\s+", " ", v).strip()

def _merge_overlap(prev: str, nxt: str) -> str:
    left, right = prev.split(), nxt.split()
    overlap = 0
    for size in range(1, min(len(left), len(right)) + 1):
        if " ".join(left[-size:]).lower() == " ".join(right[:size]).lower():
            overlap = size
    return " ".join(left + right[overlap:])

def _collapse(cues):
    res = []
    for cue in cues:
        if not res:
            res.append(dict(cue))
            continue
        prev = res[-1]
        pn, cn = _norm(prev["text"]), _norm(cue["text"])
        close = cue["start"] <= prev["end"] + 1.25
        if pn and cn and close and pn == cn:
            prev["end"] = max(prev["end"], cue["end"])
            continue
        if pn and cn and close and (cn.startswith(pn) or pn.startswith(cn)):
            if len(cn) > len(pn):
                prev["text"] = cue["text"]
            prev["end"] = max(prev["end"], cue["end"])
            continue
        if pn and cn and close and cue["start"] <= prev["end"]:
            combined = _merge_overlap(prev["text"], cue["text"])
            if _norm(combined) != cn and len(combined) > len(prev["text"]):
                prev["text"] = combined
                prev["end"] = max(prev["end"], cue["end"])
                continue
        res.append(dict(cue))
    return res

def parse_vtt(raw: str):
    raw = raw.replace("\ufeff", "").replace("\r", "").strip()
    cues = []
    time_re = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})")
    for block in re.split(r"\n\s*\n", raw):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines or re.match(r"^(WEBVTT|NOTE(\s|$)|STYLE$|REGION$)", lines[0], re.I):
            continue
        ti = next((i for i, l in enumerate(lines) if time_re.search(l)), -1)
        if ti < 0:
            continue
        m = time_re.search(lines[ti])
        start, end = _parse_ts(m.group(1)), _parse_ts(m.group(2))
        if start is None or end is None or end <= start:
            continue
        text = _clean_cue(lines[ti + 1:])
        if text:
            cues.append({"start": start, "end": end, "text": text})
    return _collapse(cues)

def convert_vtt(raw: str, target: str, plain: bool = False) -> str:
    cues = parse_vtt(raw)
    if target == "srt":
        body = "\n\n".join(f"{i}\n{_fmt_ts(c['start'], ',')} --> {_fmt_ts(c['end'], ',')}\n{c['text']}"
                           for i, c in enumerate(cues, 1))
        return body + ("\n" if cues else "")
    if target == "txt":
        if not plain:
            return "\n".join(f"{_fmt_ts(c['start'])} {c['text']}" for c in cues) + ("\n" if cues else "")
        seen, parts = set(), []
        for c in cues:
            n = _norm(c["text"])
            if not n or n in seen:
                continue
            seen.add(n)
            parts.append(c["text"])
        joined = re.sub(r"\s+([,.;!?،؛؟])", r"\1", " ".join(parts))
        joined = re.sub(r"([.!?؟])\s+", r"\1\n\n", joined).strip()
        return joined + ("\n" if joined else "")
    return "WEBVTT\n\n" + "\n\n".join(f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}\n{c['text']}" for c in cues) + ("\n" if cues else "")
