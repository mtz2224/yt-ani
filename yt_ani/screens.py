"""User-facing TUI screens and dashboard composition."""
from __future__ import annotations

import re
import time
from pathlib import Path

from .config import (APP_NAME, APP_SLUG, APP_TAGLINE, APP_VERSION, DONATE_METHODS,
                     WEBSITE_URL)
from .dependencies import ensure_ready
from .errors import YTError
from .terminal import (C_ACC, C_ACC2, C_OK, G, INTERACTIVE, Spinner, accent, accent2, bold,
                       clip, clear_screen, dim, fail_line, good, out, pad, panel, select, term_size,
                       warn_c, write)
from .ui.image import draw_avatar
from .utils import fmt_count, fmt_size, fmt_time
from .youtube import (Ctx, analyze, build_audio_rows, build_video_rows, caption_groups,
                      recommended_index, size_text, validate_url)


def banner() -> None:
    """Small text banner for utility pages (not the home dashboard)."""
    out("  " + accent(f"✦  {APP_NAME}  ✦"))
    out("  " + dim(f"{APP_TAGLINE}  ·  v{APP_VERSION}"))
    out()


def _cursor(row: int, col: int) -> None:
    write(f"\x1b[{max(1, row)};{max(1, col)}H")


def dashboard_geometry(cols: int, rows: int) -> dict:
    """Return a responsive, left-image dashboard layout in terminal cells."""
    if cols >= 76:
        available_rows = max(10, rows - 3)
        image_width = min(58, max(30, int(cols * 0.52)), available_rows * 2)
        return {
            "mode": "side",
            "image_width": image_width,
            "image_max_height": available_rows,
            "text_col": image_width + 4,
            "text_width": max(18, cols - image_width - 4),
        }

    # Narrow terminals stack the artwork first, then use a compact menu summary.
    image_max_height = max(6, min(13, rows - 13))
    image_width = max(12, min(cols - 2, 2 * image_max_height))
    return {
        "mode": "stack",
        "image_width": image_width,
        "image_max_height": image_max_height,
        "text_col": 1,
        "text_width": max(12, cols - 1),
    }


def _home_lines(ctx: Ctx, width: int, compact: bool = False) -> list[str]:
    folder = str(ctx.outdir)
    limit = max(10, width - (7 if compact else 2))
    if len(folder) > limit:
        folder = "…" + folder[-(limit - 1):]

    if compact:
        lines = [
            accent(f"✦ {APP_NAME} ✦  v{APP_VERSION}"),
            f"{accent('VIDEO')}  Quality / format",
            f"{accent('AUDIO')}  MP3 / M4A",
            f"{accent('CAPTIONS')}  Subtitles",
            f"{accent('DETAILS')}  Project guide",
            f"{accent('CLEAR')}  Redraw",
            dim("↑↓ Enter · Esc · Q"),
            dim("Save: ") + folder,
            accent2("Paste YouTube link below"),
        ]
        if width < 30:
            lines = [
                accent(f"✦ {APP_NAME} ✦ v{APP_VERSION}"),
                "VIDEO · AUDIO · CAPTIONS",
                "DETAILS · CLEAR",
                dim("↑↓ Enter · Esc · Q"),
                dim("Save: ") + folder,
                accent2("Paste YouTube link"),
            ]
        return lines

    return [
        accent(f"✦  {APP_NAME}  ✦"),
        dim(f"{APP_TAGLINE}  ·  v{APP_VERSION}"),
        "",
        bold("DOWNLOAD STUDIO"),
        f"{accent('VIDEO')}      Resolution and format",
        f"{accent('AUDIO')}      Original / MP3 / M4A",
        f"{accent('CAPTIONS')}   SRT / VTT / TXT",
        f"{accent('DETAILS')}    Guide, controls and support",
        f"{accent('CLEAR')}      Redraw the screen",
        "",
        dim("Keys  ↑↓ / Enter · Esc back · Q quit"),
        dim("Save folder"),
        folder,
        accent2("Paste a YouTube link below"),
    ]


def welcome_panel(ctx: Ctx) -> None:
    """Show the original artwork prominently on the left, without cropping."""
    cols, rows = term_size()
    clear_screen()
    layout = dashboard_geometry(cols, rows)

    try:
        image_width, image_height, _renderer = draw_avatar(
            layout["image_width"], layout["image_max_height"]
        )
    except Exception as exc:
        # Never hide a rendering failure silently; dependency setup should make
        # this rare, and the exact reason is useful when diagnosing a terminal.
        image_width = image_height = 0
        out(warn_c(f"  Artwork preview unavailable: {type(exc).__name__}: {exc}"))

    if layout["mode"] == "side" and image_width:
        text_col = image_width + 4
        text_width = max(16, cols - text_col + 1)
        lines = _home_lines(ctx, text_width)
        for row, line in enumerate(lines, 1):
            _cursor(row, text_col)
            write(clip(line, text_width) + "\x1b[K")
        _cursor(max(image_height, len(lines)) + 2, 1)
        return

    # Stacked mode is left-aligned. It deliberately uses a shorter set of lines
    # so the image and the menu fit small terminal heights without scrolling.
    start_row = image_height + 2 if image_height else 1
    lines = _home_lines(ctx, max(12, cols - 1), compact=True)
    for row, line in enumerate(lines, start_row):
        _cursor(row, 1)
        write(clip(line, max(12, cols - 1)) + "\x1b[K")
    _cursor(start_row + len(lines) + 1, 1)

def video_card(info: dict) -> None:
    meta = [info.get("channel") or info.get("uploader") or "Unknown channel", fmt_time(info.get("duration"))]
    if info.get("view_count"):
        meta.append(f"{fmt_count(info['view_count'])} views")
    ud = info.get("upload_date") or ""
    if re.fullmatch(r"\d{8}", ud):
        meta.append(f"{ud[:4]}-{ud[4:6]}-{ud[6:]}")
    panel([bold(info.get("title") or "Untitled"), dim(f" {G['mid']} ".join(meta))], "Video found")

def success_panel(path: Path, started: float) -> None:
    elapsed = max(0.1, time.monotonic() - started)
    size = path.stat().st_size
    panel([f"{good(G['ok'])} {bold('Saved')}", f"{path}",
           dim(f"{fmt_size(size)}  {G['mid']}  {elapsed:.0f}s  {G['mid']}  {fmt_size(size / elapsed)}/s")],
          "Done", C_OK)

def project_details_page(ctx: Ctx) -> None:
    """Show the project information as the fourth option in the download menu."""
    website = WEBSITE_URL.strip() or "Coming soon — not published yet"
    lines = [
        bold("A simple, focused YouTube download studio."),
        "",
        f"{accent('VIDEO')}      Select resolution, FPS, codec and MP4 / WEBM / MKV",
        f"{accent('AUDIO')}      Save the original stream or convert to MP3 / M4A",
        f"{accent('CAPTIONS')}   Download manual, automatic or translated subtitles",
        f"{accent('TRIM')}       Save a selected section using start and end timestamps",
        "",
        bold("Navigation"),
        "Arrow keys / J-K  Move between choices",
        "Enter             Select / continue",
        "Esc               Go back",
        "Q                 Quit",
        "",
        bold("Default save folder"),
        str(ctx.outdir),
        "Override with --output DIR or YT_ANI_DIR.",
        "",
        bold("Support the project"),
        "Vodafone Cash  ·  01009610342",
        "Donations are optional and do not unlock extra features.",
        "",
        bold("Official website"),
        website,
        "",
        dim("Only download content you have the right to save."),
    ]
    panel(lines, "yt ani  /  PROJECT DETAILS", C_ACC2, width=84)
    if INTERACTIVE:
        select("Details", [([bold("Back to download choices"), dim("return to Video / Audio / Captions")], "")],
               label="Page")

def print_error(e: YTError) -> None:
    out()
    fail_line(e.message)
    if e.hint:
        out("    " + dim(e.hint))
    out()

def cmd_info(args, ctx) -> int:
    ensure_ready(ctx, need_ffmpeg=False)
    url, _ = validate_url(args.url)
    with Spinner("Analyzing video"):
        info = analyze(url, ctx)
    video_card(info)
    rows = build_video_rows(info, "mp4", True)
    rec = recommended_index(rows) if rows else -1
    out(f"\n  {bold('Video')}  {dim('(audio is merged in automatically)')}")
    for i, r in enumerate(rows):
        out(f"    {pad(r['label'], 7)} {pad(str(r['fps']) + ' fps', 7)} {pad(r['codec'], 6)} "
            f"{pad(size_text(r['size'], r['estimated']), 10)} {good('recommended') if i == rec else ''}")
    arows = build_audio_rows(info)
    out(f"\n  {bold('Audio')}")
    for r in arows[:8]:
        out(f"    {pad(str(r['abr']) + ' kbps', 9)} {pad(r['codec'], 6)} {pad(r['ext'], 5)} "
            f"{pad(size_text(r['size'], r['estimated']), 10)} {dim(r['lang'])}")
    g = caption_groups(info)
    out(f"\n  {bold('Captions')}  {dim('manual')} {len(g['manual'])}  {dim('auto')} {len(g['automatic'])}  "
        f"{dim('translated')} {len(g['translated'])}")
    for k, n in (g["manual"] + g["automatic"])[:8]:
        out(f"    {pad(k, 10)} {dim(n)}")
    out()
    return 0
