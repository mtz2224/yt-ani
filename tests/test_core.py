from __future__ import annotations

import unittest
from yt_ani.errors import YTError
from yt_ani.utils import parse_time, fmt_time
from yt_ani.youtube import validate_url, build_video_rows, build_audio_rows
from yt_ani.captions import parse_vtt, convert_vtt


class CoreTests(unittest.TestCase):
    def test_validate_short_url(self):
        url, video_id = validate_url("https://youtu.be/abcdefghijk")
        self.assertEqual(video_id, "abcdefghijk")
        self.assertEqual(url, "https://www.youtube.com/watch?v=abcdefghijk")

    def test_reject_non_youtube_url(self):
        with self.assertRaises(YTError):
            validate_url("https://example.com/video")

    def test_parse_time_variants(self):
        self.assertEqual(parse_time("90"), 90.0)
        self.assertEqual(parse_time("1:30"), 90.0)
        self.assertEqual(parse_time("1:02:03"), 3723.0)
        self.assertEqual(fmt_time(3723), "1:02:03")

    def test_vtt_parse_and_srt_conversion(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello world\n"
        cues = parse_vtt(raw)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "Hello world")
        self.assertIn("00:00:01,000 --> 00:00:02,000", convert_vtt(raw, "srt"))

    def test_video_rows(self):
        info = {"duration": 10, "formats": [
            {"format_id": "18", "height": 360, "vcodec": "avc1", "acodec": "mp4a", "ext": "mp4", "filesize": 1000},
            {"format_id": "137", "height": 1080, "vcodec": "avc1", "acodec": "none", "ext": "mp4", "filesize": 3000},
            {"format_id": "140", "acodec": "mp4a", "vcodec": "none", "abr": 128, "ext": "m4a", "filesize": 500},
        ]}
        rows = build_video_rows(info)
        self.assertEqual(rows[0]["label"], "1080p")
        self.assertGreaterEqual(len(build_audio_rows(info)), 1)


if __name__ == "__main__":
    unittest.main()
