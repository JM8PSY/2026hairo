# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""子機側：親機からの DRIVE を受けて motorlink を操作する（ソケットを持たない純粋なロジック）。

安全上の決まり（CLAUDE.md §5）：
- 親機からの DRIVE が timeout（既定 0.3秒）途絶えたら ARM を解除する。再開は操作者の ARM 要求から。
- ESTOP フラグが立っている間は ESP32 を ESTOP にし続け、ARM 要求も受け付けない。
- DISARM フラグが立っている間は ARM を解除し、ARM 要求も受け付けない。
- 親機の session が変わった直後（親機の再起動・子機の起動直後）は ARM/CLEAR カウンタを
  基準値として覚えるだけで実行しない（再接続しただけで動き出さないため）。
"""
from __future__ import annotations

from typing import Protocol

from motorlink.proto import State

from . import proto as cp

ESP_UNKNOWN = 0xFF


class Link(Protocol):
    """motorlink.MotorLink のうち、ここで使う部分"""

    phase: object
    status: object
    connected: bool

    def arm(self) -> None: ...
    def disarm(self) -> None: ...
    def estop(self) -> None: ...
    def clear(self) -> None: ...
    def set_duties(self, duties: list[int]) -> None: ...


class ChildController:
    def __init__(self, link: Link, n_motors: int, timeout: float = 0.3) -> None:
        self.link = link
        self.n_motors = n_motors
        self.timeout = timeout
        self.filter = cp.SeqFilter()
        self.rx_count = 0
        self.last_rx: float | None = None
        self.last_hdr: cp.Header | None = None
        self._arm_req: int | None = None
        self._clear_req: int | None = None
        self.last_stop_reason: str | None = None

    def on_packet(self, data: bytes, now: float) -> bool:
        """DRIVE を処理する。受け入れたら True。"""
        try:
            hdr, body = cp.decode(data)
        except cp.DecodeError:
            return False
        if hdr.type != cp.T_DRIVE or not isinstance(body, cp.Drive):
            return False
        new_session = hdr.session != self.filter.session
        if not self.filter.accept(hdr):
            return False
        if len(body.duties) != self.n_motors:
            return False
        self.rx_count += 1
        self.last_rx = now
        self.last_hdr = hdr

        if new_session:
            self._arm_req = body.arm_req
            self._clear_req = body.clear_req

        if body.estop:
            st = self.link.status
            if st is None or st.state != State.ESTOP:
                self.link.estop()
            self._arm_req = body.arm_req  # ESTOP 中の ARM 要求は捨てる
        if body.clear_req != self._clear_req:
            self._clear_req = body.clear_req
            self.link.clear()
        if body.disarm:
            if _phase_name(self.link.phase) != "disarmed":
                self.link.disarm()
                self.last_stop_reason = "parent_disarm"
            self._arm_req = body.arm_req  # DISARM 中の ARM 要求は捨てる
        if body.arm_req != self._arm_req:
            self._arm_req = body.arm_req
            if not body.estop:
                self.link.arm()

        if not body.estop and not body.disarm and _phase_name(self.link.phase) == "armed":
            self.link.set_duties(list(body.duties))
        return True

    def tick(self, now: float) -> None:
        if self.last_rx is None:
            return
        if now - self.last_rx > self.timeout and _phase_name(self.link.phase) != "disarmed":
            self.link.disarm()
            self.last_stop_reason = "parent_timeout"

    def status(self) -> cp.Status:
        st = self.link.status
        hdr = self.last_hdr
        connected = bool(self.link.connected)
        return cp.Status(
            ack_session=hdr.session if hdr else 0,
            ack_seq=hdr.seq if hdr else 0,
            ack_time_ms=hdr.time_ms if hdr else 0,
            rx_count=self.rx_count,
            stale=self.filter.stale,
            esp_state=int(st.state) if st is not None and connected else ESP_UNKNOWN,
            esp_reason=int(st.reason) if st is not None else 0,
            esp_fault=int(st.fault) if st is not None else 0,
            phase=_phase_name(self.link.phase),
            connected=connected,
            outputs=tuple(st.outputs) if st is not None else (0,) * self.n_motors,
        )


def _phase_name(phase: object) -> str:
    return getattr(phase, "value", phase)  # motorlink.Phase か文字列
