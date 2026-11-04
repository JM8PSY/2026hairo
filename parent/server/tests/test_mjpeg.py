# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""MJPEG の切り出しと間引きの単体テスト。"""
import unittest

from mjpeg import JpegSplitter, Throttle


def jpeg(body: bytes) -> bytes:
    return b"\xff\xd8" + body + b"\xff\xd9"


class SplitterTest(unittest.TestCase):
    def test_frame_is_emitted_without_waiting_for_next(self):
        self.assertEqual(JpegSplitter().feed(jpeg(b"a")), [jpeg(b"a")])

    def test_concatenated_frames(self):
        self.assertEqual(JpegSplitter().feed(jpeg(b"a") + jpeg(b"b")), [jpeg(b"a"), jpeg(b"b")])

    def test_every_chunk_boundary(self):
        data = jpeg(b"abc\xff\x00d") + jpeg(b"e") + jpeg(b"\xff\x00")
        for cut in range(1, len(data)):
            s = JpegSplitter()
            self.assertEqual(s.feed(data[:cut]) + s.feed(data[cut:]),
                             [jpeg(b"abc\xff\x00d"), jpeg(b"e"), jpeg(b"\xff\x00")], cut)

    def test_byte_by_byte(self):
        s = JpegSplitter()
        out = []
        for b in jpeg(b"xy") + jpeg(b"z"):
            out += s.feed(bytes([b]))
        self.assertEqual(out, [jpeg(b"xy"), jpeg(b"z")])

    def test_leading_garbage_dropped(self):
        self.assertEqual(JpegSplitter().feed(b"junk\x00\xff" + jpeg(b"a")), [jpeg(b"a")])

    def test_embedded_thumbnail_is_not_a_boundary(self):
        frame = jpeg(b"head" + jpeg(b"thumb") + b"tail")
        self.assertEqual(JpegSplitter().feed(frame), [frame])

    def test_oversized_frame_is_discarded_and_recovers(self):
        s = JpegSplitter()
        self.assertEqual(s.feed(b"\xff\xd8" + bytes(9 * 1024 * 1024)), [])
        self.assertEqual(s.feed(jpeg(b"a")), [jpeg(b"a")])


class ThrottleTest(unittest.TestCase):
    def count(self, fps, camera_fps=29.0, seconds=10):
        t = Throttle(fps)
        return sum(t.allow(100.0 + i / camera_fps) for i in range(int(camera_fps * seconds)))

    def test_rates(self):
        for fps in (5, 10, 15):
            self.assertAlmostEqual(self.count(fps) / 10, fps, delta=fps * 0.2, msg=fps)

    def test_at_or_above_camera_rate_passes_all(self):
        self.assertEqual(self.count(30), 290)

    def test_no_burst_after_a_gap(self):
        t = Throttle(10)
        self.assertTrue(t.allow(100.0))
        self.assertTrue(t.allow(200.0))
        self.assertFalse(t.allow(200.03))
