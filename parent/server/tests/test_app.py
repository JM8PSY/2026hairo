"""Web サーバーの結合テスト（ESP32 シミュレータ相手）。aiohttp が無い環境ではスキップ。
Mac では入っていないので `make test-docker`（Ubuntu 24.04 コンテナ）で回す。"""
import asyncio
import subprocess
import time
import unittest
from pathlib import Path

try:
    from aiohttp.test_utils import TestClient, TestServer
    import app as server
except ImportError:  # aiohttp 無し
    server = None

ROOT = Path(__file__).resolve().parents[3]
SIM = ROOT / "firmware/motor_esp32/test_host/build/motor_sim"


@unittest.skipUnless(server is not None and SIM.exists(), "aiohttp か motor_sim が無い")
class AppTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sim = subprocess.Popen([str(SIM), "parent"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True)
        port = self.sim.stdout.readline().strip()
        cfg = {"motor": {"serial": port},
               "child": {"host": "127.0.0.1", "port": 9, "bind_port": 0},
               "control": {"hb_timeout": 0.3, "rate_hz": 50, "status_hz": 20}}
        self.client = TestClient(TestServer(server.build_app(cfg)))
        await self.client.start_server()
        self.hb_tasks = []

    async def asyncTearDown(self):
        for t in self.hb_tasks:
            t.cancel()
        await self.client.close()
        self.sim.kill()
        self.sim.wait()
        self.sim.stdin.close()
        self.sim.stdout.close()

    async def connect(self):
        ws = await self.client.ws_connect("/ws")
        hello = await ws.receive_json()
        self.assertEqual((hello["t"], hello["role"]), ("hello", "viewer"))
        return ws

    async def recv(self, ws, t, cond=lambda m: True, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            m = await ws.receive_json(timeout=deadline - time.monotonic())
            if m.get("t") == t and cond(m):
                return m
        self.fail(f"{t} が来ない")

    def heartbeat(self, ws, axes):
        async def run():
            while True:
                await ws.send_json({"t": "cmd", "ok": True, "target": "parent", "parent": dict(axes)})
                await asyncio.sleep(0.02)
        self.hb_tasks.append(asyncio.create_task(run()))

    async def take_and_arm(self, ws, axes):
        await ws.send_json({"t": "take_control"})
        self.assertEqual((await self.recv(ws, "role"))["role"], "operator")
        await self.recv(ws, "status", lambda m: m["parent"]["connected"])
        self.heartbeat(ws, axes)
        await ws.send_json({"t": "arm"})
        await self.recv(ws, "status", lambda m: m["parent"]["phase"] == "armed")

    async def test_index(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)

    async def test_drive_and_disconnect_stops(self):
        ws = await self.connect()
        axes = {"left": 0.0}
        await self.take_and_arm(ws, axes)
        axes["left"] = 0.3
        m = await self.recv(ws, "status", lambda m: m["parent"]["outputs"][:1] == [300])
        self.assertEqual(m["role"], "operator")
        self.assertTrue(m["core"]["armed"])

        viewer = await self.connect()
        await viewer.send_json({"t": "take_control"})
        self.assertEqual((await self.recv(viewer, "role"))["role"], "viewer")

        await ws.close()  # 操縦者が切断 → 全機停止
        m = await self.recv(viewer, "status", lambda m: m["core"]["stop_reason"] == "operator_disconnected")
        m = await self.recv(viewer, "status", lambda m: m["parent"]["phase"] == "disarmed"
                            and m["parent"]["outputs"][:1] == [0])
        self.assertFalse(m["core"]["operator"])
        await viewer.close()

    async def test_heartbeat_loss_and_viewer_estop(self):
        ws = await self.connect()
        axes = {"left": 0.0}
        await self.take_and_arm(ws, axes)
        axes["left"] = 0.2
        await self.recv(ws, "status", lambda m: m["parent"]["outputs"][:1] == [200])
        self.hb_tasks.pop().cancel()  # ハートビートが止まる（ブラウザが固まった等）
        m = await self.recv(ws, "status", lambda m: m["core"]["stop_reason"] == "heartbeat_timeout")
        await self.recv(ws, "status", lambda m: m["parent"]["outputs"][:1] == [0])

        viewer = await self.connect()
        await viewer.send_json({"t": "estop"})
        await self.recv(viewer, "status", lambda m: m["parent"]["state"] == "ESTOP")
        await viewer.close()
        await ws.close()


if __name__ == "__main__":
    unittest.main()
