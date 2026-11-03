"""ESP32 とシリアルで話すホスト側ライブラリ（CLAUDE.md §4）。標準ライブラリのみ。

- 約50Hzで CMD_SET を送り続ける（ESP32 のウォッチドッグ 200ms を切らさない）。
- 上位から set_duties() が cmd_timeout（既定 0.3秒）来なければ、自動で全0を送る。
- ESP32 がウォッチドッグ等で DISARMED に落ちたら、こちらも ARM を解除する。勝手に再ARMしない。
- 接続時に INFO の基板IDを確認し、親機用/子機用ファームの取り違えを拒否する。
"""
from __future__ import annotations

import enum
import os
import select
import termios
import threading
import time
import tty
from typing import Callable

from . import proto

STATUS_TIMEOUT_S = 0.5  # STATUS(20Hz) がこれだけ来なければ ESP32 との通信断とみなす
ARM_TIMEOUT_S = 1.0     # arm() 後この時間内に ARMED にならなければあきらめる


class LinkError(Exception):
    pass


class BoardMismatch(LinkError):
    pass


class Phase(enum.Enum):
    DISARMED = "disarmed"
    ARMING = "arming"
    ARMED = "armed"


class MotorLink:
    def __init__(
        self,
        port: str,
        expected_board: int,
        *,
        baud: int = 921600,
        rate_hz: float = 50.0,
        cmd_timeout: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.port = port
        self.expected_board = expected_board
        self.baud = baud
        self.period = 1.0 / rate_hz
        self.cmd_timeout = cmd_timeout
        self._clock = clock

        self._fd: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._parser = proto.Parser()
        self._seq = 0

        self.info: proto.Info | None = None
        self._info_event = threading.Event()
        self._status_event = threading.Event()
        self._status: proto.Status | None = None
        self._status_time = 0.0
        self._phase = Phase.DISARMED
        self._arm_started = 0.0
        self._targets: list[int] = []
        self._targets_time = 0.0
        self.last_disarm_reason: str | None = None

    # ---- 接続 ----

    def open(self, timeout: float = 2.0) -> proto.Info:
        if self._fd is not None:
            raise LinkError(f"{self.port}: すでに開いています")
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self._configure(fd)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="motorlink", daemon=True)
        self._thread.start()

        deadline = self._clock() + timeout
        while not self._info_event.is_set():
            self._write(proto.encode(proto.CMD_PING, self._next_seq()))
            if self._info_event.wait(0.2):
                break
            if self._clock() > deadline:
                self.close()
                raise LinkError(f"{self.port}: ESP32 から INFO が返りません")
        info = self.info
        assert info is not None
        if info.proto_version != proto.VERSION:
            self.close()
            raise LinkError(f"プロトコル版が違います（ESP32={info.proto_version}, host={proto.VERSION}）")
        if info.board_id != self.expected_board:
            self.close()
            raise BoardMismatch(
                f"基板IDが違います（ESP32={info.board_id}, 期待={self.expected_board}）。"
                "親機用/子機用ファームの取り違えを確認してください"
            )
        with self._lock:
            self._targets = [0] * info.n_motors
        if not self._status_event.wait(max(0.0, deadline - self._clock())):
            self.close()
            raise LinkError(f"{self.port}: ESP32 から STATUS が来ません")
        return info

    def _configure(self, fd: int) -> None:
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        speed = getattr(termios, f"B{self.baud}", None)
        if speed is not None:
            attrs[4] = attrs[5] = speed
        # macOS の termios には B921600 が無い。pty（シミュレータ）では速度は関係ないので無視する
        attrs[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._fd is not None:
            # 閉じる前に停止を伝える（ARM 解除）
            try:
                self._send_set(arm=False, duties=[0] * len(self._targets))
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None
        with self._lock:
            self._phase = Phase.DISARMED

    def __enter__(self) -> "MotorLink":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 操作 ----

    def arm(self) -> None:
        """全0で ARM を要求する。操作者の明示操作でのみ呼ぶこと。"""
        with self._lock:
            self._targets = [0] * len(self._targets)
            self._targets_time = self._clock()
            self._phase = Phase.ARMING
            self._arm_started = self._clock()
            self.last_disarm_reason = None

    def disarm(self) -> None:
        with self._lock:
            self._disarm_locked("host")
        self._send_set(arm=False, duties=[0] * len(self._targets))

    def set_duties(self, duties: list[int]) -> None:
        """各モーターのデューティ（-1000〜1000）。ARM 中でなければ無視される。"""
        with self._lock:
            if len(duties) != len(self._targets):
                raise ValueError(f"モーター数が違います（{len(duties)} != {len(self._targets)}）")
            self._targets = [max(-proto.DUTY_MAX, min(proto.DUTY_MAX, int(d))) for d in duties]
            self._targets_time = self._clock()

    def estop(self) -> None:
        with self._lock:
            self._disarm_locked("estop")
        self._write(proto.encode(proto.CMD_ESTOP, self._next_seq()))

    def clear(self) -> None:
        with self._lock:
            self._disarm_locked("clear")
        self._write(proto.encode(proto.CMD_CLEAR, self._next_seq()))

    # ---- 状態 ----

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def status(self) -> proto.Status | None:
        return self._status

    @property
    def connected(self) -> bool:
        return self._status is not None and self._clock() - self._status_time < STATUS_TIMEOUT_S

    # ---- 内部 ----

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _write(self, data: bytes) -> None:
        fd = self._fd
        if fd is None:
            return
        view = memoryview(data)
        deadline = self._clock() + 0.05
        while view:
            try:
                n = os.write(fd, view)
                view = view[n:]
            except BlockingIOError:
                if self._clock() > deadline:
                    return  # 詰まっている間は捨てる（次周期で送り直す）
                select.select([], [fd], [], 0.005)

    def _send_set(self, arm: bool, duties: list[int]) -> None:
        self._write(proto.encode_set(self._next_seq(), duties, arm))

    def _disarm_locked(self, reason: str) -> None:
        if self._phase is not Phase.DISARMED:
            self.last_disarm_reason = reason
        self._phase = Phase.DISARMED
        self._targets = [0] * len(self._targets)

    def _on_frame(self, f: proto.Frame) -> None:
        if f.type == proto.INFO:
            try:
                self.info = proto.decode_info(f.payload)
            except ValueError:
                return
            self._info_event.set()
        elif f.type == proto.STATUS:
            try:
                st = proto.decode_status(f.payload)
            except ValueError:
                return
            with self._lock:
                self._status = st
                self._status_time = self._clock()
                self._status_event.set()
                if self._phase is Phase.ARMING and st.state == proto.State.ARMED:
                    self._phase = Phase.ARMED
                elif self._phase is Phase.ARMED and st.state != proto.State.ARMED:
                    # ESP32 側で止まった。こちらからは再ARMしない
                    self._disarm_locked(f"esp32:{st.reason.name.lower()}")

    def _tick(self) -> None:
        now = self._clock()
        with self._lock:
            if self._phase is not Phase.DISARMED and self._status is not None \
                    and now - self._status_time > STATUS_TIMEOUT_S:
                self._disarm_locked("link_lost")
            if self._phase is Phase.ARMING and now - self._arm_started > ARM_TIMEOUT_S:
                self._disarm_locked("arm_timeout")
            if now - self._targets_time > self.cmd_timeout:
                self._targets = [0] * len(self._targets)
            phase = self._phase
            duties = list(self._targets) if phase is Phase.ARMED else [0] * len(self._targets)
        if self._targets:
            self._send_set(arm=phase is not Phase.DISARMED, duties=duties)

    def _run(self) -> None:
        next_send = self._clock()
        while not self._stop.is_set():
            fd = self._fd
            if fd is None:
                return
            wait = max(0.0, next_send - self._clock())
            r, _, _ = select.select([fd], [], [], wait)
            if r:
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    data = b""
                except OSError:
                    self._on_link_lost()
                    return
                if not data:  # 相手が閉じた（pty のマスター側が終了した等）
                    self._on_link_lost()
                    return
                for f in self._parser.feed(data):
                    self._on_frame(f)
            if self._clock() >= next_send:
                next_send += self.period
                if next_send < self._clock():
                    next_send = self._clock() + self.period
                try:
                    self._tick()
                except OSError:
                    self._on_link_lost()
                    return

    def _on_link_lost(self) -> None:
        with self._lock:
            self._disarm_locked("link_lost")
            self._status_time = float("-inf")
