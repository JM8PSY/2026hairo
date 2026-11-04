#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""親機の映像サーバー：カメラの MJPEG を再エンコードせずブラウザへ流す（CLAUDE.md §9）。

  parent/server/video.py [--config parent/config/video.json] [--port PORT]

- GET /ws?cam=1&fps=15 → WebSocket。プロトコルは docs/protocol_video.md
- GET /vr → Meta Quest 用の VR ページ。WebXR は HTTPS が必要なので、証明書があれば HTTPS でも待ち受ける
- POST /estop → 操縦サーバーへ非常停止を中継する（HTTPS のページから HTTP の操縦サーバーへは接続できないため）
- 操縦サーバー（app.py）とは別プロセス。映像が固まっても制御と非常停止に影響しない
- カメラは見ている人がいる間だけ開く。同じカメラを何人で見ても開くのは1回
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import ssl
import sys
import time
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mjpeg import JpegSplitter, Throttle  # noqa: E402

log = logging.getLogger("video")

READ_SIZE = 256 * 1024
# 受信確認を待たずに送るフレーム数の上限。回線やブラウザが遅いときは古いフレームを捨て、遅延をためない
MAX_IN_FLIGHT = 2
CAMS = web.AppKey("cams", dict)


def v4l2_command(device: str, width: int, height: int) -> list[str]:
    return ["v4l2-ctl", "-d", device,
            f"--set-fmt-video=width={width},height={height},pixelformat=MJPG",
            "--stream-mmap=4", "--stream-to=-"]


class Camera:
    """カメラのプロセスを見ている人がいる間だけ動かし、最新のフレームを配る。"""

    def __init__(self, cam_id: str, label: str, command: list[str],
                 restart_s: float = 1.0, idle_s: float = 3.0) -> None:
        self.id = cam_id
        self.label = label
        self.command = command
        self.restart_s = restart_s
        self.idle_s = idle_s  # ページの再読み込みなどで開き直さないための猶予
        self.viewers = 0
        self.seq = 0
        self.frame = b""
        self.starts = 0
        self._new = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._idle: asyncio.TimerHandle | None = None

    def acquire(self) -> None:
        self.viewers += 1
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def release(self) -> None:
        self.viewers -= 1
        if self.viewers == 0:
            self._idle = asyncio.get_running_loop().call_later(self.idle_s, self._stop)

    def _stop(self) -> None:
        self._idle = None
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def close(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def next_frame(self, after: int) -> tuple[int, bytes]:
        while self.seq <= after:
            await self._new.wait()
        return self.seq, self.frame

    def _publish(self, frame: bytes) -> None:
        self.seq += 1
        self.frame = frame
        new, self._new = self._new, asyncio.Event()
        new.set()

    async def _run(self) -> None:
        while True:
            self.starts += 1
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.command, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
            except OSError as e:
                log.warning("camera %s: 起動できません: %s", self.id, e)
            else:
                try:
                    splitter = JpegSplitter()
                    while data := await proc.stdout.read(READ_SIZE):
                        for frame in splitter.feed(data):
                            self._publish(frame)
                    log.warning("camera %s: 停止しました rc=%s", self.id, await proc.wait())
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
            await asyncio.sleep(self.restart_s)


def build_cameras(cfg: dict) -> dict[str, Camera]:
    width, height = cfg.get("width", 2880), cfg.get("height", 1440)
    cams = {}
    for cam_id, c in cfg.get("cameras", {}).items():
        command = c.get("command") or v4l2_command(c["device"], width, height)
        cams[cam_id] = Camera(cam_id, c.get("label", cam_id), command,
                              restart_s=cfg.get("restart_s", 1.0), idle_s=cfg.get("idle_s", 3.0))
    return cams


def build_app(cfg: dict) -> web.Application:
    app = web.Application()
    cams = build_cameras(cfg)
    default_fps = cfg.get("default_fps", 15)
    fps_options = cfg.get("fps_options", [5, 10, 15, 30])
    camera_list = [{"id": c.id, "label": c.label} for c in cams.values()]

    def pick_fps(value: object) -> int:
        try:
            fps = int(value)
        except (TypeError, ValueError):
            return default_fps
        return fps if fps in fps_options else default_fps

    async def ws_handler(request: web.Request) -> web.WebSocketResponse:
        cam = cams.get(request.query.get("cam", ""))
        if cam is None:
            raise web.HTTPNotFound(text="unknown camera")
        ws = web.WebSocketResponse(heartbeat=5.0)
        await ws.prepare(request)
        fps = pick_fps(request.query.get("fps"))
        throttle = Throttle(fps)
        in_flight = 0

        async def sender() -> None:
            nonlocal in_flight
            last = cam.seq  # 接続前の古いフレームは送らない
            while True:
                last, frame = await cam.next_frame(last)
                if in_flight < MAX_IN_FLIGHT and throttle.allow(time.monotonic()):
                    in_flight += 1
                    await ws.send_bytes(frame)

        await ws.send_json({"t": "hello", "cam": cam.id, "label": cam.label, "fps": fps,
                            "fps_options": fps_options, "cameras": camera_list})
        cam.acquire()
        task = asyncio.create_task(sender())
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
                if data.get("t") == "ack":
                    in_flight = max(0, in_flight - 1)
                elif data.get("t") == "fps":
                    fps = pick_fps(data.get("fps"))
                    throttle = Throttle(fps)
                    await ws.send_json({"t": "fps", "fps": fps})
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, ConnectionError):
                pass
            cam.release()
        return ws

    async def vr_page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(ROOT / "web" / "vr.html")

    async def estop(request: web.Request) -> web.Response:
        url = cfg.get("control_ws", "ws://127.0.0.1:8080/ws")
        try:
            async with ClientSession(timeout=ClientTimeout(total=2.0)) as session:
                async with session.ws_connect(url) as ws:
                    await ws.send_json({"t": "estop"})
                    # 閉じる前に操縦サーバーが処理できるよう、最初の応答を待つ
                    await ws.receive(timeout=1.0)
        except (ClientError, OSError, asyncio.TimeoutError) as e:
            log.error("非常停止を中継できません: %s", e)
            return web.json_response({"ok": False, "error": "操縦サーバーに接続できません"}, status=502)
        return web.json_response({"ok": True})

    async def on_cleanup(app: web.Application) -> None:
        for cam in cams.values():
            await cam.close()

    app[CAMS] = cams
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/vr", vr_page)
    app.router.add_post("/estop", estop)
    app.router.add_static("/static/", ROOT / "web", show_index=False)
    app.on_cleanup.append(on_cleanup)
    return app


def tls_context(cfg: dict) -> ssl.SSLContext | None:
    """証明書があれば HTTPS 用の設定を返す。無ければ HTTP だけで動く（VR は使えない）。"""
    tls = cfg.get("tls")
    if not tls:
        return None
    cert, key = ROOT / tls["cert"], ROOT / tls["key"]
    if not (cert.exists() and key.exists()):
        log.warning("証明書が無いので HTTPS を使いません（VR に必要。tools/make_tls_cert.sh で作れます）")
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


async def serve(cfg: dict, port: int | None) -> None:
    http = cfg.get("http", {})
    host = http.get("host", "0.0.0.0")
    runner = web.AppRunner(build_app(cfg), handle_signals=True)
    await runner.setup()
    try:
        await web.TCPSite(runner, host, port or http.get("port", 8081)).start()
        context = tls_context(cfg)
        if context is not None:
            await web.TCPSite(runner, host, cfg["tls"].get("port", 8443), ssl_context=context).start()
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "parent/config/video.json")
    ap.add_argument("--port", type=int, help="HTTP ポート（設定ファイルより優先）")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(cfg, args.port))
    except (KeyboardInterrupt, web.GracefulExit):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
