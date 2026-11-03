"""ホスト ⇔ ESP32 通信プロトコル（CLAUDE.md §4）。

C++ 側 firmware/motor_esp32/lib/proto/proto.h と必ず同時に変更すること。

フレーム: 0xAA 0x55 | type | seq | len | payload[len] | CRC16(LE)
CRC16-CCITT（多項式 0x1021、初期値 0xFFFF）を type から payload 末尾まで計算する。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

SYNC0 = 0xAA
SYNC1 = 0x55
VERSION = 1
MAX_PAYLOAD = 64
DUTY_MAX = 1000

CMD_SET = 0x01
CMD_ESTOP = 0x02
CMD_CLEAR = 0x03
CMD_PING = 0x04
STATUS = 0x81
INFO = 0x82

SET_FLAG_ARM = 0x01

BOARD_ID_PARENT = 1
BOARD_ID_CHILD = 2


class State(IntEnum):
    DISARMED = 0
    ARMED = 1
    ESTOP = 2
    FAULT = 3


class Reason(IntEnum):
    NONE = 0
    BOOT = 1
    WATCHDOG = 2
    HOST = 3
    ESTOP = 4
    FAULT = 5
    CLEAR = 6


FAULT_I2C = 0x01


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode(ftype: int, seq: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too long")
    body = bytes([ftype, seq & 0xFF, len(payload)]) + payload
    return bytes([SYNC0, SYNC1]) + body + struct.pack("<H", crc16(body))


def encode_set(seq: int, duties: list[int], arm: bool) -> bytes:
    duties = [max(-DUTY_MAX, min(DUTY_MAX, int(d))) for d in duties]
    payload = bytes([SET_FLAG_ARM if arm else 0, len(duties)])
    payload += struct.pack(f"<{len(duties)}h", *duties)
    return encode(CMD_SET, seq, payload)


@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    payload: bytes


@dataclass(frozen=True)
class Status:
    state: State
    reason: Reason
    fault: int
    limits: int
    rx_errors: int
    outputs: tuple[int, ...]


@dataclass(frozen=True)
class Info:
    proto_version: int
    board_id: int
    n_motors: int
    fw_version: tuple[int, int, int]


def decode_status(payload: bytes) -> Status:
    if len(payload) < 8:
        raise ValueError("short STATUS")
    state, reason, fault, limits, rx_errors, n = struct.unpack_from("<BBBHHB", payload)
    if len(payload) != 8 + 2 * n:
        raise ValueError("bad STATUS length")
    outputs = struct.unpack_from(f"<{n}h", payload, 8)
    return Status(State(state), Reason(reason), fault, limits, rx_errors, tuple(outputs))


def decode_info(payload: bytes) -> Info:
    if len(payload) != 6:
        raise ValueError("bad INFO length")
    v, board, n, ma, mi, pa = payload
    return Info(v, board, n, (ma, mi, pa))


class Parser:
    """1バイトずつ入れるとフレームを組み立てる。壊れたフレームは捨てて再同期する。"""

    def __init__(self) -> None:
        self.errors = 0
        self._state = 0
        self._hdr = bytearray()
        self._payload = bytearray()
        self._len = 0
        self._crc_lo = 0

    def feed(self, data: bytes) -> list[Frame]:
        frames = []
        for b in data:
            f = self._feed1(b)
            if f is not None:
                frames.append(f)
        return frames

    def _error(self) -> None:
        self.errors += 1
        self._state = 0

    def _feed1(self, b: int) -> Frame | None:
        s = self._state
        if s == 0:  # SYNC0
            if b == SYNC0:
                self._state = 1
        elif s == 1:  # SYNC1
            self._state = 2 if b == SYNC1 else (1 if b == SYNC0 else 0)
            self._hdr.clear()
        elif s in (2, 3):  # type, seq
            self._hdr.append(b)
            self._state += 1
        elif s == 4:  # len
            if b > MAX_PAYLOAD:
                self._error()
                return None
            self._hdr.append(b)
            self._len = b
            self._payload.clear()
            self._state = 6 if b == 0 else 5
        elif s == 5:  # payload
            self._payload.append(b)
            if len(self._payload) == self._len:
                self._state = 6
        elif s == 6:  # CRC lo
            self._crc_lo = b
            self._state = 7
        elif s == 7:  # CRC hi
            crc = crc16(bytes(self._payload), crc16(bytes(self._hdr)))
            if crc != (self._crc_lo | (b << 8)):
                self._error()
                return None
            self._state = 0
            return Frame(self._hdr[0], self._hdr[1], bytes(self._payload))
        return None
