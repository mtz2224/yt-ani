"""Brand identity, app paths, and user defaults."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "yt ani"
APP_SLUG = "yt-ani"
APP_VERSION = "3.1.0"
APP_TAGLINE = "A softer, simpler way to save videos."
WEBSITE_URL = ""  # Intentionally blank until the official website is published.

BRAND_ACCENT = (177, 145, 202)
BRAND_ACCENT_2 = (224, 174, 207)

DONATE_TITLE = "Support yt ani."
DONATE_INTRO = ("Your contribution helps with maintenance and future improvements. "
                "Every contribution is optional.")
DONATE_METHODS = (
    {"key": "vodafone", "name": "Vodafone Cash", "kind": "Mobile wallet", "number": "01009610342"},
)
DONATE_NOTE = ("Double-check the recipient details in your payment app before confirming a "
               "transfer. Donations are voluntary and do not unlock extra features.")

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
ASSETS_DIR = PACKAGE_DIR / "assets"
AVATAR_FILE = ASSETS_DIR / "anime.png"
ENTRY_SCRIPT = PROJECT_ROOT / "yt-ani.py"


def is_termux() -> bool:
    return bool(os.environ.get("TERMUX_VERSION")) or "com.termux" in str(Path(sys.prefix)).lower()


def default_downloads_dir() -> Path:
    home = Path.home()
    if is_termux():
        shared_downloads = home / "storage" / "downloads"
        if shared_downloads.exists():
            return shared_downloads
    return home / "Downloads"


DEFAULT_PARENT_DIR = default_downloads_dir()
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("YT_ANI_DIR") or os.environ.get("YT_DIR") or (DEFAULT_PARENT_DIR / APP_SLUG)
).expanduser()
HOME_DIR = Path.home() / f".{APP_SLUG}"
VENV_DIR = HOME_DIR / "venv"
DENO_DIR = HOME_DIR / "bin"
YT_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
