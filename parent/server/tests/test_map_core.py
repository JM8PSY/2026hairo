# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""地図・スキャンの変換、保存、負荷の読み取りの単体テスト。"""
import base64
import math
import tempfile
import unittest
from pathlib import Path

from map_core import SystemStats, encode_map, encode_ranges, quaternion_yaw, write_map_files

MAP = {"seq": 3, "w": 2, "h": 2, "res": 0.05, "ox": -1.0, "oy": 2.0, "cells": bytes([255, 0, 100, 40])}


class ConvertTest(unittest.TestCase):
    def test_yaw(self):
        self.assertAlmostEqual(quaternion_yaw(0, 0, 0, 1), 0.0)
        self.assertAlmostEqual(quaternion_yaw(0, 0, math.sin(0.5), math.cos(0.5)), 1.0)

    def test_encode_map(self):
        m = encode_map(MAP)
        self.assertEqual((m["t"], m["w"], m["ox"]), ("map", 2, -1.0))
        self.assertEqual(base64.b64decode(m["cells"]), MAP["cells"])

    def test_ranges(self):
        r = encode_ranges([0.0, 1.234, float("inf"), float("nan"), 20.0, 0.05], 0.1, 12.0)
        self.assertEqual(r, [0, 123, 0, 0, 0, 0])


class SaveTest(unittest.TestCase):
    def test_pgm_and_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            yaml = write_map_files(Path(d) / "maps", "m", MAP)
            self.assertIn("image: m.pgm", yaml.read_text())
            self.assertIn("origin: [-1.0, 2.0, 0.0]", yaml.read_text())
            pgm = (Path(d) / "maps" / "m.pgm").read_bytes()
        # 上の行（占有格子の y=1）が先：占有 100 → 黒、空き 40 → 白。次に 不明、空き
        self.assertEqual(pgm, b"P5\n2 2\n255\n" + bytes([0, 254, 205, 254]))


class StatsTest(unittest.TestCase):
    def make_root(self, d):
        root = Path(d)
        for i, value in enumerate(["49062\n", "51000\n", None]):
            zone = root / f"sys/class/thermal/thermal_zone{i}"
            zone.mkdir(parents=True)
            if value:
                (zone / "temp").write_text(value)
        (root / "proc").mkdir()
        (root / "proc/meminfo").write_text("MemTotal: 1000 kB\nMemFree: 1 kB\nMemAvailable: 250 kB\n")
        return root

    def test_reads_values(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d)
            s = SystemStats(root)
            self.assertEqual(s.temp_c(), 51.0)
            self.assertEqual(s.mem_pct(), 75.0)
            (root / "proc/stat").write_text("cpu 100 0 0 100 0 0 0 0 0 0\n")
            self.assertIsNone(s.cpu_pct())  # 差分なので1回目は出せない
            (root / "proc/stat").write_text("cpu 175 0 0 125 0 0 0 0 0 0\n")
            self.assertEqual(s.cpu_pct(), 75.0)

    def test_missing_files_give_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(SystemStats(Path(d)).snapshot(), {"temp_c": None, "cpu_pct": None, "mem_pct": None})
