#!/usr/bin/env python3
"""子機の制御プロセス：親機からの UDP 指令を受けて ESP32 へ送り、状態を親機へ返す。

  child/control/child_control.py --serial /dev/robot_mcu --port 47100
"""
from __future__ import annotations

import argparse
import os
import select
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from childlink import ChildController  # noqa: E402
from childlink import proto as cp  # noqa: E402
from motorlink import LinkError, MotorLink, proto  # noqa: E402

STATUS_PERIOD_S = 0.05  # 20Hz


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial", default="/dev/robot_mcu")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=47100)
    ap.add_argument("--timeout", type=float, default=0.3, help="親機からの指令が途絶えたら停止するまでの秒数")
    args = ap.parse_args(argv)

    link = MotorLink(args.serial, proto.BOARD_ID_CHILD)
    try:
        info = link.open()
    except (LinkError, OSError) as e:
        print(f"ESP32 に接続できません: {e}", file=sys.stderr)
        return 1
    print(f"ESP32 接続: {args.serial} motors={info.n_motors}", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))
    sock.setblocking(False)
    print(f"UDP 待受: {args.bind}:{sock.getsockname()[1]}", flush=True)

    ctrl = ChildController(link, info.n_motors, timeout=args.timeout)
    session = int.from_bytes(os.urandom(4), "little")
    seq = 0
    parent_addr = None
    next_status = time.monotonic()
    t0 = time.monotonic()
    try:
        while True:
            r, _, _ = select.select([sock], [], [], 0.01)
            now = time.monotonic()
            if r:
                try:
                    while True:
                        data, addr = sock.recvfrom(2048)
                        if ctrl.on_packet(data, now):
                            parent_addr = addr
                except BlockingIOError:
                    pass
            ctrl.tick(now)
            if parent_addr and now >= next_status:
                next_status = now + STATUS_PERIOD_S
                seq += 1
                pkt = cp.encode_status(session, seq, int((now - t0) * 1000), ctrl.status())
                try:
                    sock.sendto(pkt, parent_addr)
                except OSError:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        link.close()  # 停止を伝えてから閉じる
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
