"""Automatic setup for yt-dlp, FFmpeg, Deno, and the image renderer."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

from .config import APP_NAME, APP_SLUG, APP_VERSION, DENO_DIR, ENTRY_SCRIPT, HOME_DIR, VENV_DIR, is_termux
from .errors import YTError
from .terminal import (Spinner, accent, bad, bold, confirm, dim, fail_line, good, out, pad,
                       panel, warn_c, warn_line)
from .utils import fmt_size

DENO_MINIMUM = (2, 3, 0)
NEED_REEXEC = False
_FFMPEG = {}

def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

def externally_managed() -> bool:
    try:
        return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()
    except Exception:
        return False

def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def reexec_in_venv() -> None:
    vp = venv_python()
    env = dict(os.environ, YT_REEXEC="1")
    entry = Path(sys.argv[0]).resolve()
    if entry.name == "__main__.py":
        args = [str(vp), "-m", "yt_ani", *sys.argv[1:]]
    else:
        if not entry.exists():
            entry = ENTRY_SCRIPT
        args = [str(vp), str(entry), *sys.argv[1:]]
    if os.name == "nt":
        sys.exit(subprocess.call(args, env=env))
    os.execve(str(vp), args, env)

def maybe_reexec_in_venv() -> None:
    if in_venv() or os.environ.get("YT_NO_VENV") or os.environ.get("YT_REEXEC"):
        return
    if venv_python().exists():
        reexec_in_venv()

def install_packages(pkgs: list[str], upgrade: bool = False) -> bool:
    """pip install into the current environment, or into ~/.yt/venv on 'externally managed' Pythons."""
    global NEED_REEXEC
    target = sys.executable
    if not in_venv() and externally_managed():
        vp = venv_python()
        if not vp.exists():
            try:
                import venv
                with Spinner("Creating an isolated environment (~/.yt/venv)"):
                    venv.EnvBuilder(with_pip=True).create(str(VENV_DIR))
            except Exception as e:
                fail_line(f"Couldn't create the environment: {e}")
                hint = "On Debian/Ubuntu run:  sudo apt install python3-venv" if sys.platform.startswith("linux") else ""
                if hint:
                    out("    " + dim(hint))
                return False
        target = str(vp)
        NEED_REEXEC = True
    cmd = [target, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    if upgrade:
        cmd.append("-U")
    cmd += pkgs
    with Spinner(f"Installing {', '.join(p.split('[')[0] for p in pkgs)}"):
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail_line("Installation failed.")
        tail = (r.stderr or r.stdout).strip().splitlines()[-4:]
        for l in tail:
            out("    " + dim(l))
        return False
    importlib.invalidate_caches()
    return True

def ytdlp_version() -> str | None:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return None

def version_age_days(v: str | None) -> int | None:
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", v or "")
    if not m:
        return None
    try:
        return (date.today() - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return None

def find_ffmpeg() -> str | None:
    if "p" in _FFMPEG:
        return _FFMPEG["p"]
    p = shutil.which("ffmpeg")
    if not p:
        try:
            import imageio_ffmpeg
            p = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            p = None
    _FFMPEG["p"] = p
    return p

def ffmpeg_version(p: str) -> str:
    try:
        r = subprocess.run([p, "-version"], capture_output=True, text=True, timeout=8)
        parts = (r.stdout.splitlines() or [""])[0].split()
        return parts[2] if len(parts) > 2 else "unknown"
    except Exception:
        return "unknown"

def ffmpeg_install_hint() -> str:
    if is_termux():
        return "pkg install ffmpeg"
    if sys.platform == "win32":
        return "winget install Gyan.FFmpeg"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return "Install ffmpeg with your Linux distribution's package manager."

def _runtime_version(executable: str) -> tuple[int, ...] | None:
    """Read a JavaScript runtime's semantic version without assuming a shell."""
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        output = (result.stdout or result.stderr or "").strip()
        match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", output)
        if not match:
            return None
        return tuple(int(part or 0) for part in match.groups())
    except (OSError, subprocess.SubprocessError):
        return None

def local_deno_path() -> Path:
    return HOME_DIR / "bin" / ("deno.exe" if os.name == "nt" else "deno")

def find_js_runtime() -> tuple[str, str, str] | None:
    """Find an installed runtime, including the private Deno managed by yt ani."""
    candidates: list[tuple[str, str, tuple[int, ...] | None]] = []
    local_deno = local_deno_path()
    if local_deno.is_file():
        candidates.append(("deno", str(local_deno), DENO_MINIMUM))
    for runtime_name, commands, minimum in (
        ("deno", ("deno",), DENO_MINIMUM),
        ("node", ("node",), (22, 0, 0)),
        ("quickjs", ("quickjs", "qjs"), None),
    ):
        for command in commands:
            executable = shutil.which(command)
            if executable:
                candidates.append((runtime_name, executable, minimum))
    for runtime_name, executable, minimum in candidates:
        version = _runtime_version(executable)
        if minimum and (version is None or version < minimum):
            continue
        version_text = ".".join(map(str, version)) if version else "version unknown"
        return runtime_name, executable, version_text

    # Bun remains a compatibility fallback only for the narrow versions yt-dlp supports.
    bun = shutil.which("bun")
    if bun:
        version = _runtime_version(bun)
        if version and (1, 2, 11) <= version <= (1, 3, 14):
            return "bun", bun, ".".join(map(str, version)) + " (legacy)"
    return None

def _deno_release_asset() -> str:
    """Return the official Deno release archive name for this platform."""
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    if not arch:
        raise YTError(f"Automatic Deno installation is not supported on {machine or 'this CPU'}.",
                      "Install Deno 2.3+ manually, then launch yt ani again.")
    if sys.platform == "win32":
        target = f"{arch}-pc-windows-msvc"
    elif sys.platform == "darwin":
        target = f"{arch}-apple-darwin"
    elif sys.platform.startswith("linux"):
        target = f"{arch}-unknown-linux-gnu"
    else:
        raise YTError(f"Automatic Deno installation is not supported on {sys.platform}.",
                      "Install Deno 2.3+ manually, then launch yt ani again.")
    return f"deno-{target}.zip"

def install_deno() -> bool:
    """Download and verify the official Deno binary into yt ani's private tools folder."""
    if is_termux():
        pkg = shutil.which("pkg")
        if not pkg:
            return False
        try:
            result = subprocess.run([pkg, "install", "-y", "deno"], check=False)
            return result.returncode == 0 and find_js_runtime() is not None
        except OSError:
            return False

    asset_name = _deno_release_asset()
    bin_dir = local_deno_path().parent
    bin_dir.mkdir(parents=True, exist_ok=True)
    api = "https://api.github.com/repos/denoland/deno/releases/latest"
    headers = {"User-Agent": f"{APP_SLUG}/{APP_VERSION}", "Accept": "application/vnd.github+json"}
    try:
        request = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(request, timeout=25) as response:
            release = json.loads(response.read().decode("utf-8"))
        assets = {item.get("name", ""): item for item in release.get("assets", [])}
        archive_asset = assets.get(asset_name)
        if not archive_asset:
            raise YTError("The official Deno release has no build for this system.")

        expected = ""
        digest = archive_asset.get("digest") or ""
        match = re.search(r"sha256:([0-9a-fA-F]{64})", digest)
        if match:
            expected = match.group(1).lower()
        checksum_asset = assets.get(asset_name + ".sha256sum")
        if not expected and checksum_asset:
            req = urllib.request.Request(checksum_asset["browser_download_url"], headers=headers)
            with urllib.request.urlopen(req, timeout=25) as response:
                checksum_text = response.read(4096).decode("utf-8", "replace")
            match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
            if match:
                expected = match.group(1).lower()
        if not expected:
            raise YTError("Could not verify the Deno download checksum.",
                          "For safety, yt ani will not install an unverified runtime.")

        archive_url = archive_asset["browser_download_url"]
        with tempfile.TemporaryDirectory(prefix="deno-", dir=str(bin_dir)) as work:
            archive_path = Path(work) / asset_name
            req = urllib.request.Request(archive_url, headers=headers)
            with Spinner("Downloading the official Deno runtime"):
                with urllib.request.urlopen(req, timeout=90) as response, archive_path.open("wb") as target:
                    shutil.copyfileobj(response, target)
            actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if actual.lower() != expected:
                raise YTError("The Deno download failed its SHA-256 verification.")
            executable_name = "deno.exe" if os.name == "nt" else "deno"
            with zipfile.ZipFile(archive_path) as archive:
                member = next((name for name in archive.namelist()
                               if Path(name).name.lower() == executable_name), None)
                if not member:
                    raise YTError("The Deno archive did not contain its executable.")
                staged = Path(work) / executable_name
                with archive.open(member) as source, staged.open("wb") as target:
                    shutil.copyfileobj(source, target)
            destination = local_deno_path()
            staged.replace(destination)
            if os.name != "nt":
                destination.chmod(0o755)
        version = _runtime_version(str(local_deno_path()))
        if version is None or version < DENO_MINIMUM:
            local_deno_path().unlink(missing_ok=True)
            raise YTError("The installed Deno version is too old or could not be started.")
        return True
    except YTError:
        raise
    except (OSError, urllib.error.URLError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise YTError("Could not install the required JavaScript runtime (Deno).",
                      f"Check your internet connection and try again. Details: {exc}") from exc

class Check:
    def __init__(self, name, status, detail, required=False, fix=None, fix_label="", hint=""):
        self.name, self.status, self.detail = name, status, detail
        self.required, self.fix, self.fix_label, self.hint = required, fix, fix_label, hint

def has_yt_dlp_ejs() -> bool:
    try:
        from importlib import metadata
        metadata.version("yt-dlp-ejs")
        return True
    except Exception:
        return importlib.util.find_spec("yt_dlp_ejs") is not None

def fix_ytdlp() -> bool:
    return install_packages(["yt-dlp[default]", "yt-dlp-ejs"], upgrade=True)

def fix_ffmpeg() -> bool:
    """Install FFmpeg, using Termux packages on Android and a bundled binary elsewhere."""
    if is_termux():
        pkg = shutil.which("pkg")
        if not pkg:
            return False
        try:
            result = subprocess.run([pkg, "install", "-y", "ffmpeg"], check=False)
            _FFMPEG.clear()
            return result.returncode == 0 and bool(find_ffmpeg())
        except OSError:
            return False
    ok = install_packages(["imageio-ffmpeg"])
    _FFMPEG.clear()
    return ok

def has_term_image() -> bool:
    """Return whether term-image is importable in the active Python environment."""
    try:
        return importlib.util.find_spec("term_image") is not None
    except (ImportError, ValueError):
        return False

def collect_checks(outdir: Path, network: bool = True) -> list[Check]:
    checks: list[Check] = []
    v = sys.version_info
    if v < (3, 11):
        checks.append(Check("Python", "fail", f"{v.major}.{v.minor} - needs 3.11 or newer", True,
                            None, "", "Install Python 3.11+ and run this tool with that interpreter."))
    else:
        checks.append(Check("Python", "ok", f"{v.major}.{v.minor}.{v.micro}"))

    yv = ytdlp_version()
    if not yv:
        checks.append(Check("yt-dlp", "fail", "not installed", True, fix_ytdlp, "Install yt-dlp"))
    else:
        age = version_age_days(yv)
        if age is not None and age > 30:
            checks.append(Check("yt-dlp", "warn", f"{yv} - {age} days old, YouTube changes often",
                                False, fix_ytdlp, "Update yt-dlp"))
        else:
            checks.append(Check("yt-dlp", "ok", f"{yv}" + (" (up to date)" if age is not None else "")))
        if not has_yt_dlp_ejs():
            checks.append(Check("yt-dlp scripts", "warn", "yt-dlp-ejs missing - full YouTube support needs it",
                                False, fix_ytdlp, "Install yt-dlp-ejs"))

    ff = find_ffmpeg()
    if ff:
        checks.append(Check("FFmpeg", "ok", f"{ffmpeg_version(ff)}" + (" (bundled)" if "imageio" in ff else "")))
    else:
        checks.append(Check("FFmpeg", "fail", "not found - needed to merge HD video, convert and trim",
                            True, fix_ffmpeg, "Install FFmpeg", ffmpeg_install_hint()))
    if not shutil.which("ffprobe"):
        checks.append(Check("ffprobe", "warn", "not found - optional, slightly better audio conversion"))
    if has_term_image():
        checks.append(Check("term-image", "ok", "native image protocols / colour fallback"))
    else:
        checks.append(Check("term-image", "fail", "not installed - required for the anime preview",
                            True, lambda: install_packages(["term-image>=0.7,<0.8"]), "Install term-image"))

    runtime = find_js_runtime()
    if runtime:
        checks.append(Check("JS runtime", "ok", f"{runtime[0]} {runtime[2]}"))
    else:
        checks.append(Check("JS runtime", "fail", "no supported runtime found", True, install_deno,
                            "Install Deno", "yt ani can download and configure Deno automatically."))

    try:
        outdir.mkdir(parents=True, exist_ok=True)
        probe = outdir / f".{APP_NAME}-write-test"
        probe.write_text("ok")
        probe.unlink()
        free = shutil.disk_usage(outdir).free
        st = "warn" if free < 2 * 1024 ** 3 else "ok"
        checks.append(Check("Output folder", st, f"{outdir}  ({fmt_size(free)} free)"))
    except Exception as e:
        checks.append(Check("Output folder", "fail", f"{outdir} is not writable ({e})", True))

    if network:
        try:
            socket.create_connection(("www.youtube.com", 443), timeout=4).close()
            checks.append(Check("Network", "ok", "youtube.com reachable"))
        except Exception:
            checks.append(Check("Network", "warn", "can't reach youtube.com - check your connection"))
    return checks

def render_checks(checks: list[Check]) -> None:
    lines = []
    for c in checks:
        mark = {"ok": good(G["ok"]), "warn": warn_c(G["warn"]), "fail": bad(G["fail"])}[c.status]
        lines.append(f"{mark} {pad(bold(c.name), 16)} {c.detail}")
        if c.status != "ok" and c.hint:
            lines.append(f"   {dim(c.hint)}")
    panel(lines, "Environment check")

def cmd_doctor(args, ctx) -> int:
    checks = collect_checks(ctx.outdir)
    render_checks(checks)
    fixes, seen = [], set()
    for c in checks:
        if c.fix and c.status != "ok" and c.fix not in seen:
            seen.add(c.fix)
            fixes.append(c)
    ran = False
    for c in fixes:
        if args.fix or confirm(f"{c.fix_label}?"):
            ran = c.fix() or ran
    if ran:
        if NEED_REEXEC:
            info_line("Switching to the isolated environment...")
            reexec_in_venv()
        out()
        checks = collect_checks(ctx.outdir)
        render_checks(checks)
    return 2 if any(c.status == "fail" and c.required for c in checks) else 0

def ensure_ready(ctx, need_ffmpeg: bool = True, need_image: bool = False) -> None:
    """Install every missing runtime/package automatically before showing the TUI."""
    global NEED_REEXEC
    if sys.version_info < (3, 11):
        raise YTError("Python 3.11 or newer is required.",
                      "Python itself cannot be upgraded safely by yt ani. Install Python 3.11+ once, then restart.")

    packages: list[str] = []
    # When bootstrapping a new PEP 668 virtual environment, system-installed
    # packages are not visible inside it, so seed the venv with the full stack.
    fresh_managed_venv = (not in_venv() and externally_managed() and not venv_python().exists())
    if fresh_managed_venv or not ytdlp_version():
        packages.append("yt-dlp[default]")
    if fresh_managed_venv or not has_yt_dlp_ejs():
        packages.append("yt-dlp-ejs")
    if need_image and (fresh_managed_venv or not has_term_image()):
        packages.append("term-image>=0.7,<0.8")
    if need_ffmpeg and not is_termux() and (fresh_managed_venv or not find_ffmpeg()):
        packages.append("imageio-ffmpeg")

    if packages:
        if not install_packages(packages, upgrade=False):
            raise YTError("Automatic dependency installation failed.",
                          "Check your internet connection and Python package permissions, then run: "
                          f"python {APP_SLUG}.py doctor --fix")
        if NEED_REEXEC:
            reexec_in_venv()
        importlib.invalidate_caches()
        _FFMPEG.clear()

    if need_ffmpeg and not find_ffmpeg():
        if is_termux():
            if not fix_ffmpeg():
                raise YTError("FFmpeg could not be installed automatically.",
                              "On Termux, check the package repositories and run: pkg install ffmpeg")
        else:
            raise YTError("FFmpeg is still unavailable after automatic setup.",
                          "Run the doctor command to inspect the environment.")

    if not find_js_runtime():
        if not install_deno() or not find_js_runtime():
            raise YTError("The required JavaScript runtime could not be installed.",
                          "yt ani needs Deno 2.3+ (recommended) or another supported runtime. "
                          "Check your connection and run doctor --fix.")

    if need_image and not has_term_image():
        raise YTError("term-image could not be installed, so the anime preview is unavailable.",
                      "Check your internet connection and Python package permissions, then run doctor --fix.")

    try:
        ctx.outdir.mkdir(parents=True, exist_ok=True)
        if not os.access(ctx.outdir, os.W_OK):
            raise OSError("folder is not writable")
    except OSError as exc:
        raise YTError(f"The download folder is not ready: {ctx.outdir}", str(exc)) from exc

    age = version_age_days(ytdlp_version())
    if age is not None and age > 30 and not os.environ.get("YT_QUIET"):
        warn_line(f"yt-dlp is {age} days old - run {bold(APP_SLUG + ' update')} if anything fails.")

def cmd_update(args, ctx) -> int:
    before = ytdlp_version()
    if not install_packages(["yt-dlp[default]", "yt-dlp-ejs"], upgrade=True):
        return 1
    if NEED_REEXEC:
        info_line("Updated inside the isolated environment.")
        return 0
    importlib.invalidate_caches()
    for m in [k for k in sys.modules if k == "yt_dlp" or k.startswith("yt_dlp.")]:
        del sys.modules[m]
    after = ytdlp_version()
    if before == after:
        out(f"  {good(G['ok'])} yt-dlp {after} is already the latest.")
    else:
        out(f"  {good(G['ok'])} yt-dlp {before or 'none'} {G['mid']} {bold(str(after))}")
    return 0
