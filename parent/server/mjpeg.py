# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""MJPEG パススルー配信の部品（デコードしない。CLAUDE.md §9）。aiohttp に依存しない。"""
from __future__ import annotations

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_FRAME = 8 * 1024 * 1024


class JpegSplitter:
    """連結された JPEG のバイト列をフレームごとに切り出す。

    JPEG の本体中の 0xFF はバイトスタッフィングされるので、EOI が現れるのはフレーム末尾か
    埋め込みサムネイルの末尾だけ。次が SOI かデータの終わりならフレームの区切りとみなす
    （データの終わりで切ることで、次のフレームを待つ遅延を入れない）。
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0  # ここより前に EOI は無い

    def feed(self, data: bytes) -> list[bytes]:
        buf = self._buf
        buf += data
        frames: list[bytes] = []
        while True:
            start = buf.find(SOI)
            if start < 0:
                # 次のチャンクと合わせて SOI になる可能性がある 0xFF だけ残す
                del buf[:-1 if buf.endswith(b"\xff") else len(buf)]
                self._pos = 0
                return frames
            if start > 0:
                del buf[:start]
                self._pos = 0
            end = buf.find(EOI, max(self._pos, 2))
            if end < 0:
                if len(buf) > MAX_FRAME:
                    buf.clear()
                self._pos = max(len(buf) - 1, 0)
                return frames
            stop = end + 2
            following = bytes(buf[stop:stop + 2])
            if following == b"\xff":  # 次のチャンクを見ないと判断できない
                self._pos = end
                return frames
            if following and following != SOI:  # 埋め込みサムネイルの EOI
                self._pos = stop
                continue
            frames.append(bytes(buf[:stop]))
            del buf[:stop]
            self._pos = 0


class Throttle:
    """カメラのフレームを間引いて目標 fps に落とす。"""

    # カメラのフレーム間隔の揺れで、1枚ずつ余分に落とさないための余裕（秒）
    MARGIN = 0.01

    def __init__(self, fps: float) -> None:
        self.period = 1.0 / fps
        self._next = 0.0

    def allow(self, now: float) -> bool:
        if now < self._next - self.MARGIN:
            return False
        self._next += self.period
        if self._next < now:  # 間が空いたあと、遅れを取り戻そうとして連続で通さない
            self._next = now + self.period
        return True
