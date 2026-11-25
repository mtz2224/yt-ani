# yt ani — Project Guide

This guide explains what is in the source tree, how modules communicate, and where to edit common settings.

## Folder map

```text
yt-ani-project/
├── yt-ani.py                  # Small launcher for the application
├── README.md                  # Quick start, user features and commands
├── GUIDE.md                   # This architecture and maintenance guide
├── requirements.txt           # Python runtime requirements
├── pyproject.toml             # Package metadata and console entry point
├── MANIFEST.in                # Include bundled image in source distributions
├── tests/
│   ├── test_core.py           # URL, time, captions and stream tests
│   └── test_ui.py             # Responsive layout and image placement tests
└── yt_ani/
    ├── __init__.py            # Package identity and version exports
    ├── __main__.py            # Enables: python -m yt_ani
    ├── config.py              # Branding, paths, defaults, support and website
    ├── errors.py              # Quit and YTError exception types
    ├── terminal.py            # ANSI styling, panels, keyboard, input and spinner
    ├── utils.py               # Size, time, count and filename helpers
    ├── dependencies.py        # yt-dlp, FFmpeg, Deno, venv and setup/doctor logic
    ├── youtube.py             # YouTube URL validation and format discovery
    ├── captions.py            # VTT parsing, cleanup and format conversion
    ├── downloads.py           # Download plans, progress UI and file execution
    ├── workflows.py           # Interactive menus and the download loop
    ├── screens.py             # Dashboard, Details, video and result screens
    ├── ui/
    │   ├── __init__.py        # UI subpackage marker
    │   └── image.py           # Uncropped image renderer, left-aligned
    └── assets/
        ├── __init__.py        # Package-data marker
        └── anime.png          # Original bundled character artwork
```

## Responsibilities

### `config.py`

The single source of truth for the project name, version, palette, default output folder, website placeholder, donation recipient, asset path and private Deno/venv paths. Change shared brand values here.

### `terminal.py`

Provides terminal primitives: ANSI colors, UTF-8 sizing, safe clipping, panels, cursor positioning, arrow-key menus, prompts, clear-screen behavior, and the progress spinner. It does not contain YouTube logic.

### `ui/image.py` and `assets/anime.png`

`assets/anime.png` is the original supplied image, stored unchanged. `draw_avatar()` loads it with `term-image`, scales only its on-screen size while preserving its aspect ratio, and draws it from the current cursor position with left alignment. It does not crop or re-save the PNG.

`term-image` chooses a native graphics renderer when the terminal supports Kitty or iTerm2 image protocols. On terminals without such a protocol, it uses a full-colour Unicode half-block representation. Pixel-identical bitmap display is not technically possible in a plain text-only terminal; use a Kitty or iTerm2-compatible terminal for the native image.

### `screens.py`

Owns dashboard composition and other screens. `dashboard_geometry()` chooses between two layouts:

- **Wide terminal:** image on the left at approximately half the terminal width; dashboard text in a separate right column.
- **Narrow terminal:** image remains left-aligned at the top; compact information moves beneath it.

The project details page shows features, controls, save directory, Vodafone Cash and the unpublished website state. The dashboard's Clear option repaints the same screen.

To change image size or placement, edit `dashboard_geometry()` in `screens.py`. To alter rendering behavior, edit `draw_avatar()` in `ui/image.py`.

### `dependencies.py`

Checks and installs `yt-dlp[default]`, `yt-dlp-ejs`, `term-image`, and the bundled FFmpeg fallback before the interactive dashboard appears. It installs Deno when no supported JavaScript runtime exists. On externally managed Python distributions, it creates an isolated venv under `~/.yt-ani/venv`. It also implements the `doctor` and `update` commands.

### `youtube.py`

Validates links, constructs the yt-dlp options, analyzes videos and builds available video/audio stream rows. It does not draw the UI or perform the actual download.

### `captions.py`

Contains the WebVTT parser, overlap cleanup and SRT/VTT/TXT conversion helpers. It does not perform network requests.

### `downloads.py`

Contains the `Plan` model, disk-space preflight, progress hooks, yt-dlp execution and caption file placement. Output is grouped under `video/`, `audio/` and `captions/` inside the configured output root.

### `workflows.py`

Owns the interactive journey after a YouTube URL is entered: choose video/audio/captions, select quality or language, select trimming, open project details, clear/redraw the screen, and start the download.

### `cli.py`

Defines the argument parser, direct-download plan builder, donation screen and top-level command router. The CLI routes to lower-level modules; lower-level modules must not import `cli.py`.

## Startup and control flow

1. `yt-ani.py` calls `yt_ani.cli.main()`.
2. `cli.main()` handles the managed virtual environment and parses arguments.
3. Interactive mode creates `Ctx` then calls `ensure_ready()`.
4. `ensure_ready()` installs missing Python packages, FFmpeg fallback and Deno before the user is asked for a link.
5. `screens.welcome_panel()` computes terminal geometry and draws the original image on the left with text on the right (or text below on narrow screens).
6. `workflows.interactive()` reads the URL and calls `youtube.analyze()`.
7. `workflows.choose_plan()` presents download choices and the project Details/Clear options.
8. `downloads.execute()` runs the selected download and writes the result into the selected category folder.

## Common edits

### Change the official website

Edit `WEBSITE_URL` in `yt_ani/config.py`. Leave it as an empty string until the real official URL is published.

### Change the donation recipient

Edit the `DONATE_METHODS` tuple in `yt_ani/config.py`. The Project Details page and donation screen read the same shared value.

### Change the default save directory

Set `YT_ANI_DIR` in the environment or change `DEFAULT_OUTPUT_DIR` in `yt_ani/config.py`. `-o DIR` overrides the path for one run.

### Replace the character image

Replace `yt_ani/assets/anime.png` with another PNG/JPEG while preserving the filename. For packaging, `pyproject.toml` and `MANIFEST.in` already include package assets.

### Change the color palette

Edit `BRAND_ACCENT` and `BRAND_ACCENT_2` in `yt_ani/config.py`.

## Install / package

```bash
python -m pip install -e .
```

Or use directly from the source directory:

```bash
python yt-ani.py
```

## Test and verify

```bash
python -m compileall -q yt_ani yt-ani.py
python -m unittest discover -s tests -v
python yt-ani.py --version
python yt-ani.py --help
```

The UI tests mock the terminal image renderer to verify placement and alignment. They do not claim to prove that the current terminal emulator supports native bitmap graphics. That depends on the terminal's image protocol support.
