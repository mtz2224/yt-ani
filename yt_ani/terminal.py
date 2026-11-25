"""Cross-platform terminal drawing, keyboard input, and menus."""
from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import threading
import time
import unicodedata

from .config import BRAND_ACCENT, BRAND_ACCENT_2
from .errors import Quit


def _enable_vt() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        for std in (-11, -12):
            h = k.GetStdHandle(std)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


def _fg(rgb, fallback):
    return f"38;2;{rgb[0]};{rgb[1]};{rgb[2]}" if TRUECOLOR else fallback


_enable_vt()


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUT_TTY = sys.stdout.isatty()
INTERACTIVE = OUT_TTY and sys.stdin.isatty()
COLOR = OUT_TTY and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
TRUECOLOR = COLOR and (os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
                       or bool(os.environ.get("WT_SESSION")) or os.name == "nt")
UNI = (sys.stdout.encoding or "").lower().replace("-", "").startswith("utf") and not os.environ.get("YT_ASCII")

if UNI:
    G = dict(ok="✔", warn="▲", fail="✖", ptr="❯", dot="•", on="━", off="─", tl="╭", tr="╮", bl="╰",
             br="╯", h="─", v="│", ell="…", mid="·", ud="↑↓", spin="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", prompt="›")
else:
    G = dict(ok="+", warn="!", fail="x", ptr=">", dot="*", on="=", off="-", tl="+", tr="+", bl="+",
             br="+", h="-", v="|", ell="...", mid="-", ud="up/down", spin="|/-\\", prompt=">")

C_ACC = _fg(BRAND_ACCENT, "95")
C_ACC2 = _fg(BRAND_ACCENT_2, "96")
C_OK = _fg((74, 222, 128), "92")
C_WARN = _fg((251, 191, 36), "93")
C_ERR = _fg((248, 113, 113), "91")
C_MUT = _fg((148, 163, 184), "90")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

def sgr(text, *codes) -> str:
    if not COLOR or not codes:
        return str(text)
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

def accent(s): return sgr(s, C_ACC)

def accent2(s): return sgr(s, C_ACC2)

def bold(s): return sgr(s, "1")

def dim(s): return sgr(s, C_MUT)

def good(s): return sgr(s, C_OK)

def warn_c(s): return sgr(s, C_WARN)

def bad(s): return sgr(s, C_ERR)

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

def _cw(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

def vlen(s: str) -> int:
    return sum(_cw(c) for c in strip_ansi(s))

def clip(s: str, width: int) -> str:
    if vlen(s) <= width:
        return s
    out, w, i = [], 0, 0
    while i < len(s):
        m = ANSI_RE.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        cw = _cw(s[i])
        if w + cw > width - 1:
            break
        out.append(s[i])
        w += cw
        i += 1
    return "".join(out) + G["ell"] + ("\x1b[0m" if COLOR else "")

def pad(s: str, width: int, right: bool = False) -> str:
    gap = max(0, width - vlen(s))
    return (" " * gap + s) if right else (s + " " * gap)

def term_size():
    s = shutil.get_terminal_size((80, 24))
    return s.columns, s.lines

def clear_screen() -> None:
    """Clear a real terminal without invoking a shell command."""
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        return
    if os.environ.get("TERM", "").lower() in ("dumb", "unknown"):
        return
    try:
        # ANSI is enabled on supported Windows consoles by _enable_vt().
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
    except OSError:
        pass

def out(s: str = "") -> None:
    sys.stdout.write(s + "\n")
    sys.stdout.flush()

def write(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()

def hide_cursor() -> None:
    if OUT_TTY:
        write("\x1b[?25l")

def show_cursor() -> None:
    if OUT_TTY:
        write("\x1b[?25h")

def gradient(text: str) -> str:
    if not TRUECOLOR:
        return sgr(text, C_ACC, "1")
    n = max(len(text) - 1, 1)
    a, b = BRAND_ACCENT, BRAND_ACCENT_2
    buf = []
    for i, ch in enumerate(text):
        if ch == " ":
            buf.append(ch)
            continue
        t = i / n
        r, g, bl = (int(a[k] + (b[k] - a[k]) * t) for k in range(3))
        buf.append(f"\x1b[1;38;2;{r};{g};{bl}m{ch}")
    return "".join(buf) + "\x1b[0m"

def panel(lines, title: str = "", color: str | None = None, width: int = 76) -> None:
    cols, _ = term_size()
    w = max(12, min(width, max(12, cols - 1)))
    inner = max(8, w - 4)
    col = color or C_ACC
    if title:
        short_title = clip(title, max(1, w - 7))
        top = (sgr(G["tl"] + G["h"] + " ", col) + sgr(short_title, col, "1") +
               sgr(" " + G["h"] * max(0, w - 5 - vlen(short_title)) + G["tr"], col))
    else:
        top = sgr(G["tl"] + G["h"] * (w - 2) + G["tr"], col)
    out(top)
    for line in lines:
        out(sgr(G["v"], col) + " " + pad(clip(line, inner), inner) + " " + sgr(G["v"], col))
    out(sgr(G["bl"] + G["h"] * (w - 2) + G["br"], col))

def step_done(label: str, value: str) -> None:
    out(f"  {good(G['ok'])} {dim(pad(label, 9))} {value}")

def info_line(msg: str) -> None:
    out(f"  {accent2(G['dot'])} {msg}")

def warn_line(msg: str) -> None:
    out(f"  {warn_c(G['warn'])} {msg}")

def fail_line(msg: str) -> None:
    out(f"  {bad(G['fail'])} {msg}")

class Spinner:
    def __init__(self, text: str):
        self.text = text
        self._stop = threading.Event()
        self._t = None

    def start(self):
        if not OUT_TTY:
            return self
        hide_cursor()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def _run(self):
        i = 0
        frames = G["spin"]
        while not self._stop.is_set():
            cols, _ = term_size()
            line = clip(f"  {accent2(frames[i % len(frames)])} {self.text}", cols - 1)
            write("\r\x1b[2K" + line)
            i += 1
            time.sleep(0.08)

    def stop(self, final: str | None = None):
        self._stop.set()
        if self._t:
            self._t.join()
            write("\r\x1b[2K")
            show_cursor()
        if final:
            out(final)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

def read_key() -> str:
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home",
                    "O": "end", "I": "pgup", "Q": "pgdn"}.get(msvcrt.getwch(), "")
        if ch == "\r":
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x1b":
            return "esc"
        if ch == "\x08":
            return "backspace"
        return ch
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        b = os.read(fd, 1)
        if b == b"\x1b":
            if select.select([fd], [], [], 0.04)[0]:
                seq = os.read(fd, 8)
                table = {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left",
                         b"OA": "up", b"OB": "down", b"OC": "right", b"OD": "left",
                         b"[H": "home", b"[F": "end", b"[5~": "pgup", b"[6~": "pgdn",
                         b"[1~": "home", b"[4~": "end"}
                return table.get(seq, "")
            return "esc"
        if b in (b"\r", b"\n"):
            return "enter"
        if b in (b"\x7f", b"\x08"):
            return "backspace"
        return b.decode("utf-8", "ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def select(title: str, items, *, header: str = "", hint: str = "", hotkeys: dict | None = None,
           start: int = 0, label: str | None = None):
    """items: list of (cols, badge). Returns ('item', i) | ('hotkey', key) | ('back', None)."""
    hotkeys = hotkeys or {}
    ncols = max(len(c) for c, _ in items)
    widths = [max(vlen(c[i]) if i < len(c) else 0 for c, _ in items) for i in range(ncols)]

    def row_text(cols, badge):
        parts = []
        for i in range(ncols):
            txt = cols[i] if i < len(cols) else ""
            parts.append(pad(txt, widths[i], right=(i == ncols - 1 and ncols > 1 and i > 0 and False)))
        t = "  ".join(parts)
        return t + (("  " + badge) if badge else "")

    if not INTERACTIVE:
        out(f"  {bold(title)}")
        for i, (cols, badge) in enumerate(items, 1):
            out(f"   {i:>2}. {strip_ansi(row_text(cols, badge))}")
        keys = "/".join(hotkeys) if hotkeys else ""
        while True:
            try:
                raw = input(f"  {G['prompt']} choose 1-{len(items)}" +
                            (f" [{keys}]" if keys else "") + f" (b=back, q=quit) [{start + 1}]: ").strip().lower()
            except EOFError:
                raise Quit
            if raw == "":
                return ("item", start)
            if raw == "q":
                raise Quit
            if raw == "b":
                return ("back", None)
            if raw in hotkeys:
                return ("hotkey", raw)
            if raw.isdigit() and 1 <= int(raw) <= len(items):
                return ("item", int(raw) - 1)

    idx = max(0, min(start, len(items) - 1))
    top = 0
    _, th = term_size()
    visible = max(3, min(len(items), th - 8, 16))
    prev = 0
    hide_cursor()
    try:
        while True:
            cols_n, _ = term_size()
            if idx < top:
                top = idx
            if idx >= top + visible:
                top = idx - visible + 1
            lines = [f"  {accent(G['prompt'])} {bold(title)}"]
            if header:
                lines.append(f"    {dim(header)}")
            more_up = top > 0
            more_dn = top + visible < len(items)
            for i in range(top, min(len(items), top + visible)):
                cols, badge = items[i]
                body = row_text(cols, badge)
                if i == idx:
                    lines.append(f"  {accent(G['ptr'])} {bold(body)}")
                else:
                    lines.append(f"    {body}")
            foot = f"{G['ud']} move  {G['mid']}  enter select  {G['mid']}  esc back  {G['mid']}  q quit"
            for k, name in hotkeys.items():
                foot += f"  {G['mid']}  {k} {name}"
            if len(items) > visible:
                foot += f"  {G['mid']}  {idx + 1}/{len(items)}"
            lines.append(f"    {dim(foot)}")
            lines = [clip(l, cols_n - 1) for l in lines]
            if prev:
                write(f"\x1b[{prev}A")
            write("".join("\x1b[2K\r" + l + "\n" for l in lines))
            prev = len(lines)
            k = read_key()
            if k in ("up", "k"):
                idx = (idx - 1) % len(items)
            elif k in ("down", "j"):
                idx = (idx + 1) % len(items)
            elif k == "home":
                idx = 0
            elif k == "end":
                idx = len(items) - 1
            elif k == "pgup":
                idx = max(0, idx - visible)
            elif k == "pgdn":
                idx = min(len(items) - 1, idx + visible)
            elif k == "enter" or k == "right":
                result = ("item", idx)
                break
            elif k in ("esc", "left", "backspace"):
                result = ("back", None)
                break
            elif k == "q":
                result = None
                break
            elif k in hotkeys:
                result = ("hotkey", k)
                break
    finally:
        if prev:
            write(f"\x1b[{prev}A\x1b[J")
        show_cursor()
    if result is None:
        raise Quit
    if result[0] == "item":
        cols, _ = items[result[1]]
        step_done(label or title, " ".join(c for c in (strip_ansi(x) for x in cols) if c))
    return result

def ask(label: str, default: str | None = None) -> str:
    sfx = f" {dim('(' + default + ')')}" if default else ""
    try:
        v = input(f"  {accent(G['prompt'])} {label}{sfx} ").strip()
    except EOFError:
        raise Quit
    return v or (default or "")

def confirm(label: str, default: bool = True) -> bool:
    if not INTERACTIVE:
        return default
    hint = "Y/n" if default else "y/N"
    try:
        v = input(f"  {accent(G['prompt'])} {label} {dim('[' + hint + ']')} ").strip().lower()
    except EOFError:
        raise Quit
    if not v:
        return default
    return v in ("y", "yes")

atexit.register(show_cursor)
