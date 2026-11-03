# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""親機側：子機へ DRIVE を約50Hzで送り続け、子機の STATUS からリンク品質を測る。

ソケットの送受信は呼び出し側のループ（または run_forever）から step() / on_packet() を呼ぶ。
操作対象でないときも stop() で全0を送り続けること（CLAUDE.md §6）。
"""
from __future__ import annotations

import os
import socket
import time
from collections import deque

from . import proto as cp

STATUS_TIMEOUT_S = 0.5


class ChildClient:
    def __init__(self, n_motors: int, rate_hz: float = 50.0) -> None:
        self.n_motors = n_motors
        self.period = 1.0 / rate_hz
        self.session = int.from_bytes(os.urandom(4), "little")
        self.seq = 0
        self._duties = [0] * n_motors
        self._estop = False
        self._disarm = True  # 起動時は DISARM（操縦者が ARM するまで）
        self._arm_req = 0
        self._clear_req = 0
        self._next_send = 0.0
        self._t0 = time.monotonic()

        self.filter = cp.SeqFilter()
        self.status: cp.Status | None = None
        self.status_time = float("-inf")
        self.rtt_ms: float | None = None
        # (送った seq, 子機の rx_count) の履歴からロス率を出す
        self._loss_hist: deque[tuple[int, int]] = deque(maxlen=50)

    # ---- 操作 ----

    def set_duties(self, duties: list[int]) -> None:
        if len(duties) != self.n_motors:
            raise ValueError("motor count mismatch")
        self._duties = [int(d) for d in duties]

    def stop(self) -> None:
        self._duties = [0] * self.n_motors

    def set_estop(self, on: bool) -> None:
        self._estop = on
        if on:
            self.stop()

    def set_disarm(self, on: bool) -> None:
        self._disarm = on
        if on:
            self.stop()

    def request_arm(self) -> None:
        """DISARM を解いて ARM を要求する（操作者の明示操作でのみ呼ぶ）。"""
        self._disarm = False
        self._arm_req = (self._arm_req + 1) & 0xFF

    def request_clear(self) -> None:
        self._clear_req = (self._clear_req + 1) & 0xFF

    # ---- 送受信 ----

    def _ms(self, now: float) -> int:
        return int((now - self._t0) * 1000) & 0xFFFFFFFF

    def step(self, now: float) -> bytes | None:
        """送る時刻になっていれば DRIVE パケットを返す。"""
        if now < self._next_send:
            return None
        self._next_send = max(self._next_send + self.period, now)
        self.seq += 1
        idle = self._estop or self._disarm
        d = cp.Drive(self._estop, self._arm_req, self._clear_req,
                     tuple([0] * self.n_motors if idle else self._duties), self._disarm)
        return cp.encode_drive(self.session, self.seq, self._ms(now), d)

    def on_packet(self, data: bytes, now: float) -> bool:
        try:
            hdr, body = cp.decode(data)
        except cp.DecodeError:
            return False
        if not isinstance(body, cp.Status) or not self.filter.accept(hdr):
            return False
        if body.ack_session != self.session:
            return False  # 前回起動時の親機あての応答
        self.status = body
        self.status_time = now
        self.rtt_ms = float((self._ms(now) - body.ack_time_ms) & 0xFFFFFFFF)
        self._loss_hist.append((body.ack_seq, body.rx_count))
        return True

    # ---- 状態 ----

    def connected(self, now: float) -> bool:
        return now - self.status_time < STATUS_TIMEOUT_S

    @property
    def loss_rate(self) -> float | None:
        """直近の履歴での DRIVE のロス率（0〜1）。"""
        if len(self._loss_hist) < 2:
            return None
        (s0, r0), (s1, r1) = self._loss_hist[0], self._loss_hist[-1]
        sent = s1 - s0
        if sent <= 0:
            return None
        return min(1.0, max(0.0, 1.0 - (r1 - r0) / sent))


def run_forever(client: ChildClient, child_addr: tuple[str, int], sock: socket.socket,
                should_stop=lambda: False) -> None:
    """単純な送受信ループ（テスト・ツール用）。親機サーバーでは自前のループに組み込む。"""
    sock.setblocking(False)
    while not should_stop():
        now = time.monotonic()
        pkt = client.step(now)
        if pkt:
            try:
                sock.sendto(pkt, child_addr)
            except OSError:
                pass  # 子機側が落ちている間も送り続ける
        try:
            while True:
                data, _ = sock.recvfrom(2048)
                client.on_packet(data, time.monotonic())
        except (BlockingIOError, ConnectionRefusedError):
            pass
        time.sleep(0.002)
