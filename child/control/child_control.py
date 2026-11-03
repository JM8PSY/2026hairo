#!/usr/bin/env python3
"""子機の制御プロセス：親機からの UDP 指令を受けて ESP32 へ送り、状態を親機へ返す。

  child/control/child_control.py [--config child/config/child.json] [--serial PATH] [--port N]

コマンドライン引数は設定ファイルより優先する。
"""
from __future__ import annotations

import argparse
import json
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
ESP_LOST_EXIT_S = 2.0   # ESP32 との通信がこれだけ途絶えたら終了する（systemd が再起動してつなぎ直す）


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--config", type=Path, default=root / "child/config/child.json")
    ap.add_argument("--serial")
    ap.add_argument("--bind")
    ap.add_argument("--port", type=int)
    ap.add_argument("--timeout", type=float, help="親機からの指令が途絶えたら停止するまでの秒数")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    args.serial = args.serial or cfg.get("motor", {}).get("serial", "/dev/robot_mcu")
    args.bind = args.bind or cfg.get("udp", {}).get("bind", "0.0.0.0")
    if args.port is None:
        args.port = cfg.get("udp", {}).get("port", 47100)
    if args.timeout is None:
        args.timeout = cfg.get("control", {}).get("parent_timeout", 0.3)

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
    last_esp_ok = t0
    rc = 0
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
            if link.connected:
                last_esp_ok = now
            elif now - last_esp_ok > ESP_LOST_EXIT_S:
                print("ESP32 との通信が途絶えたため終了します", file=sys.stderr, flush=True)
                rc = 1
                break
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
    return rc


if __name__ == "__main__":
    sys.exit(main())
