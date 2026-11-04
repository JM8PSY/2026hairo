# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""ゲートウェイの結合テスト（偽の ROS 相手）。aiohttp が無い環境ではスキップ。"""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path

try:
    from aiohttp.test_utils import TestClient, TestServer
    import gateway as server
except ImportError:  # aiohttp 無し
    server = None

MAP = {"seq": 1, "w": 2, "h": 1, "res": 0.05, "ox": 0.0, "oy": 0.0, "cells": bytes([255, 100])}
SCAN = {"seq": 1, "frame": "laser_frame", "angle_min": -3.14, "angle_inc": 0.01, "ranges": [100, 0]}
POSE = {"x": 1.0, "y": 2.0, "yaw": 0.5}


class FakeBackend:
    available = True

    def __init__(self):
        self.map = MAP
        self.scan = SCAN
        self.pose = POSE
        self.laser_pose = POSE
        self.hz = 12.0
        self.calls = []
        self.fail = None
        self.closed = False

    def scan_hz(self):
        return self.hz

    def driver_running(self):
        return True

    def slam_running(self):
        return True

    def close(self):
        self.closed = True

    async def _op(self, *call):
        self.calls.append(call)
        if self.fail:
            raise RuntimeError(self.fail)

    async def set_lidar(self, on):
        await self._op("lidar", on)
        self.hz = 12.0 if on else 0.0

    async def reset_map(self):
        await self._op("reset")
        self.map = None

    async def serialize_map(self, path):
        await self._op("serialize", path)


@unittest.skipUnless(server is not None, "aiohttp が無い")
class GatewayTest(unittest.IsolatedAsyncioTestCase):
    async def start(self, backend=None, **cfg):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = backend or FakeBackend()
        conf = {"map_hz": 100, "scan_hz": 100, "map_dir": self.tmp.name, **cfg}
        self.client = TestClient(TestServer(server.build_app(conf, backend=self.backend)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.ws = await self.client.ws_connect("/ws", max_msg_size=0)

    async def recv(self, t, cond=lambda m: True):
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            m = await self.ws.receive_json(timeout=deadline - time.monotonic())
            if m.get("t") == t and cond(m):
                return m
        self.fail(f"{t} が来ない")

    async def test_streams_map_pose_scan_and_sensors(self):
        await self.start()
        self.assertEqual((await self.recv("map"))["w"], 2)
        self.assertEqual((await self.recv("pose"))["pose"], POSE)
        scan = await self.recv("scan")
        self.assertEqual((scan["ranges"], scan["laser"]), ([100, 0], POSE))
        s = await self.recv("sensors")
        self.assertEqual((s["ros"], s["slam"], s["lidar"]["wanted"], s["d455"]["state"]),
                         (True, True, True, "unsupported"))

    async def test_same_map_is_not_resent(self):
        await self.start()
        await self.recv("map")
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            m = await self.ws.receive_json(timeout=1)
            self.assertNotEqual(m["t"], "map")

    async def test_lidar_off_and_on(self):
        await self.start()
        await self.ws.send_json({"t": "lidar", "on": False})
        self.assertTrue((await self.recv("result"))["ok"])
        self.assertEqual(self.backend.calls[-1], ("lidar", False))
        s = await self.recv("sensors", lambda m: not m["lidar"]["wanted"])
        self.assertEqual(s["lidar"]["scan_hz"], 0.0)
        await self.ws.send_json({"t": "lidar", "on": True})
        await self.recv("result")
        await self.recv("sensors", lambda m: m["lidar"]["wanted"])

    async def test_lidar_is_stopped_again_if_driver_restarts(self):
        await self.start()
        await self.ws.send_json({"t": "lidar", "on": False})
        await self.recv("result")
        n = len(self.backend.calls)
        self.backend.hz = 12.0  # ドライバが再起動してスキャンを始めた
        await asyncio.sleep(1.2)
        self.assertEqual(self.backend.calls[n:], [("lidar", False)])

    async def test_default_off_from_config(self):
        await self.start(lidar_default_on=False)
        await asyncio.sleep(0.1)
        self.assertEqual(self.backend.calls[0], ("lidar", False))

    async def test_failed_service_is_reported_and_state_kept(self):
        await self.start()
        self.backend.fail = "サービスがありません"
        await self.ws.send_json({"t": "lidar", "on": False})
        r = await self.recv("result")
        self.assertEqual((r["ok"], r["error"]), (False, "サービスがありません"))
        s = await self.recv("sensors")
        self.assertTrue(s["lidar"]["wanted"])

    async def test_save_writes_files_and_serializes(self):
        await self.start()
        await self.ws.send_json({"t": "map_save"})
        r = await self.recv("result")
        self.assertTrue(r["ok"], r)
        self.assertTrue(Path(r["path"]).exists())
        self.assertTrue(Path(r["path"]).with_suffix(".pgm").exists())
        self.assertEqual(self.backend.calls[-1][0], "serialize")

    async def test_save_without_map_fails(self):
        await self.start()
        self.backend.map = None
        await self.ws.send_json({"t": "map_save"})
        self.assertFalse((await self.recv("result"))["ok"])

    async def test_reset_clears_map_on_browsers(self):
        await self.start()
        await self.recv("map")
        await self.ws.send_json({"t": "map_reset"})
        self.assertTrue((await self.recv("result"))["ok"])
        await self.recv("map_clear")

    async def test_without_ros(self):
        await self.start(backend=server.NoRos())
        s = await self.recv("sensors")
        self.assertEqual((s["ros"], s["slam"], s["lidar"]["driver"]), (False, False, False))
        await self.ws.send_json({"t": "map_reset"})
        r = await self.recv("result")
        self.assertEqual((r["ok"], r["error"]), (False, "ROS 未接続です"))
