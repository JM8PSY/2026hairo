#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""親機のゲートウェイ：ROS 2（地図・自己位置・スキャン・LiDAR の ON/OFF）とブラウザの仲介（CLAUDE.md §6, §7）。

  parent/server/gateway.py [--config parent/config/gateway.json] [--port PORT]

- GET /ws → WebSocket。プロトコルは docs/protocol_gateway.md
- 操縦サーバー（app.py）とは別プロセス。ROS が落ちても操縦と非常停止に影響しない
- rclpy が使えない環境でも起動する（「ROS 未接続」と表示するだけ）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from map_core import SystemStats, encode_map, write_map_files  # noqa: E402

log = logging.getLogger("gateway")

TICK_S = 0.1
BACKEND = web.AppKey("backend", object)


class NoRos:
    """rclpy が無い環境の代役。"""

    available = False
    map = None
    scan = None
    pose = None
    laser_pose = None

    def scan_hz(self) -> float:
        return 0.0

    def driver_running(self) -> bool:
        return False

    def slam_running(self) -> bool:
        return False

    def close(self) -> None:
        pass


def make_backend():
    try:
        from ros_backend import RosBackend
    except ImportError as e:
        log.warning("rclpy が使えないので ROS なしで起動します: %s", e)
        return NoRos()
    return RosBackend()


def build_app(cfg: dict, backend=None, stats: SystemStats | None = None) -> web.Application:
    app = web.Application()
    backend = backend if backend is not None else make_backend()
    stats = stats or SystemStats()
    map_period = 1.0 / cfg.get("map_hz", 1)
    scan_period = 1.0 / cfg.get("scan_hz", 5)
    map_dir = Path(cfg.get("map_dir", ROOT / "parent/maps"))
    if not map_dir.is_absolute():
        map_dir = ROOT / map_dir
    lidar_wanted = bool(cfg.get("lidar_default_on", True))
    sensors_msg: dict = {}
    tasks: list[asyncio.Task] = []

    def sensors_state() -> dict:
        return {"t": "sensors", "ros": backend.available, "slam": backend.slam_running(),
                "lidar": {"driver": backend.driver_running(), "wanted": lidar_wanted, "scan_hz": backend.scan_hz()},
                "d455": {"state": "unsupported"}}

    async def set_lidar(on: bool) -> None:
        nonlocal lidar_wanted
        if not backend.available:
            raise RuntimeError("ROS 未接続です")
        await backend.set_lidar(on)
        lidar_wanted = on

    async def save_map() -> dict:
        m = backend.map
        if m is None:
            raise RuntimeError("保存できる地図がありません")
        stem = "map-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        loop = asyncio.get_running_loop()
        yaml = await loop.run_in_executor(None, write_map_files, map_dir, stem, m)
        # 続きから地図を作るためのデータ。地図の画像は保存済みなので、失敗しても画像は残る
        await backend.serialize_map(str(map_dir / stem))
        return {"path": str(yaml)}

    async def do_action(ws: web.WebSocketResponse, data: dict) -> None:
        op = data.get("t")
        try:
            result: dict = {}
            if op == "lidar":
                await set_lidar(bool(data.get("on")))
            elif op == "map_save":
                result = await save_map()
            elif op == "map_reset":
                if not backend.available:
                    raise RuntimeError("ROS 未接続です")
                await backend.reset_map()
            else:
                return
            await ws.send_json({"t": "result", "op": op, "ok": True, **result})
        except ConnectionError:
            pass
        except Exception as e:  # サービスの失敗はサーバーを落とさず画面に出す
            log.warning("%s に失敗: %s", op, e)
            await ws.send_json({"t": "result", "op": op, "ok": False, "error": str(e)})

    async def sender(ws: web.WebSocketResponse) -> None:
        # 遅いブラウザには古い値を送らず最新だけを送る
        sent_map = sent_scan = 0
        next_map = next_scan = 0.0
        sent_sensors = None
        while True:
            now = time.monotonic()
            if sensors_msg is not sent_sensors:
                sent_sensors = sensors_msg
                await ws.send_json(sent_sensors)
            m = backend.map
            if m is None:
                if sent_map:  # 地図がリセットされた
                    sent_map = 0
                    await ws.send_json({"t": "map_clear"})
            elif m["seq"] != sent_map and now >= next_map:
                sent_map = m["seq"]
                next_map = now + map_period
                await ws.send_json(encode_map(m))
            pose = backend.pose
            await ws.send_json({"t": "pose", "pose": pose})
            scan, laser = backend.scan, backend.laser_pose
            if scan is not None and scan["seq"] != sent_scan and laser is not None and now >= next_scan:
                sent_scan = scan["seq"]
                next_scan = now + scan_period
                await ws.send_json({"t": "scan", "angle_min": scan["angle_min"], "angle_inc": scan["angle_inc"],
                                    "ranges": scan["ranges"], "laser": laser})
            await asyncio.sleep(TICK_S)

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=5.0)
        await ws.prepare(request)
        task = asyncio.create_task(sender(ws))
        actions: set[asyncio.Task] = set()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    # サービスの応答待ちで受信を止めない
                    t = asyncio.create_task(do_action(ws, data))
                    actions.add(t)
                    t.add_done_callback(actions.discard)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, ConnectionError):
                pass
        return ws

    async def status_loop() -> None:
        nonlocal sensors_msg
        while True:
            sensors_msg = {**sensors_state(), "system": stats.snapshot()}
            # ドライバが再起動するとスキャンが始まるので、OFF のままになるよう止め直す
            if not lidar_wanted and backend.scan_hz() > 0:
                try:
                    await backend.set_lidar(False)
                except Exception as e:
                    log.warning("LiDAR を止められません: %s", e)
            await asyncio.sleep(1.0)

    async def on_startup(app: web.Application) -> None:
        tasks.append(asyncio.create_task(status_loop()))

    async def on_cleanup(app: web.Application) -> None:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        backend.close()

    app[BACKEND] = backend
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "parent/config/gateway.json")
    ap.add_argument("--port", type=int, help="HTTP ポート（設定ファイルより優先）")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    http = cfg.get("http", {})
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(build_app(cfg), host=http.get("host", "0.0.0.0"), port=args.port or http.get("port", 8082))
    return 0


if __name__ == "__main__":
    sys.exit(main())
