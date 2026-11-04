# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

"""ROS 2 側（rclpy）。別スレッドで spin し、最新の値を属性に置く。ゲートウェイはそれを読むだけ。
属性は丸ごと差し替えるだけなのでロックは使わない。rclpy が import できない環境では使えない。"""
from __future__ import annotations

import asyncio
import threading
import time

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from slam_toolbox.srv import Reset, SerializePoseGraph
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener

from map_core import encode_ranges, quaternion_yaw

SERVICE_TIMEOUT_S = 15.0
SCAN_WINDOW_S = 2.0


class BackendError(Exception):
    pass


class RosBackend:
    available = True

    def __init__(self) -> None:
        rclpy.init()
        self.node = rclpy.create_node("web_gateway")
        self.map: dict | None = None
        self.scan: dict | None = None
        self.pose: dict | None = None
        self._map_seq = 0
        self._scan_seq = 0
        self._scan_times: list[float] = []
        self._tf = Buffer()
        self._tf_listener = TransformListener(self._tf, self.node)
        map_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.node.create_subscription(OccupancyGrid, "/map", self._on_map, map_qos)
        self.node.create_subscription(LaserScan, "/scan", self._on_scan, qos_profile_sensor_data)
        self.node.create_timer(0.1, self._on_timer)
        self._stop_scan = self.node.create_client(Empty, "/stop_scan")
        self._start_scan = self.node.create_client(Empty, "/start_scan")
        self._reset = self.node.create_client(Reset, "/slam_toolbox/reset")
        self._serialize = self.node.create_client(SerializePoseGraph, "/slam_toolbox/serialize_map")
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self.node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._executor.shutdown()
        self.node.destroy_node()
        rclpy.try_shutdown()
        self._thread.join(timeout=2.0)

    # ---- 購読（spin スレッド） ----

    def _on_map(self, msg: OccupancyGrid) -> None:
        self._map_seq += 1
        o = msg.info.origin.position
        self.map = {"seq": self._map_seq, "w": msg.info.width, "h": msg.info.height,
                    "res": msg.info.resolution, "ox": o.x, "oy": o.y, "cells": msg.data.tobytes()}

    def _on_scan(self, msg: LaserScan) -> None:
        now = time.monotonic()
        self._scan_times = [t for t in self._scan_times if now - t <= SCAN_WINDOW_S] + [now]
        self._scan_seq += 1
        self.scan = {"seq": self._scan_seq, "frame": msg.header.frame_id, "angle_min": msg.angle_min,
                     "angle_inc": msg.angle_increment,
                     "ranges": encode_ranges(msg.ranges, msg.range_min, msg.range_max)}

    def _lookup(self, child: str) -> dict | None:
        try:
            t = self._tf.lookup_transform("map", child, rclpy.time.Time()).transform
        except Exception:  # tf2 の例外は種類が多い。地図がまだ無いときなど
            return None
        r = t.rotation
        return {"x": t.translation.x, "y": t.translation.y, "yaw": quaternion_yaw(r.x, r.y, r.z, r.w)}

    def _on_timer(self) -> None:
        self.pose = self._lookup("base_link")
        scan = self.scan
        if scan is not None:
            self.laser_pose = self._lookup(scan["frame"])

    laser_pose: dict | None = None

    # ---- 状態 ----

    def scan_hz(self) -> float:
        now = time.monotonic()
        return sum(1 for t in self._scan_times if now - t <= SCAN_WINDOW_S) / SCAN_WINDOW_S

    def driver_running(self) -> bool:
        return self.node.count_publishers("/scan") > 0

    def slam_running(self) -> bool:
        return self.node.count_publishers("/map") > 0

    # ---- サービス ----

    async def _call(self, client, request):
        if not client.service_is_ready():
            raise BackendError(f"サービス {client.srv_name} がありません")
        loop = asyncio.get_running_loop()
        done: asyncio.Future = loop.create_future()

        def finish(future) -> None:
            def deliver() -> None:
                if not done.done():
                    done.set_result(future.result())
            loop.call_soon_threadsafe(deliver)

        client.call_async(request).add_done_callback(finish)
        try:
            return await asyncio.wait_for(done, SERVICE_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise BackendError(f"サービス {client.srv_name} が応答しません") from None

    async def set_lidar(self, on: bool) -> None:
        await self._call(self._start_scan if on else self._stop_scan, Empty.Request())

    async def reset_map(self) -> None:
        response = await self._call(self._reset, Reset.Request())
        if response.result != Reset.Response.RESULT_SUCCESS:
            raise BackendError(f"地図のリセットに失敗しました（{response.result}）")
        self.map = None

    async def serialize_map(self, path: str) -> None:
        request = SerializePoseGraph.Request()
        request.filename = path
        response = await self._call(self._serialize, request)
        if response.result != SerializePoseGraph.Response.RESULT_SUCCESS:
            raise BackendError(f"地図データの保存に失敗しました（{response.result}）")
