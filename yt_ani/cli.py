"""CLI parsing and application entry point."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from .config import (APP_NAME, APP_SLUG, APP_TAGLINE, APP_VERSION, DEFAULT_OUTPUT_DIR,
                     DONATE_INTRO, DONATE_METHODS, DONATE_NOTE, DONATE_TITLE)
from .dependencies import (cmd_doctor, cmd_update, ensure_ready,
                           maybe_reexec_in_venv)
from .downloads import Plan, execute
from .errors import Quit, YTError
from .screens import banner, cmd_info, print_error, success_panel, video_card
from .terminal import (C_ACC2, G, INTERACTIVE, Spinner, accent, bold, dim, good, out,
                       panel, select, show_cursor, term_size, warn_c, warn_line, info_line)
from .utils import fmt_size, parse_time
from .workflows import _scaled, interactive
from .youtube import Ctx, analyze, build_audio_rows, build_video_rows, caption_groups, recommended_index

COMMANDS = {"get", "info", "doctor", "update", "donate"}

def pick_row(rows: list[dict], q: str | None) -> dict:
    if not q or q == "recommended":
        return rows[recommended_index(rows)]
    if q == "best":
        return rows[0]
    if q == "worst":
        return rows[-1]
    m = re.fullmatch(r"(\d{3,4})p?(\d{2})?", q.lower())
    if not m:
        raise YTError(f"Unknown quality '{q}'.", "Use best, recommended, worst, or a height like 1080 / 720 / 1080p60.")
    h, f = int(m.group(1)), int(m.group(2) or 0)
    exact = [r for r in rows if r["height"] == h and (not f or r["fps"] == f)]
    if exact:
        return exact[0]
    lower = [r for r in rows if r["height"] <= h]
    if lower:
        warn_line(f"{h}p isn't available - using {lower[0]['label']}.")
        return lower[0]
    warn_line(f"{h}p isn't available - using {rows[-1]['label']}.")
    return rows[-1]

def plan_from_args(info: dict, a) -> Plan:
    dur = info.get("duration")
    rng = None
    if a.start is not None or a.end is not None:
        s = parse_time(a.start) if a.start is not None else 0.0
        e = parse_time(a.end) if a.end is not None else dur
        if e is None:
            raise YTError("This video has no known length - pass --end too.")
        if dur:
            e = min(e, dur)
        if s < 0 or e <= s:
            raise YTError("--end must be after --start and inside the video.")
        rng = (s, e)
    if a.type == "video":
        rows = build_video_rows(info, a.container, not a.no_audio)
        if not rows:
            raise YTError("No video formats are available for those settings.")
        row = pick_row(rows, a.quality)
        plan = Plan("video", container=a.container, with_audio=not a.no_audio, row=row)
        plan.est_bytes = row["size"]
        plan.summary = f"{row['label']} {row['codec']} {a.container.upper()}"
    elif a.type == "audio":
        rows = build_audio_rows(info)
        if not rows:
            raise YTError("No audio streams are available.")
        plan = Plan("audio", row=rows[0])
        plan.est_bytes = rows[0]["size"]
        if a.audio_format != "original":
            plan.convert, plan.bitrate = a.audio_format, a.bitrate
            plan.est_bytes = int(a.bitrate * 1000 / 8 * dur) if dur else None
        plan.summary = ("Original" if a.audio_format == "original" else f"{a.audio_format.upper()} {a.bitrate} kbps")
    else:
        g = caption_groups(info)
        allt = ([(k, "manual") for k, _ in g["manual"]] + [(k, "automatic") for k, _ in g["automatic"]]
                + [(k, "translated") for k, _ in g["translated"]])
        if not allt:
            raise YTError("This video has no captions.")
        lang = a.lang
        if not lang:
            lang = allt[0][0]
        order = [a.source] if a.source else ["manual", "automatic", "translated"]
        found = next(((k, s) for s in order for k, _ in g[s] if k == lang or (s == "automatic" and k == f"{lang}-orig")), None)
        if not found:
            avail = ", ".join(k for k, _ in allt[:20])
            raise YTError(f"No '{lang}' captions found.", f"Available: {avail}{' ...' if len(allt) > 20 else ''}")
        plan = Plan("captions", track=found[0], source=found[1], cap_format=a.sub_format, plain=a.plain)
        plan.summary = f"{found[0]} {a.sub_format.upper()} captions"
        return plan
    if rng:
        plan.start, plan.end, plan.precise = rng[0], rng[1], a.precise
        plan.est_bytes = _scaled(plan.est_bytes, rng, dur)
    return plan

def cmd_get(args, ctx) -> int:
    explicit = any(v is not None for v in (args.type_given,)) or args.quality or args.start or args.end
    if INTERACTIVE and not explicit:
        return interactive(args, ctx)
    needs_ffmpeg = (
        args.type == "video"
        or (args.type == "audio" and (args.audio_format != "original" or args.start is not None or args.end is not None))
    )
    ensure_ready(ctx, need_ffmpeg=needs_ffmpeg)
    url, _ = validate_url(args.url)
    with Spinner("Analyzing video"):
        info = analyze(url, ctx)
    video_card(info)
    plan = plan_from_args(info, args)
    info_line(f"{plan.summary}" + (f"  {dim('~' + fmt_size(plan.est_bytes))}" if plan.est_bytes else ""))
    started = time.monotonic()
    path = execute(url, info, plan, ctx, force=args.force)
    success_panel(path, started)
    return 0

def copy_to_clipboard(text: str) -> bool:
    if sys.platform == "win32":
        cmds = [["clip"]]
    elif sys.platform == "darwin":
        cmds = [["pbcopy"]]
    else:
        cmds = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for c in cmds:
        if shutil.which(c[0]):
            try:
                subprocess.run(c, input=text.encode(), check=True, timeout=3)
                return True
            except Exception:
                continue
    return False

def cmd_donate(args, ctx) -> int:
    cols, _ = term_size()
    inner = max(30, min(76, cols - 1) - 4)
    lines = [bold(DONATE_TITLE), ""]
    lines += textwrap.wrap(DONATE_INTRO, inner) + [""]
    for m in DONATE_METHODS:
        lines.append(f"{accent(m['name'])}  {dim(m['kind'])}")
        lines.append(f"  {bold(m['number'])}")
        lines.append("")
    lines += [dim(l) for l in textwrap.wrap(DONATE_NOTE, inner)]
    banner() if INTERACTIVE else None
    panel(lines, "Support " + APP_NAME, C_ACC2)
    keys = {m["key"]: m for m in DONATE_METHODS}
    if args.copy:
        m = keys.get(args.copy.lower())
        if not m:
            raise YTError(f"Unknown method '{args.copy}'.", "Use: " + ", ".join(keys))
        ok = copy_to_clipboard(m["number"])
        out(f"  {good(G['ok'])} Copied {m['name']} number." if ok else f"  {warn_c(G['warn'])} No clipboard tool found - number: {m['number']}")
        return 0
    if INTERACTIVE:
        while True:
            items = [([bold(f"Copy {m['name']} number"), dim(m["number"])], "") for m in DONATE_METHODS]
            items.append(([bold("Done"), ""], ""))
            res = select("Copy a number?", items, label="Donate")
            if res[0] == "back" or res[1] == len(DONATE_METHODS):
                break
            m = DONATE_METHODS[res[1]]
            ok = copy_to_clipboard(m["number"])
            out(f"  {good(G['ok'])} Copied!" if ok else f"  {warn_c(G['warn'])} No clipboard tool found - number: {m['number']}")
        out(f"  {dim('Thank you for supporting ' + APP_NAME + '.')}\n")
    return 0

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-o", "--output", metavar="DIR",
        help=f"output root; creates video/audio/captions inside it (default: {DEFAULT_OUTPUT_DIR}; also set YT_ANI_DIR)",
    )
    common.add_argument("--cookies-from-browser", metavar="BROWSER", help="use cookies from firefox, chrome, edge, brave...")
    common.add_argument("--cookies", metavar="FILE", help="Netscape cookies.txt file")
    common.add_argument("--verbose", action="store_true", help="show yt-dlp's own messages")

    p = argparse.ArgumentParser(
        prog=APP_SLUG, description=f"{APP_NAME} - {APP_TAGLINE}", parents=[common],
        epilog="Only download content you have the right to save.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    sub = p.add_subparsers(dest="cmd")

    g = sub.add_parser("get", parents=[common], help="download a video, audio or captions")
    g.add_argument("url", nargs="?")
    g.add_argument("-t", "--type", choices=["video", "audio", "captions"], default=None)
    g.add_argument("-q", "--quality", help="best | recommended | worst | 1080 | 720 | 1080p60 ...")
    g.add_argument("-c", "--container", choices=["mp4", "webm", "mkv"], default="mkv")
    g.add_argument("--no-audio", action="store_true", help="video only (no sound)")
    g.add_argument("--audio-format", choices=["original", "mp3", "m4a"], default="original")
    g.add_argument("--bitrate", type=int, choices=[96, 128, 192, 256, 320], default=192)
    g.add_argument("--lang", help="caption language code, e.g. en, ar")
    g.add_argument("--source", choices=["manual", "automatic", "translated"])
    g.add_argument("--sub-format", choices=["srt", "vtt", "txt"], default="srt")
    g.add_argument("--plain", action="store_true", help="captions: plain text without timestamps (txt)")
    g.add_argument("--start", help="trim start (90, 1:30, 1h2m3s)")
    g.add_argument("--end", help="trim end")
    g.add_argument("--precise", action="store_true", help="precise cut (re-encodes at cuts)")
    g.add_argument("--force", action="store_true", help="skip the free-disk-space check")

    i = sub.add_parser("info", parents=[common], help="show available qualities, audio and captions")
    i.add_argument("url")
    d = sub.add_parser("doctor", parents=[common], help="check what YT needs and fix it")
    d.add_argument("--fix", action="store_true", help="install/update everything without asking")
    sub.add_parser("update", parents=[common], help="update yt-dlp")
    n = sub.add_parser("donate", parents=[common], help="support yt ani")
    n.add_argument("--copy", metavar="METHOD", help="copy a number: " + ", ".join(m["key"] for m in DONATE_METHODS))
    return p

def normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["get"]
    if any(a in COMMANDS for a in argv[:1]):
        return argv
    if argv[0] in ("-h", "--help", "--version"):
        return argv
    return ["get"] + argv

def main(argv=None) -> int:
    maybe_reexec_in_venv()
    argv = normalize_argv(list(sys.argv[1:] if argv is None else argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "get":
        args.type_given = args.type
        args.type = args.type or "video"
        if not args.url and not INTERACTIVE:
            parser.error("a YouTube link is required")
    ctx = Ctx(args)
    try:
        if args.cmd == "get":
            return cmd_get(args, ctx)
        if args.cmd == "info":
            return cmd_info(args, ctx)
        if args.cmd == "doctor":
            return cmd_doctor(args, ctx)
        if args.cmd == "update":
            return cmd_update(args, ctx)
        if args.cmd == "donate":
            return cmd_donate(args, ctx)
    except YTError as e:
        print_error(e)
        return 1
    except Quit:
        out()
        return 0
    except KeyboardInterrupt:
        show_cursor()
        out("\n  " + dim("Cancelled."))
        return 130
    return 0
