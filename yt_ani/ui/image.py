"""Render the bundled artwork as a real terminal image when supported.

The source asset is never cropped or rewritten. term-image selects Kitty/iTerm2
graphics output when the terminal supports it and a coloured half-block fallback
otherwise. The fallback is intentionally rendered at a large, readable size.
"""
from __future__ import annotations

from ..config import AVATAR_FILE


def draw_avatar(width: int, max_height: int) -> tuple[int, int, str]:
    """Draw the original PNG at the current cursor, left-aligned and uncropped.

    ``width`` is measured in terminal columns. Only the on-screen render size is
    scaled; the image file in ``assets/`` remains byte-for-byte unchanged.
    Returns (columns, rows, renderer class name).
    """
    if not AVATAR_FILE.is_file():
        raise FileNotFoundError(f"Bundled artwork is missing: {AVATAR_FILE}")

    from term_image.image import from_file

    image = from_file(AVATAR_FILE, width=max(16, int(width)))
    try:
        # Width-only sizing preserves the PNG's aspect ratio. If the calculated
        # height is too large for this terminal, constrain height proportionally.
        rendered_width, rendered_height = image.rendered_size
        if rendered_height > max_height:
            image.height = max(6, int(max_height))
            rendered_width, rendered_height = image.rendered_size

        # No padding is added, so the image starts at the current cursor column.
        # term-image uses native terminal graphics where available. In a plain
        # terminal it uses its own high-colour half-block renderer.
        image.draw(
            h_align="left",
            pad_width=rendered_width,
            v_align="top",
            pad_height=rendered_height,
            alpha=None,
            animate=False,
            check_size=True,
        )
        return rendered_width, rendered_height, type(image).__name__
    finally:
        close = getattr(image, "close", None)
        if callable(close):
            close()
