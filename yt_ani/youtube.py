"""yt-dlp integration, validation, and available stream catalogues."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import APP_SLUG, DEFAULT_OUTPUT_DIR, YT_HOSTS
from .dependencies import find_ffmpeg, find_js_runtime
from .errors import YTError
from .terminal import Spinner, strip_ansi
from .utils import fmt_size

class _Log:
    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.lines: list[str] = []

    def debug(self, m):
        if self.verbose and not str(m).startswith("[debug] "):
            sys.stderr.write(str(m) + "\n")

    info = debug

    def warning(self, m):
        self.lines.append(str(m))
        if self.verbose:
            sys.stderr.write(str(m) + "\n")

    def error(self, m):
        self.lines.append(str(m))
        if self.verbose:
            sys.stderr.write(str(m) + "\n")

class Ctx:
    def __init__(self, args):
        o = getattr(args, "output", None)
        self.outdir = Path(o).expanduser() if o else DEFAULT_OUTPUT_DIR
        self.cookies_browser = getattr(args, "cookies_from_browser", None)
        self.cookies = getattr(args, "cookies", None)
        self.verbose = getattr(args, "verbose", False)
        self.log = _Log(self.verbose)

    def opts(self) -> dict:
        o = {
            "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
            "logger": self.log, "socket_timeout": 20, "retries": 10, "fragment_retries": 10,
            "extractor_retries": 3, "concurrent_fragment_downloads": 8,
            "http_chunk_size": 10 * 1024 * 1024, "overwrites": True,
        }
        ff = find_ffmpeg()
        if ff:
            o["ffmpeg_location"] = ff
        runtime = find_js_runtime()
        if runtime:
            o["js_runtimes"] = {runtime[0]: {"path": runtime[1]}}
        if self.cookies_browser:
            o["cookiesfrombrowser"] = (self.cookies_browser,)
        if self.cookies:
            o["cookiefile"] = str(Path(self.cookies).expanduser())
        if os.name == "nt":
            o["windowsfilenames"] = True
        return o

def friendly(exc: Exception, log: _Log | None = None) -> YTError:
    raw = strip_ansi(str(exc))
    msg = re.sub(r"^ERROR:\s*", "", raw.strip())
    msg = re.sub(r"^\[youtube\]\s*[\w-]+:\s*", "", msg)
    low = (raw + " " + " ".join(log.lines if log else [])).lower()
    hint = ""
    if "no supported javascript runtime" in low or "javascript challenge" in low:
        hint = "Install Deno 2.3+ (recommended) or Node.js 22+. On Termux, try: pkg install deno."
    elif "sign in to confirm" in low or "not a bot" in low:
        hint = "YouTube wants a signed-in session. Try:  --cookies-from-browser firefox  (or chrome, edge, brave...)"
    elif "private video" in low:
        hint = "This video is private."
    elif "requested format is not available" in low:
        hint = "That quality isn't available for this video. Run  info  to see what is."
    elif "http error 403" in low or "nsig" in low or "signature" in low:
        hint = f"Run  {APP_SLUG} update  - YouTube changed something and yt-dlp likely has a fix."
    elif "ffmpeg" in low and ("not found" in low or "not installed" in low):
        hint = f"Run  {APP_SLUG} doctor --fix  to install FFmpeg."
    elif "no space left" in low:
        hint = "Your disk is full - free some space or pick another folder with -o."
    elif "urlopen error" in low or "getaddrinfo" in low or "unable to download" in low or "timed out" in low:
        hint = "Check your internet connection and try again."
    return YTError(msg.splitlines()[0] if msg else "Something went wrong.", hint)

def validate_url(raw: str):
    raw = raw.strip().strip("\"'")
    if not raw:
        raise YTError("Paste a YouTube link first.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    p = urlparse(raw)
    host = (p.hostname or "").lower()
    if host not in YT_HOSTS:
        raise YTError("That doesn't look like a YouTube link.", "Use a link from youtube.com or youtu.be.")
    vid = None
    if host.endswith("youtu.be"):
        vid = p.path.strip("/").split("/")[0]
    else:
        vid = (parse_qs(p.query).get("v") or [None])[0]
        if not vid:
            m = re.match(r"^/(?:shorts|embed|live|v)/([\w-]{11})", p.path)
            vid = m.group(1) if m else None
    if not vid or not re.fullmatch(r"[\w-]{11}", vid):
        raise YTError("Couldn't find a video in that link.", "Playlists and channels aren't supported - paste a single video link.")
    return f"https://www.youtube.com/watch?v={vid}", vid

def analyze(url: str, ctx: Ctx) -> dict:
    from yt_dlp import YoutubeDL
    try:
        with YoutubeDL(ctx.opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # yt-dlp raises DownloadError / ExtractorError
        raise friendly(e, ctx.log)
    if info and info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise YTError("No video found at that link.")
        info = entries[0]
    if not info:
        raise YTError("No video information came back.")
    if info.get("is_live"):
        raise YTError("Live streams aren't supported.", "Wait until the stream ends and it becomes a normal video.")
    return info

def _has(f, key) -> bool:
    return f.get(key) not in (None, "none")

def est_size(f: dict, duration):
    if f.get("filesize"):
        return int(f["filesize"]), False
    if f.get("filesize_approx"):
        return int(f["filesize_approx"]), True
    rate = f.get("tbr") or f.get("abr") or f.get("vbr")
    if rate and duration:
        return int(rate * 1000 / 8 * duration), True
    return None, True

def best_audio_stream(info: dict, container: str = "mp4"):
    auds = [f for f in info.get("formats") or []
            if f.get("format_id") and _has(f, "acodec") and not _has(f, "vcodec") and (f.get("abr") or f.get("tbr"))]
    if not auds:
        return None
    pref = {"mp4": "m4a", "webm": "webm"}.get(container)
    auds.sort(key=lambda f: ((f.get("ext") == pref) if pref else 0, f.get("abr") or f.get("tbr") or 0), reverse=True)
    return auds[0]

def _codec_rank(f: dict, container: str) -> int:
    """Prefer efficient source codecs; fall back to H.264 for compatibility."""
    vc = (f.get("vcodec") or "").lower()
    order = ("av01", "av1", "vp09", "vp9", "hev", "hvc", "avc")
    for i, name in enumerate(order):
        if vc.startswith(name):
            return i
    return len(order)

def _codec_label(vc: str) -> str:
    vc = (vc or "").lower()
    for k, v in (("avc", "H.264"), ("vp09", "VP9"), ("vp9", "VP9"), ("av01", "AV1"), ("hev", "H.265"), ("hvc", "H.265")):
        if vc.startswith(k):
            return v
    return vc.split(".")[0].upper() or "?"

def build_video_rows(info: dict, container: str = "mp4", with_audio: bool = True) -> list[dict]:
    duration = info.get("duration")
    groups: dict = {}
    for f in info.get("formats") or []:
        if not (f.get("format_id") and _has(f, "vcodec") and f.get("height")):
            continue
        if f.get("protocol") in ("mhtml",) or "storyboard" in (f.get("format_note") or "").lower():
            continue
        if not with_audio and _has(f, "acodec"):
            continue
        key = (int(f["height"]), 1 if (f.get("fps") or 0) >= 50 else 0)
        groups.setdefault(key, []).append(f)
    aud = best_audio_stream(info, container)
    rows = []
    for (height, hfps), lst in groups.items():
        video_only = [f for f in lst if not _has(f, "acodec")]
        pool = video_only or lst
        pool.sort(key=lambda f: (_codec_rank(f, container), -(f.get("tbr") or 0)))
        f = pool[0]
        muxed = _has(f, "acodec")
        size, est = est_size(f, duration)
        if with_audio and not muxed and aud:
            asz, aest = est_size(aud, duration)
            if size and asz:
                size, est = size + asz, est or aest
            elif not asz:
                est = True
        fps = int(round(f.get("fps") or 0))
        rows.append({
            "format_id": str(f["format_id"]), "height": height, "fps": fps, "muxed": muxed,
            "ext": f.get("ext") or "", "codec": _codec_label(f.get("vcodec")),
            "size": size, "estimated": est or size is None,
            "label": f"{height}p" + (str(fps) if fps >= 50 else ""),
        })
    rows.sort(key=lambda r: (r["height"], r["fps"]), reverse=True)
    return rows

def recommended_index(rows: list[dict]) -> int:
    for i, r in enumerate(rows):
        if r["height"] <= 1080:
            return i
    return 0

def size_text(size, estimated) -> str:
    if not size:
        return "size unknown"
    return ("~" if estimated else "") + fmt_size(size)

def build_audio_rows(info: dict) -> list[dict]:
    duration = info.get("duration")
    auds = [f for f in info.get("formats") or []
            if f.get("format_id") and _has(f, "acodec") and not _has(f, "vcodec")
            and "storyboard" not in (f.get("format_note") or "").lower()]
    if any("-drc" not in str(f["format_id"]) for f in auds):
        auds = [f for f in auds if "-drc" not in str(f["format_id"])]
    auds.sort(key=lambda f: (f.get("abr") or f.get("tbr") or 0, f.get("ext") == "m4a"), reverse=True)
    rows = []
    for f in auds:
        size, est = est_size(f, duration)
        rows.append({
            "format_id": str(f["format_id"]), "abr": int(round(f.get("abr") or f.get("tbr") or 0)),
            "codec": (f.get("acodec") or "").split(".")[0], "ext": f.get("ext") or "",
            "lang": f.get("language") or "", "size": size, "estimated": est or size is None,
        })
    return rows

def caption_groups(info: dict) -> dict:
    g = {"manual": [], "automatic": [], "translated": []}

    def name_of(entries, key):
        e = entries[0] if isinstance(entries, list) and entries else {}
        return (e.get("name") if isinstance(e, dict) else None) or key

    for k, v in (info.get("subtitles") or {}).items():
        if k != "live_chat":
            g["manual"].append((k, name_of(v, k)))
    for k, v in (info.get("automatic_captions") or {}).items():
        (g["automatic"] if re.search(r"-orig$", k, re.I) else g["translated"]).append((k, name_of(v, k)))
    return g
