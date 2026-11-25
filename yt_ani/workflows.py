"""Interactive quality, audio, caption and download workflows."""
from __future__ import annotations

import time
from pathlib import Path

from .config import APP_NAME
from .dependencies import ensure_ready
from .downloads import Plan, execute
from .errors import Quit, YTError
from .screens import (print_error, project_details_page, success_panel, video_card,
                      welcome_panel)
from .terminal import (G, INTERACTIVE, Spinner, accent, bold, clear_screen, confirm, dim, good,
                       info_line, out, panel, select, warn_line, write, ask)
from .utils import fmt_size, fmt_time, parse_time
from .youtube import (Ctx, analyze, build_audio_rows, build_video_rows, caption_groups,
                      recommended_index, size_text, validate_url)

BACK = object()

def ask_range(info: dict):
    dur = info.get("duration")
    res = select("Range", [([f"Full video", dim(fmt_time(dur))], ""), (["Trim a section", dim("start / end")], "")],
                 label="Range")
    if res[0] == "back":
        return BACK
    if res[1] == 0:
        return None
    while True:
        try:
            s = parse_time(ask("Start", "0:00"))
            e_raw = ask("End", fmt_time(dur) if dur else "")
            e = parse_time(e_raw) if e_raw else dur
            if e is None:
                raise YTError("This video has no known length - enter an end time.")
            if s < 0 or e <= s or (dur and e > dur + 0.5):
                raise YTError("The end must be after the start and inside the video.")
            if dur:
                e = min(e, dur)
            precise = confirm("Precise cut? (re-encodes at the cuts, slower)", False)
            return (s, e, precise)
        except YTError as ex:
            warn_line(ex.message + (" " + ex.hint if ex.hint else ""))

def _scaled(size, plan_range, dur):
    if not size or not plan_range or not dur:
        return size
    return int(size * max(0.0, min(1.0, (plan_range[1] - plan_range[0]) / dur)))

def flow_video(info: dict, ctx: Ctx):
    container, with_audio, pos = "mkv", True, None
    while True:
        rows = build_video_rows(info, container, with_audio)
        if not rows:
            warn_line("No video formats available for these settings.")
            if not with_audio:
                with_audio = True
                continue
            return None
        rec = recommended_index(rows)
        items = []
        for i, r in enumerate(rows):
            items.append(([bold(r["label"]), dim(f"{r['fps']} fps"), r["codec"],
                           size_text(r["size"], r["estimated"])],
                          good("recommended") if i == rec else ""))
        header = f"{container.upper()} {G['mid']} " + ("with audio" if with_audio else "video only")
        res = select("Quality", items, header=header, hotkeys={"a": "audio on/off", "c": "container"},
                     start=rec if pos is None else pos, label="Quality")
        if res[0] == "back":
            return None
        if res[0] == "hotkey":
            if res[1] == "a":
                with_audio = not with_audio
            else:
                container = {"mp4": "webm", "webm": "mkv", "mkv": "mp4"}[container]
            continue
        pos = res[1]
        row = rows[pos]
        rng = ask_range(info)
        if rng is BACK:
            continue
        plan = Plan("video", container=container, with_audio=with_audio, row=row)
        plan.est_bytes = row["size"]
        if rng:
            plan.start, plan.end, plan.precise = rng
            plan.est_bytes = _scaled(row["size"], rng, info.get("duration"))
        plan.summary = (f"{row['label']} {row['codec']} {G['mid']} {container.upper()} {G['mid']} "
                        + ("with audio" if with_audio else "video only"))
        return plan

def flow_audio(info: dict, ctx: Ctx):
    rows = build_audio_rows(info)
    dur = info.get("duration")
    best = rows[0] if rows else None
    while True:
        items = []
        if best:
            items.append(([bold("Original"), f"{best['abr']} kbps {best['ext']}", size_text(best["size"], best["estimated"])],
                          good("best quality")))
        items.append(([bold("MP3"), "converted", dim("choose bitrate")], ""))
        items.append(([bold("M4A"), "converted (AAC)", dim("choose bitrate")], ""))
        if len(rows) > 1:
            items.append(([bold("Pick a stream"), f"{len(rows)} available", ""], ""))
        res = select("Audio", items, label="Audio")
        if res[0] == "back":
            return None
        names = [("orig" if best else None), "mp3", "m4a", ("pick" if len(rows) > 1 else None)]
        names = [n for n in names if n]
        choice = names[res[1]]
        plan = Plan("audio")
        if choice == "orig":
            plan.row = best
            plan.est_bytes = best["size"]
            plan.summary = f"Original {best['abr']} kbps {best['ext']}"
        elif choice == "pick":
            sub = [([bold(f"{r['abr']} kbps"), r["codec"], r["ext"], size_text(r["size"], r["estimated"]), dim(r["lang"])], "")
                   for r in rows]
            r2 = select("Stream", sub, label="Stream")
            if r2[0] == "back":
                continue
            plan.row = rows[r2[1]]
            plan.est_bytes = plan.row["size"]
            plan.summary = f"{plan.row['abr']} kbps {plan.row['ext']}"
        else:
            rates = [128, 192, 256, 320]
            sub = [([bold(f"{r} kbps"), dim("~" + fmt_size(r * 1000 / 8 * dur) if dur else "")], good("recommended") if r == 192 else "")
                   for r in rates]
            r2 = select("Bitrate", sub, start=1, label="Bitrate")
            if r2[0] == "back":
                continue
            plan.convert, plan.bitrate = choice, rates[r2[1]]
            plan.row = best
            plan.est_bytes = int(plan.bitrate * 1000 / 8 * dur) if dur else None
            plan.summary = f"{choice.upper()} {plan.bitrate} kbps"
        rng = ask_range(info)
        if rng is BACK:
            continue
        if rng:
            plan.start, plan.end, plan.precise = rng
            plan.est_bytes = _scaled(plan.est_bytes, rng, dur)
        return plan

def flow_captions(info: dict, ctx: Ctx):
    g = caption_groups(info)
    labels = {"manual": "Manual captions", "automatic": "Auto-generated", "translated": "Auto-translated"}
    present = [k for k in ("manual", "automatic", "translated") if g[k]]
    if not present:
        warn_line("This video has no captions.")
        return None
    while True:
        res = select("Source", [([bold(labels[k]), dim(f"{len(g[k])} languages")], "") for k in present], label="Source")
        if res[0] == "back":
            return None
        source = present[res[1]]
        tracks = g[source]
        if len(tracks) > 15:
            q = ask("Filter languages (Enter = show all)").lower()
            if q:
                tracks = [t for t in tracks if q in t[0].lower() or q in t[1].lower()] or tracks
        r2 = select("Language", [([bold(k), n], "") for k, n in tracks], label="Language")
        if r2[0] == "back":
            continue
        track = tracks[r2[1]][0]
        r3 = select("Format", [([bold("SRT"), dim("most players & editors")], good("recommended")),
                               ([bold("VTT"), dim("web / HTML5")], ""),
                               ([bold("TXT"), dim("plain text")], "")], label="Format")
        if r3[0] == "back":
            continue
        fmt = ("srt", "vtt", "txt")[r3[1]]
        plain = confirm("Plain text without timestamps?", True) if fmt == "txt" else False
        plan = Plan("captions", track=track, source=("manual" if source == "manual" else source),
                    cap_format=fmt, plain=plain)
        plan.summary = f"{track} {G['mid']} {fmt.upper()} captions"
        return plan

def redraw_download_screen(info: dict, ctx: Ctx) -> None:
    """Repaint the current session after Details or Clear screen."""
    welcome_panel(ctx)
    video_card(info)

def choose_plan(info: dict, ctx: Ctx):
    start = 0
    while True:
        items = [([bold("Video"), dim("pick a quality")], ""),
                 ([bold("Audio"), dim("original, MP3 or M4A")], ""),
                 ([bold("Captions"), dim("SRT / VTT / TXT")], ""),
                 ([bold("Project details"), dim("features, controls, save folder, website and support")], ""),
                 ([bold("Clear screen"), dim("clear the terminal and redraw this page")], "")]
        res = select("What do you want?", items, start=start, label="Type")
        if res[0] == "back":
            return None
        start = res[1]
        if res[1] == 3:
            project_details_page(ctx)
            redraw_download_screen(info, ctx)
            start = 0
            continue
        if res[1] == 4:
            redraw_download_screen(info, ctx)
            start = 0
            continue
        plan = (flow_video, flow_audio, flow_captions)[res[1]](info, ctx)
        if plan is None:
            continue
        lines = [f"{bold('Title')}   {info.get('title') or ''}", f"{bold('Option')}  {plan.summary}"]
        if plan.start is not None:
            lines.append(f"{bold('Range')}   {fmt_time(plan.start)} {G['mid']} {fmt_time(plan.end)}")
        if plan.est_bytes:
            lines.append(f"{bold('Size')}    ~{fmt_size(plan.est_bytes)}")
        lines.append(f"{bold('Folder')}  {ctx.outdir / plan.kind}")
        panel(lines, "Ready")
        if confirm("Start download?", True):
            return plan

def interactive(args, ctx: Ctx) -> int:
    # Finish all downloads/installations before displaying the first UI screen.
    ensure_ready(ctx, need_ffmpeg=True, need_image=True)
    welcome_panel(ctx)
    pending = args.url if getattr(args, "url", None) else None
    while True:
        try:
            if pending:
                raw = pending
            else:
                write(f"  {accent(G['prompt'])} ")
                try:
                    raw = input().strip()
                except EOFError:
                    raise Quit
            pending = None
            if raw.strip().lower() in ("q", "quit", "exit"):
                return 0
            url, _ = validate_url(raw)
            with Spinner("Analyzing video"):
                info = analyze(url, ctx)
        except YTError as e:
            print_error(e)
            continue
        video_card(info)
        plan = choose_plan(info, ctx)
        if plan is None:
            continue
        out()
        started = time.monotonic()
        try:
            path = execute(url, info, plan, ctx)
        except KeyboardInterrupt:
            out()
            warn_line("Cancelled - partial files removed.")
            continue
        except YTError as e:
            print_error(e)
            continue
        success_panel(path, started)
        # Return directly to the link prompt; no donation pop-up or extra question.
        out()
