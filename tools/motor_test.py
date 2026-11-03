#!/usr/bin/env python3
"""モーター単体確認ツール（実機の最初の通電用）。

  # 状態を表示するだけ（モーターは回さない）
  tools/motor_test.py --board child status
  # C1 を 15% で 1 秒だけ回す（確認プロンプトあり）
  tools/motor_test.py --board child spin C1 --duty 150 --seconds 1

安全のため：
- デューティは既定で最大 30%、時間は最大 3 秒（--allow-high で 100% / 10 秒まで）。
- 回す前に確認を求める（--yes で省略。シミュレータ用）。
- Ctrl-C・例外・終了時は必ず全0にして ARM を解除する。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

from motorlink import LinkError, MotorLink, Phase, proto  # noqa: E402
from motorlink.boards import BOARD_IDS, MOTOR_NAMES  # noqa: E402

SAFE_DUTY = 300
SAFE_SECONDS = 3.0


def fmt_status(st: proto.Status | None) -> str:
    if st is None:
        return "STATUS なし"
    outs = " ".join(f"{o:+5d}" for o in st.outputs)
    return (f"state={st.state.name:<8} reason={st.reason.name:<8} fault=0x{st.fault:02x} "
            f"limits=0x{st.limits:04x} rx_err={st.rx_errors} out=[{outs}]")


def cmd_status(link: MotorLink, args) -> int:
    end = time.monotonic() + args.seconds if args.seconds else None
    try:
        while end is None or time.monotonic() < end:
            print(fmt_status(link.status), flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_spin(link: MotorLink, args, board_id: int) -> int:
    names = MOTOR_NAMES[board_id]
    name = args.motor.upper()
    if name not in names:
        print(f"モーター名は {', '.join(names)} のどれか", file=sys.stderr)
        return 2
    idx = names.index(name)
    max_duty = proto.DUTY_MAX if args.allow_high else SAFE_DUTY
    max_sec = 10.0 if args.allow_high else SAFE_SECONDS
    if abs(args.duty) > max_duty or not 0 < args.seconds <= max_sec:
        print(f"duty は ±{max_duty}、seconds は {max_sec} 秒以下にしてください", file=sys.stderr)
        return 2

    print(f"{name} を duty {args.duty:+d}（{args.duty / 10:.0f}%）で {args.seconds} 秒回します。")
    print("機体が浮いている／周囲に人がいないことを確認してください。")
    if not args.yes and input("回しますか？ [y/N] ").strip().lower() != "y":
        print("中止しました")
        return 1

    link.arm()
    deadline = time.monotonic() + 1.0
    while link.phase is not Phase.ARMED:
        if link.phase is Phase.DISARMED or time.monotonic() > deadline:
            print(f"ARM できませんでした: {fmt_status(link.status)}", file=sys.stderr)
            return 1
        time.sleep(0.02)

    duties = [0] * len(names)
    duties[idx] = args.duty
    end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < end:
            if link.phase is not Phase.ARMED:
                print(f"途中で停止しました（{link.last_disarm_reason}）: {fmt_status(link.status)}",
                      file=sys.stderr)
                return 1
            link.set_duties(duties)
            print(fmt_status(link.status), flush=True)
            time.sleep(0.1)
    finally:
        link.set_duties([0] * len(names))
        link.disarm()
    print("停止しました")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/robot_mcu")
    ap.add_argument("--board", choices=BOARD_IDS, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="状態を表示する（回さない）")
    st.add_argument("--seconds", type=float, default=0, help="表示する時間（0 = Ctrl-C まで）")
    sp = sub.add_parser("spin", help="1モーターを一定時間回す")
    sp.add_argument("motor", help="P1〜P9 / C1〜C3")
    sp.add_argument("--duty", type=int, default=150, help="千分率（既定 150 = 15%%）")
    sp.add_argument("--seconds", type=float, default=1.0)
    sp.add_argument("--allow-high", action="store_true", help="上限を 100%% / 10 秒に広げる")
    sp.add_argument("--yes", action="store_true", help="確認を省略する")
    args = ap.parse_args(argv)

    board_id = BOARD_IDS[args.board]
    link = MotorLink(args.port, board_id)
    try:
        link.open()
    except (LinkError, OSError) as e:
        print(f"接続できません: {e}", file=sys.stderr)
        return 1
    try:
        info = link.info
        print(f"接続: {args.port} board={args.board} motors={info.n_motors} "
              f"fw={'.'.join(map(str, info.fw_version))}")
        if args.cmd == "status":
            return cmd_status(link, args)
        return cmd_spin(link, args, board_id)
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
