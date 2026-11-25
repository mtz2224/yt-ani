from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yt_ani.screens import dashboard_geometry, welcome_panel
from yt_ani.ui.image import draw_avatar


class FakeImage:
    def __init__(self, path, width):
        self.path = Path(path)
        self.width = width
        self.height = (width + 1) // 2
        self.draw_options = None
        self.closed = False

    @property
    def rendered_size(self):
        return self.width, self.height

    def draw(self, **kwargs):
        self.draw_options = kwargs

    def close(self):
        self.closed = True


class ImageAndLayoutTests(unittest.TestCase):
    def test_wide_dashboard_uses_large_left_image(self):
        layout = dashboard_geometry(80, 24)
        self.assertEqual(layout["mode"], "side")
        self.assertGreaterEqual(layout["image_width"], 40)
        self.assertEqual(layout["text_col"], layout["image_width"] + 4)

    def test_narrow_dashboard_stacks_image_and_text(self):
        layout = dashboard_geometry(60, 24)
        self.assertEqual(layout["mode"], "stack")
        self.assertGreaterEqual(layout["image_width"], 20)
        self.assertEqual(layout["text_col"], 1)

    def test_draw_avatar_uses_original_uncropped_and_left_aligned(self):
        instance = FakeImage("unused", 40)
        def fake_from_file(path, width):
            self.assertTrue(Path(path).is_file())
            self.assertEqual(width, 40)
            instance.path = Path(path)
            return instance

        package = types.ModuleType("term_image")
        package.__path__ = []
        image_module = types.ModuleType("term_image.image")
        image_module.from_file = fake_from_file
        with patch.dict(sys.modules, {"term_image": package, "term_image.image": image_module}):
            width, height, renderer = draw_avatar(40, 20)

        self.assertEqual((width, height), (40, 20))
        self.assertEqual(renderer, "FakeImage")
        self.assertEqual(instance.draw_options["h_align"], "left")
        self.assertEqual(instance.draw_options["v_align"], "top")
        self.assertIsNone(instance.draw_options["alpha"])
        self.assertTrue(instance.closed)

    def test_welcome_screen_places_text_to_right_of_image(self):
        writes = []
        ctx = SimpleNamespace(outdir=Path("/home/test/Downloads/yt-ani"))
        with patch("yt_ani.screens.term_size", return_value=(80, 24)), \
             patch("yt_ani.screens.clear_screen"), \
             patch("yt_ani.screens.draw_avatar", return_value=(41, 21, "KittyImage")) as draw, \
             patch("yt_ani.screens.write", side_effect=writes.append):
            welcome_panel(ctx)

        draw.assert_called_once_with(41, 21)
        self.assertIn("\x1b[1;45H", writes)


if __name__ == "__main__":
    unittest.main()
