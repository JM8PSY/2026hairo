# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""ゲートウェイの ROS に依存しない部分：地図・スキャンの変換、保存、Jetson の負荷の読み取り。"""
from __future__ import annotations

import base64
import math
from pathlib import Path


def quaternion_yaw(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def encode_map(m: dict) -> dict:
    """占有格子をブラウザへ送る形にする。cells は 1マス1バイト（-1 = 255 = 不明、0〜100 = 占有度）。"""
    return {"t": "map", "seq": m["seq"], "w": m["w"], "h": m["h"], "res": m["res"],
            "ox": m["ox"], "oy": m["oy"], "cells": base64.b64encode(m["cells"]).decode("ascii")}


def encode_ranges(ranges, range_min: float, range_max: float) -> list[int]:
    """距離をセンチメートルの整数にする（0 = 無効）。"""
    return [round(r * 100) if math.isfinite(r) and range_min <= r <= range_max else 0 for r in ranges]


def write_map_files(directory: Path, stem: str, m: dict) -> Path:
    """地図を PGM と YAML（nav2 map_server の形式）で保存し、YAML のパスを返す。"""
    directory.mkdir(parents=True, exist_ok=True)
    w, h, cells = m["w"], m["h"], m["cells"]
    pgm = directory / f"{stem}.pgm"
    with open(pgm, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        # PGM は上の行から、占有格子は下の行から並ぶ
        for y in range(h - 1, -1, -1):
            f.write(bytes(205 if c == 255 else (0 if c > 50 else 254) for c in cells[y * w:(y + 1) * w]))
    yaml = directory / f"{stem}.yaml"
    yaml.write_text(
        f"image: {pgm.name}\nmode: trinary\nresolution: {m['res']}\n"
        f"origin: [{m['ox']}, {m['oy']}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n",
        encoding="utf-8")
    return yaml


class SystemStats:
    """Jetson の温度・負荷。読めない環境（Mac など）では None を返す。"""

    def __init__(self, root: Path = Path("/")) -> None:
        self.root = root
        self._prev: tuple[int, int] | None = None

    def _read(self, relative: str) -> str | None:
        try:
            return (self.root / relative).read_text()
        except OSError:
            return None

    def temp_c(self) -> float | None:
        best = None
        for zone in sorted((self.root / "sys/class/thermal").glob("thermal_zone*")):
            try:
                value = int((zone / "temp").read_text()) / 1000.0
            except (OSError, ValueError):  # 無効なゾーンは読むとエラーになる
                continue
            best = value if best is None else max(best, value)
        return best

    def cpu_pct(self) -> float | None:
        text = self._read("proc/stat")
        if text is None:
            return None
        fields = [int(v) for v in text.splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields[:8])
        prev, self._prev = self._prev, (idle, total)
        if prev is None or total == prev[1]:
            return None
        return 100.0 * (1.0 - (idle - prev[0]) / (total - prev[1]))

    def mem_pct(self) -> float | None:
        text = self._read("proc/meminfo")
        if text is None:
            return None
        info = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in text.splitlines())}
        return 100.0 * (1.0 - info["MemAvailable"] / info["MemTotal"])

    def snapshot(self) -> dict:
        return {"temp_c": self.temp_c(), "cpu_pct": self.cpu_pct(), "mem_pct": self.mem_pct()}
