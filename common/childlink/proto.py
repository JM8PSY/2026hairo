"""親機 ⇔ 子機 UDP プロトコル（CLAUDE.md §8）。docs/protocol_childlink.md も参照。

UDP は落ちる・前後する前提で、どのパケットも単独で意味が通るようにする：
- 指令（DRIVE）は毎回「全モーターのデューティ」と「ESTOP フラグ」を丸ごと送る。
- ARM / CLEAR は「要求カウンタ」で送る。値が変わったときだけ子機が実行する
  （落ちても次のパケットで伝わり、重複しても1回しか実行されない）。
- session は送信側の起動ごとに変わる乱数。seq は session 内で単調増加し、古いものは捨てる。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"HC"
VERSION = 1

T_DRIVE = 0x01   # 親機 → 子機
T_STATUS = 0x81  # 子機 → 親機

# DRIVE flags
F_ESTOP = 0x01

# 共通ヘッダ: magic(2s) version(B) type(B) session(I) seq(I) time_ms(I)
_HDR = struct.Struct("<2sBBIII")
# DRIVE: flags(B) arm_req(B) clear_req(B) n(B) + duty(h) x n
_DRIVE = struct.Struct("<BBBB")
# STATUS: ack_session(I) ack_seq(I) ack_time_ms(I) rx_count(I) stale(I)
#         esp_state(B) esp_reason(B) esp_fault(B) phase(B) connected(B) n(B) + out(h) x n
_STATUS = struct.Struct("<IIIIIBBBBBB")

MAX_MOTORS = 16

PHASES = ("disarmed", "arming", "armed")


@dataclass(frozen=True)
class Header:
    type: int
    session: int
    seq: int
    time_ms: int


@dataclass(frozen=True)
class Drive:
    estop: bool
    arm_req: int
    clear_req: int
    duties: tuple[int, ...]


@dataclass(frozen=True)
class Status:
    ack_session: int
    ack_seq: int       # 最後に受け取った DRIVE の seq
    ack_time_ms: int   # その DRIVE の time_ms（親機が往復時間を測る）
    rx_count: int      # 受け取った DRIVE の数（親機がロス率を測る）
    stale: int         # 古い・重複として捨てた数
    esp_state: int     # motorlink.proto.State（ESP32 と通信できていなければ 0xFF）
    esp_reason: int
    esp_fault: int
    phase: str         # 子機の motorlink の ARM 状態
    connected: bool    # 子機 ⇔ ESP32
    outputs: tuple[int, ...]


class DecodeError(ValueError):
    pass


def encode_drive(session: int, seq: int, time_ms: int, d: Drive) -> bytes:
    n = len(d.duties)
    if n > MAX_MOTORS:
        raise ValueError("too many motors")
    return (_HDR.pack(MAGIC, VERSION, T_DRIVE, session, seq, time_ms & 0xFFFFFFFF)
            + _DRIVE.pack(F_ESTOP if d.estop else 0, d.arm_req & 0xFF, d.clear_req & 0xFF, n)
            + struct.pack(f"<{n}h", *d.duties))


def encode_status(session: int, seq: int, time_ms: int, s: Status) -> bytes:
    n = len(s.outputs)
    return (_HDR.pack(MAGIC, VERSION, T_STATUS, session, seq, time_ms & 0xFFFFFFFF)
            + _STATUS.pack(s.ack_session, s.ack_seq, s.ack_time_ms & 0xFFFFFFFF, s.rx_count,
                           s.stale, s.esp_state, s.esp_reason, s.esp_fault,
                           PHASES.index(s.phase), int(s.connected), n)
            + struct.pack(f"<{n}h", *s.outputs))


def decode(data: bytes) -> tuple[Header, Drive | Status]:
    if len(data) < _HDR.size:
        raise DecodeError("short packet")
    magic, ver, ptype, session, seq, time_ms = _HDR.unpack_from(data)
    if magic != MAGIC or ver != VERSION:
        raise DecodeError("bad magic/version")
    hdr = Header(ptype, session, seq, time_ms)
    body = data[_HDR.size:]
    if ptype == T_DRIVE:
        if len(body) < _DRIVE.size:
            raise DecodeError("short DRIVE")
        flags, arm_req, clear_req, n = _DRIVE.unpack_from(body)
        if n > MAX_MOTORS or len(body) != _DRIVE.size + 2 * n:
            raise DecodeError("bad DRIVE length")
        duties = struct.unpack_from(f"<{n}h", body, _DRIVE.size)
        return hdr, Drive(bool(flags & F_ESTOP), arm_req, clear_req, tuple(duties))
    if ptype == T_STATUS:
        if len(body) < _STATUS.size:
            raise DecodeError("short STATUS")
        (ack_session, ack_seq, ack_time, rx, stale, st, rs, ft, ph, conn,
         n) = _STATUS.unpack_from(body)
        if n > MAX_MOTORS or len(body) != _STATUS.size + 2 * n or ph >= len(PHASES):
            raise DecodeError("bad STATUS")
        outs = struct.unpack_from(f"<{n}h", body, _STATUS.size)
        return hdr, Status(ack_session, ack_seq, ack_time, rx, stale, st, rs, ft,
                           PHASES[ph], bool(conn), tuple(outs))
    raise DecodeError(f"unknown type 0x{ptype:02x}")


class SeqFilter:
    """古い・重複したパケットを捨てる。送信側が再起動して session が変わったら受け入れ直す。"""

    def __init__(self) -> None:
        self.session: int | None = None
        self.last_seq = -1
        self.stale = 0

    def accept(self, hdr: Header) -> bool:
        if hdr.session != self.session:
            self.session = hdr.session
            self.last_seq = hdr.seq
            return True
        if hdr.seq <= self.last_seq:
            self.stale += 1
            return False
        self.last_seq = hdr.seq
        return True
