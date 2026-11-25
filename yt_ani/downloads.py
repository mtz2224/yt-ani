"""Download plan models, progress rendering, and execution."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .captions import convert_vtt, parse_vtt
from .config import APP_NAME, APP_SLUG
from .dependencies import find_ffmpeg, find_js_runtime
from .errors import YTError
from .terminal import (C_MUT, C_ACC, G, OUT_TTY, Spinner, accent2, bold, clip, dim, good,
                       info_line, out, pad, sgr, term_size, warn_line, write)
from .utils import fmt_size, fmt_time, tag_time
from .youtube import Ctx, _has, caption_groups, friendly

class Plan:
    def __init__(self, kind: str, **kw):
        self.kind = kind
        self.container = "mkv"
        self.with_audio = True
        self.row = None
        self.convert = None
        self.bitrate = 192
        self.start = None
        self.end = None
        self.precise = False
        self.track = None
        self.source = "manual"
        self.cap_format = "srt"
        self.plain = False
        self.est_bytes = None
        self.summary = ""
        self.__dict__.update(kw)

def safe_filename(name: str, limit: int = 120) -> str:
    try:
        from yt_dlp.utils import sanitize_filename
        name = sanitize_filename(name, restricted=False)
    except Exception:
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return "".join(list(name)[:limit]) or "download"

class DownloadUI:
    PP = {"Merger": "Merging video & audio", "ExtractAudio": "Converting audio",
          "VideoRemuxer": "Finalizing container", "VideoConvertor": "Converting video"}

    def __init__(self):
        self.last = 0.0
        self.spin: Spinner | None = None
        self.bytes_done = 0
        self.t0 = time.monotonic()

    @staticmethod
    def _label(d) -> str:
        i = d.get("info_dict") or {}
        v, a = _has(i, "vcodec"), _has(i, "acodec")
        if v:
            return "Video"
        if a:
            return "Audio"
        return "Data"

    def _bar(self, frac, width):
        if frac is None:
            return sgr(G["off"] * width, C_MUT)
        n = int(round(frac * width))
        return sgr(G["on"] * n, C_ACC) + sgr(G["off"] * (width - n), C_MUT)

    def hook(self, d):
        st = d.get("status")
        cols, _ = term_size()
        if st == "downloading":
            now = time.monotonic()
            if now - self.last < 0.1 or not OUT_TTY:
                return
            self.last = now
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            frac = min(1.0, done / total) if total else None
            speed = d.get("speed")
            eta = d.get("eta")
            width = max(10, min(30, cols - 62))
            pct = f"{frac * 100:5.1f}%" if frac is not None else "  ... "
            line = (f"  {accent2(pad(self._label(d), 6))} {self._bar(frac, width)} {pct}  "
                    f"{fmt_size(done)}{(' / ' + fmt_size(total)) if total else ''}  "
                    f"{dim((fmt_size(speed) + '/s') if speed else '')}  {dim(('ETA ' + fmt_time(eta)) if eta else '')}")
            write("\r\x1b[2K" + clip(line, cols - 1))
        elif st == "finished":
            size = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            self.bytes_done += size
            line = (f"  {accent2(pad(self._label(d), 6))} {self._bar(1.0, max(10, min(30, cols - 62)))} 100.0%  "
                    f"{fmt_size(size)}")
            if OUT_TTY:
                write("\r\x1b[2K" + clip(line, cols - 1) + "\n")
            else:
                out(clip(strip_ansi(line), 100))

    def pp_hook(self, d):
        label = self.PP.get(d.get("postprocessor"))
        if not label:
            return
        if d.get("status") == "started" and not self.spin:
            self.spin = Spinner(label).start()
        elif d.get("status") == "finished" and self.spin:
            self.spin.stop()
            self.spin = None

    def close(self):
        if self.spin:
            self.spin.stop()
            self.spin = None

def preflight_disk(plan: Plan, outdir: Path, force: bool) -> None:
    try:
        free = shutil.disk_usage(outdir).free
    except Exception:
        return
    if plan.est_bytes:
        need = int(plan.est_bytes * 2.2) + 200 * 1024 ** 2
    else:
        need = 1024 ** 3
    if free < need and not force:
        raise YTError(
            f"Not enough free disk space: need about {fmt_size(need)}, have {fmt_size(free)}.",
            "Free some space, choose another folder with -o, or pass --force to try anyway.")

def execute(url: str, info: dict, plan: Plan, ctx: Ctx, force: bool = False) -> Path:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import download_range_func
    target_dir = ctx.outdir / plan.kind
    target_dir.mkdir(parents=True, exist_ok=True)
    preflight_disk(plan, target_dir, force)
    tmp = Path(tempfile.mkdtemp(prefix=f".{APP_NAME}-", dir=target_dir))
    ui = DownloadUI()
    try:
        if plan.kind == "captions":
            return _do_captions(url, info, plan, ctx, tmp, target_dir)
        o = ctx.opts()
        o["paths"] = {"home": str(target_dir), "temp": str(tmp)}
        suffix = ""
        if plan.row:
            suffix += f" {plan.row['label']}" if plan.kind == "video" else ""
        if plan.start is not None:
            suffix += f" [{tag_time(plan.start)}-{tag_time(plan.end)}]"
        if plan.kind == "audio" and plan.convert:
            suffix += f" {plan.bitrate}k"
        o["outtmpl"] = {"default": "%(title).120s [%(id)s]" + suffix.replace("%", "") + ".%(ext)s"}
        o["progress_hooks"] = [ui.hook]
        o["postprocessor_hooks"] = [ui.pp_hook]
        pps = []
        if plan.kind == "video":
            row = plan.row
            fid = row["format_id"]
            if plan.with_audio and not row["muxed"]:
                pref = {"mp4": "[ext=m4a]", "webm": "[ext=webm]"}.get(plan.container)
                o["format"] = (f"{fid}+bestaudio{pref}/{fid}+bestaudio" if pref else f"{fid}+bestaudio")
                o["merge_output_format"] = plan.container
            else:
                o["format"] = fid
                if row["ext"] and row["ext"] != plan.container:
                    pps.append({"key": "FFmpegVideoRemuxer", "preferedformat": plan.container})
        else:
            o["format"] = plan.row["format_id"] if plan.row else "bestaudio/best"
            if plan.convert:
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": plan.convert,
                            "preferredquality": str(plan.bitrate)})
        if pps:
            o["postprocessors"] = pps
        if plan.start is not None:
            o["download_ranges"] = download_range_func(None, [(plan.start, plan.end)])
            if plan.precise:
                o["force_keyframes_at_cuts"] = True
        try:
            with YoutubeDL(o) as ydl:
                res = ydl.extract_info(url, download=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            raise friendly(e, ctx.log)
        finally:
            ui.close()
        path = None
        try:
            path = Path(res["requested_downloads"][0]["filepath"])
        except Exception:
            pass
        if not path or not path.exists():
            vid = info.get("id", "")
            cands = [p for p in target_dir.glob(f"*{vid}*") if p.is_file()]
            path = max(cands, key=lambda p: p.stat().st_mtime) if cands else None
        if not path or not path.exists():
            raise YTError("The download finished but no file was produced.", "Re-run with --verbose to see why.")
        return path
    finally:
        ui.close()
        shutil.rmtree(tmp, ignore_errors=True)

def _do_captions(url, info, plan, ctx, tmp: Path, target_dir: Path) -> Path:
    from yt_dlp import YoutubeDL
    o = ctx.opts()
    o.update({
        "skip_download": True, "writesubtitles": plan.source == "manual",
        "writeautomaticsub": plan.source != "manual",
        "subtitleslangs": [re.escape(plan.track) + "$"] if False else [plan.track],
        "subtitlesformat": "vtt", "outtmpl": str(tmp / "cap.%(ext)s"),
    })
    with Spinner(f"Fetching {plan.track} captions"):
        try:
            with YoutubeDL(o) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            raise friendly(e, ctx.log)
    files = sorted(tmp.glob("*.vtt"))
    if not files:
        raise YTError("No caption file came back for that language.",
                        "YouTube may be rate-limiting translated tracks - wait a minute and retry.")
    raw = files[0].read_text(encoding="utf-8", errors="replace")
    text = convert_vtt(raw, plan.cap_format, plan.plain)
    if not parse_vtt(raw):
        raise YTError("The captions track had no readable text.")
    name = f"{safe_filename(info.get('title') or 'captions')} [{info.get('id', '')}].{plan.track}.{plan.cap_format}"
    path = target_dir / name
    path.write_text(text, encoding="utf-8")
    return path
