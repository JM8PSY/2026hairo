#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""親機 Web サーバー：Web UI の配信と、ブラウザ ⇔ 親機・子機 の仲介（CLAUDE.md §6）。

  parent/server/app.py [--config parent/config/parent.json] [--serial PATH] [--child HOST:PORT]

- GET /      → web/ 以下の静的ファイル（index.html）
- GET /video → 映像ページ（映像そのものは別プロセスの video.py が配信する）
- GET /ws    → WebSocket。JSON メッセージ（docs/protocol_web.md）
- 50Hz で ControlCore.tick() → ESP32（motorlink）と子機（childlink/UDP）へ指令
- 10Hz で全クライアントへ status を配る

ESP32 や子機が見つからなくても起動する（つながり次第使う）。ROS 2 との連携は後で足す。
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import socket
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from childlink import ChildClient  # noqa: E402
from control import Config, ControlCore  # noqa: E402
from motorlink import LinkError, MotorLink, Phase, proto  # noqa: E402

RECONNECT_S = 2.0


class ParentMotor:
    """MotorLink を包み、未接続でも呼べるようにする。切れたら作り直して再接続する。"""

    def __init__(self, port: str | None) -> None:
        self.port = port
        self.link: MotorLink | None = None
        self.error: str | None = None
        self._next_try = 0.0

    def maintain(self, now: float) -> None:
        if self.port is None:
            return
        if self.link is not None and self.link.connected:
            return
        if now < self._next_try:
            return
        self._next_try = now + RECONNECT_S
        if self.link is not None:
            self.link.close()
            self.link = None
        link = MotorLink(self.port, proto.BOARD_ID_PARENT)
        try:
            link.open(timeout=1.0)
        except (LinkError, OSError) as e:
            self.error = str(e)
            return
        self.link, self.error = link, None

    def _ok(self) -> MotorLink | None:
        return self.link if self.link is not None and self.link.connected else None

    def arm(self) -> None:
        if link := self._ok():
            link.arm()

    def disarm(self) -> None:
        if link := self._ok():
            link.disarm()

    def estop(self) -> None:
        if link := self._ok():
            link.estop()

    def clear(self) -> None:
        if link := self._ok():
            link.clear()

    def set_duties(self, duties: list[int]) -> None:
        if link := self._ok():
            link.set_duties(duties)

    def close(self) -> None:
        if self.link is not None:
            self.link.close()

    def snapshot(self) -> dict:
        link = self._ok()
        st = link.status if link else None
        return {
            "connected": link is not None,
            "error": self.error,
            "phase": link.phase.value if link else Phase.DISARMED.value,
            "last_disarm_reason": link.last_disarm_reason if link else None,
            "state": st.state.name if st else None,
            "reason": st.reason.name if st else None,
            "fault": st.fault if st else 0,
            "limits": st.limits if st else 0,
            "outputs": list(st.outputs) if st else [],
        }


class ChildUdp(asyncio.DatagramProtocol):
    def __init__(self, client: ChildClient) -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr) -> None:
        self.client.on_packet(data, time.monotonic())


def child_snapshot(client: ChildClient, now: float) -> dict:
    st = client.status
    ok = client.connected(now)
    return {
        "connected": ok,
        "rtt_ms": client.rtt_ms if ok else None,
        "loss": client.loss_rate if ok else None,
        "phase": st.phase if st and ok else None,
        "esp_connected": st.connected if st and ok else False,
        "esp_state": (proto.State(st.esp_state).name if st and ok and st.esp_state in proto.State._value2member_map_
                      else None),
        "outputs": list(st.outputs) if st and ok else [],
    }


def build_app(cfg: dict) -> web.Application:
    app = web.Application()
    ctl = cfg.get("control", {})
    parent = ParentMotor(cfg.get("motor", {}).get("serial"))
    child = ChildClient(3, rate_hz=ctl.get("rate_hz", 50))
    core = ControlCore(parent, child, Config(hb_timeout=ctl.get("hb_timeout", 0.3)))
    clients: dict[str, web.WebSocketResponse] = {}
    ids = itertools.count(1)
    tasks: list[asyncio.Task] = []

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=5.0)
        await ws.prepare(request)
        cid = f"c{next(ids)}"
        clients[cid] = ws
        await ws.send_json({"t": "hello", "id": cid, "role": core.role(cid)})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                reply = core.on_message(cid, data, time.monotonic())
                if reply:
                    await ws.send_json(reply)
        finally:
            clients.pop(cid, None)
            core.disconnect(cid)  # 操縦者なら全機停止
        return ws

    async def control_loop() -> None:
        period = 1.0 / ctl.get("rate_hz", 50)
        child_cfg = cfg.get("child", {})
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: ChildUdp(child), local_addr=("0.0.0.0", child_cfg.get("bind_port", 0)),
            family=socket.AF_INET)
        child_addr = (child_cfg.get("host", "127.0.0.1"), child_cfg.get("port", 47100))
        try:
            while True:
                now = time.monotonic()
                core.tick(now)
                pkt = child.step(now)
                if pkt:
                    try:
                        transport.sendto(pkt, child_addr)
                    except OSError:
                        pass
                await asyncio.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            transport.close()

    async def reconnect_loop() -> None:
        # 接続待ち（最大1秒）で制御ループを止めないよう、別タスク・別スレッドで行う
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, parent.maintain, time.monotonic())
            await asyncio.sleep(0.5)

    async def status_loop() -> None:
        period = 1.0 / ctl.get("status_hz", 10)
        while True:
            now = time.monotonic()
            base = {"t": "status", "core": core.snapshot(), "parent": parent.snapshot(),
                    "child": child_snapshot(child, now)}
            for cid, ws in list(clients.items()):
                if not ws.closed:
                    try:
                        await ws.send_json({**base, "role": core.role(cid)})
                    except ConnectionError:
                        pass
            await asyncio.sleep(period)

    async def on_startup(app: web.Application) -> None:
        tasks.extend([asyncio.create_task(control_loop()), asyncio.create_task(status_loop()),
                      asyncio.create_task(reconnect_loop())])

    async def on_cleanup(app: web.Application) -> None:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        parent.close()

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(ROOT / "web" / "index.html")

    app.router.add_get("/ws", ws_handler)
    async def video_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(ROOT / "web" / "video.html")

    app.router.add_get("/", index)
    app.router.add_get("/video", video_page)
    app.router.add_static("/static/", ROOT / "web", show_index=False)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "parent/config/parent.json")
    ap.add_argument("--serial", help="ESP32 のシリアル（設定ファイルより優先。シミュレータの pty など）")
    ap.add_argument("--child", help="子機の HOST:PORT（設定ファイルより優先）")
    ap.add_argument("--port", type=int, help="HTTP ポート（設定ファイルより優先）")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.serial:
        cfg.setdefault("motor", {})["serial"] = args.serial
    if args.child:
        host, port = args.child.rsplit(":", 1)
        cfg.setdefault("child", {}).update(host=host, port=int(port))
    if args.port:
        cfg.setdefault("http", {})["port"] = args.port
    http = cfg.get("http", {})
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(build_app(cfg), host=http.get("host", "0.0.0.0"), port=http.get("port", 8080))
    return 0


if __name__ == "__main__":
    sys.exit(main())
