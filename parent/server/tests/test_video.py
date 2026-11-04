# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""映像サーバーの結合テスト（偽カメラ相手）。aiohttp が無い環境ではスキップ。"""
import asyncio
import sys
import unittest
from pathlib import Path

try:
    from aiohttp import WSMsgType, web
    from aiohttp.test_utils import TestClient, TestServer
    import video as server
except ImportError:  # aiohttp 無し
    server = None

FAKE = str(Path(__file__).resolve().parent / "fake_camera.py")


@unittest.skipUnless(server is not None, "aiohttp が無い")
class VideoTest(unittest.IsolatedAsyncioTestCase):
    async def start(self, argv=("100",), **cfg):
        conf = {"default_fps": 15, "fps_options": [5, 15, 30], "idle_s": 0.2, "restart_s": 0.1,
                "cameras": {"1": {"label": "A", "command": [sys.executable, FAKE, *argv]}}, **cfg}
        self.app = server.build_app(conf)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.cam = self.app[server.CAMS]["1"]

    async def connect(self, query="cam=1&fps=30"):
        ws = await self.client.ws_connect(f"/ws?{query}")
        hello = await ws.receive_json(timeout=3)
        self.assertEqual(hello["t"], "hello")
        return ws, hello

    async def frame(self, ws):
        while True:
            m = await ws.receive(timeout=3)
            if m.type == WSMsgType.BINARY:
                return m.data

    async def test_frames_are_passed_through_unchanged(self):
        await self.start()
        ws, hello = await self.connect()
        self.assertEqual((hello["cam"], hello["label"], hello["fps"]), ("1", "A", 30))
        data = await self.frame(ws)
        self.assertEqual((data[:2], data[-2:], len(data)), (b"\xff\xd8", b"\xff\xd9", 8))
        await ws.close()

    async def test_unknown_camera_is_rejected(self):
        await self.start()
        r = await self.client.get("/ws?cam=9")
        self.assertEqual(r.status, 404)

    async def test_invalid_fps_falls_back_to_default(self):
        await self.start()
        ws, hello = await self.connect("cam=1&fps=999")
        self.assertEqual(hello["fps"], 15)
        await ws.close()

    async def test_camera_is_shared_and_stops_when_nobody_watches(self):
        await self.start()
        self.assertIsNone(self.cam._task)  # 誰も見ていなければ開かない
        a, _ = await self.connect()
        b, _ = await self.connect()
        await self.frame(a)
        await self.frame(b)
        self.assertEqual(self.cam.starts, 1)
        await a.close()
        await b.close()
        await asyncio.sleep(0.5)
        self.assertIsNone(self.cam._task)

    async def test_quick_reconnect_keeps_camera_open(self):
        await self.start()
        a, _ = await self.connect()
        await self.frame(a)
        await a.close()
        b, _ = await self.connect()
        await self.frame(b)
        self.assertEqual(self.cam.starts, 1)
        await b.close()

    async def test_no_ack_limits_frames_in_flight(self):
        await self.start()
        ws, _ = await self.connect()
        await asyncio.sleep(0.5)  # 確認を返さない遅いブラウザ
        frames = []
        await ws.close()
        while (m := await ws.receive(timeout=1)).type == WSMsgType.BINARY:
            frames.append(m.data)
        self.assertLessEqual(len(frames), server.MAX_IN_FLIGHT)

    async def test_frames_after_ack_are_recent(self):
        await self.start()
        ws, _ = await self.connect()
        first = await self.frame(ws)
        await self.frame(ws)
        await asyncio.sleep(0.5)  # この間のフレームは捨てられる
        await ws.send_json({"t": "ack"})
        await ws.send_json({"t": "ack"})
        newer = await self.frame(ws)
        gap = int.from_bytes(newer[2:6], "big") - int.from_bytes(first[2:6], "big")
        self.assertGreater(gap, 10)
        await ws.close()

    async def test_fps_can_be_changed(self):
        await self.start()
        ws, _ = await self.connect()
        await ws.send_json({"t": "fps", "fps": 5})
        while True:
            m = await ws.receive(timeout=3)
            if m.type == WSMsgType.TEXT:
                self.assertEqual(m.json(), {"t": "fps", "fps": 5})
                break
            await ws.send_json({"t": "ack"})
        await ws.close()

    async def test_camera_process_is_restarted(self):
        await self.start(argv=("100", "3"))
        ws, _ = await self.connect()
        for _ in range(3):
            await self.frame(ws)
            await ws.send_json({"t": "ack"})
        for _ in range(100):
            if self.cam.starts >= 2:
                break
            await asyncio.sleep(0.05)
        self.assertGreaterEqual(self.cam.starts, 2)
        await ws.close()

    async def test_missing_command_does_not_crash(self):
        await self.start()
        self.cam.command = ["/nonexistent/camera"]
        ws, _ = await self.connect()
        await asyncio.sleep(0.3)
        self.assertGreaterEqual(self.cam.starts, 2)
        self.assertFalse(ws.closed)
        await ws.close()

    async def test_vr_page_and_scripts_are_served(self):
        await self.start()
        r = await self.client.get("/vr")
        self.assertEqual(r.status, 200)
        self.assertIn("VRで見る", await r.text())
        self.assertEqual((await self.client.get("/static/vr.js")).status, 200)

    async def test_estop_is_relayed_to_control_server(self):
        received = []

        async def control_ws(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"t": "hello"})
            received.append(await ws.receive_json(timeout=2))
            await ws.close()
            return ws

        control = web.Application()
        control.router.add_get("/ws", control_ws)
        control_client = TestClient(TestServer(control))
        await control_client.start_server()
        self.addAsyncCleanup(control_client.close)
        await self.start(control_ws=str(control_client.make_url("/ws")))
        r = await self.client.post("/estop")
        self.assertEqual((r.status, await r.json()), (200, {"ok": True}))
        self.assertEqual(received, [{"t": "estop"}])

    async def test_estop_reports_failure_when_control_server_is_down(self):
        await self.start(control_ws="ws://127.0.0.1:9/ws")
        r = await self.client.post("/estop")
        self.assertEqual(r.status, 502)
        self.assertFalse((await r.json())["ok"])

    async def test_tls_context_needs_certificate(self):
        self.assertIsNone(server.tls_context({}))
        self.assertIsNone(server.tls_context({"tls": {"cert": "no/such.pem", "key": "no/such.pem"}}))
