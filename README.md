# yt ani

**yt ani** is an anime-inspired YouTube download studio for the terminal. The application is split into small Python modules so that the terminal UI, image display, download logic, and setup routines can be maintained separately.

## Features

- Video downloads with resolution, FPS, codec, audio and MP4 / WEBM / MKV choices.
- Audio downloads as the original stream, MP3 or M4A with bitrate selection.
- Manual, automatic and translated captions in SRT, VTT or TXT.
- Trim a selected time range; optional precise cuts use FFmpeg.
- Automatic first-run setup for yt-dlp, yt-dlp-ejs, FFmpeg fallback, Deno and the terminal image renderer.
- Default output folder: `~/Downloads/yt-ani` (or Android shared Downloads in Termux).
- Responsive dashboard: the original anime artwork is shown large and left-aligned, with project details on the right on wide terminals.
- Project Details, Vodafone Cash support information, and a Clear / redraw option.

## Requirements

- Python 3.11 or newer.
- Internet access on first launch so yt ani can install missing packages and the Deno runtime.
- A terminal with Unicode support. For a true, unconverted image display, use a terminal that supports the Kitty or iTerm2 graphics protocol. `term-image` detects supported graphics protocols automatically; on other terminals it uses a large full-colour half-block approximation. A plain text terminal cannot reproduce a PNG pixel-for-pixel without a graphics protocol.

## Run from the source folder

```bash
python yt-ani.py
```

Package entry point:

```bash
python -m yt_ani
```

On first launch the application checks its Python dependencies and download runtime before displaying the dashboard. If the system Python is externally managed (PEP 668), packages are installed in an isolated environment under `~/.yt-ani/venv`.

## CLI examples

```bash
# Interactive mode
python yt-ani.py

# Start with a YouTube URL
python yt-ani.py https://youtu.be/VIDEO_ID

# Download recommended video quality
python yt-ani.py https://youtu.be/VIDEO_ID -q recommended

# Audio conversion
python yt-ani.py https://youtu.be/VIDEO_ID -t audio --audio-format mp3 --bitrate 192

# Captions
python yt-ani.py https://youtu.be/VIDEO_ID -t captions --lang en --sub-format srt

# Trim a section
python yt-ani.py https://youtu.be/VIDEO_ID --start 1:30 --end 2:45

# Inspect formats, diagnose setup, or update yt-dlp
python yt-ani.py info https://youtu.be/VIDEO_ID
python yt-ani.py doctor
python yt-ani.py update
```

## Save location

The default is `~/Downloads/yt-ani`. Change it for one run with `-o DIR`, or set it persistently with `YT_ANI_DIR`:

```bash
python yt-ani.py -o ~/Videos/yt-ani
export YT_ANI_DIR="$HOME/Videos/yt-ani"
```

## Image display and layout

The original character PNG is bundled unchanged at `yt_ani/assets/anime.png`. The dashboard gives it roughly half the terminal width and pins it to the **left edge**; the project summary is placed beside it. On narrow windows the image stays left-aligned and the text moves below it. The UI never crops or overwrites the source asset; it only scales the on-screen rendering while preserving its aspect ratio.

`term-image` automatically selects its best render style. When the terminal supports Kitty or iTerm2 inline graphics, it displays the source as a native image. On terminals without a graphics protocol, it falls back to full-colour Unicode half-blocks. This fallback can look like terminal artwork, but it cannot be pixel-identical to the original image. For the closest-to-original display, run yt ani inside a Kitty or iTerm2-compatible terminal.

## Donation and website

- Vodafone Cash: **01009610342**
- Official website: not published yet; `WEBSITE_URL` in `yt_ani/config.py` is intentionally blank.

Donations are optional and do not unlock features. Verify the recipient details inside Vodafone Cash before transferring.

## Project structure

See [GUIDE.md](GUIDE.md) for the purpose of every folder and module, the startup sequence, image-rendering behavior, and customization instructions.

## Usage note

Only download content you have the right to save. Network, disk and platform restrictions still apply.
