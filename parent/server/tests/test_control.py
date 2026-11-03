# SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from control import Config, ControlCore


class FakeParent:
    def __init__(self):
        self.calls, self.duties = [], None

    def arm(self): self.calls.append("arm")
    def disarm(self): self.calls.append("disarm")
    def estop(self): self.calls.append("estop")
    def clear(self): self.calls.append("clear")
    def set_duties(self, d): self.duties = list(d)


class FakeChild:
    def __init__(self):
        self.calls, self.duties = [], None
        self.disarm_flag = None

    def request_arm(self): self.calls.append("arm")
    def set_disarm(self, on): self.disarm_flag = on; self.calls.append(f"disarm={on}")
    def set_estop(self, on): self.calls.append(f"estop={on}")
    def request_clear(self): self.calls.append("clear")
    def set_duties(self, d): self.duties = list(d)


def cmd(target="parent", ok=True, lid_confirm=False, **axes):
    key = "parent" if target == "parent" else "child"
    return {"t": "cmd", "ok": ok, "target": target, key: axes, "lid_confirm": lid_confirm}


class ControlCoreTest(unittest.TestCase):
    def setUp(self):
        self.p, self.c = FakeParent(), FakeChild()
        self.core = ControlCore(self.p, self.c, Config(hb_timeout=0.3))
        self.t = 0.0

    def send(self, cid, msg):
        return self.core.on_message(cid, msg, self.t)

    def step(self, msg=None, cid="A", dt=0.02):
        self.t += dt
        if msg is not None:
            self.send(cid, msg)
        self.core.tick(self.t)

    def take_and_arm(self, cid="A"):
        self.assertEqual(self.send(cid, {"t": "take_control"})["role"], "operator")
        self.step(cmd())
        self.send(cid, {"t": "arm"})
        self.step(cmd())  # ニュートラル

    def test_startup_child_disarmed_and_zero(self):
        self.assertTrue(self.c.disarm_flag)
        self.core.tick(0.0)
        self.assertEqual(self.p.duties, [0] * 9)
        self.assertEqual(self.c.duties, [0] * 3)

    def test_single_operator(self):
        self.assertEqual(self.send("A", {"t": "take_control"})["role"], "operator")
        self.assertEqual(self.send("B", {"t": "take_control"})["role"], "viewer")
        self.assertEqual(self.send("B", {"t": "arm"})["error"], "not_operator")
        self.send("B", cmd(left=1.0))  # 閲覧者の cmd は黙って無視
        self.assertEqual(self.p.calls, [])

    def test_drive_mapping(self):
        self.take_and_arm()
        self.step(cmd(left=0.5, right=-0.25, sub_front=1.0, sub_rear=-1.0, reel=0.3))
        self.assertEqual(self.p.duties, [500, -250, 1000, 1000, -1000, -1000, 0, 300, 0])
        self.assertEqual(self.c.duties, [0, 0, 0])

    def test_non_target_gets_zero(self):
        self.take_and_arm()
        self.step(cmd("child", left=0.4, right=0.4, brush=-1))
        self.assertEqual(self.c.duties, [400, 400, -1000])
        self.assertEqual(self.p.duties, [0] * 9)

    def test_needs_neutral_after_arm(self):
        self.send("A", {"t": "take_control"})
        self.step(cmd(left=1.0))
        self.send("A", {"t": "arm"})
        self.step(cmd(left=1.0))
        self.assertEqual(self.p.duties[0], 0)  # 倒したままでは動かない
        self.step(cmd(left=0.02))  # NEUTRAL 未満
        self.step(cmd(left=1.0))
        self.assertEqual(self.p.duties[0], 1000)

    def test_heartbeat_timeout_stops_all(self):
        self.take_and_arm()
        self.step(cmd(left=1.0))
        self.step(None, dt=0.29)
        self.assertEqual(self.p.duties[0], 1000)
        self.step(None, dt=0.02)
        self.assertEqual(self.p.duties[0], 0)
        self.assertEqual(self.core.stop_reason, "heartbeat_timeout")
        self.assertIn("disarm", self.p.calls)
        self.assertTrue(self.c.disarm_flag)
        self.step(cmd(left=1.0))  # cmd が戻っても arm し直すまで動かない
        self.assertEqual(self.p.duties[0], 0)

    def test_client_not_ok_stops(self):
        for why in ("hidden", "blur", "gamepad_disconnected"):
            self.take_and_arm()
            self.step({"t": "cmd", "ok": False, "why": why, "parent": {"left": 1.0}})
            self.assertEqual(self.p.duties[0], 0)
            self.assertEqual(self.core.stop_reason, why)
            self.send("A", {"t": "release_control"})

    def test_disconnect_releases_and_stops(self):
        self.take_and_arm()
        self.step(cmd(left=1.0))
        self.core.disconnect("A")
        self.step(None)
        self.assertEqual(self.p.duties[0], 0)
        self.assertEqual(self.core.stop_reason, "operator_disconnected")
        self.assertEqual(self.send("B", {"t": "take_control"})["role"], "operator")

    def test_viewer_can_estop_only_operator_clears(self):
        self.take_and_arm()
        self.send("B", {"t": "take_control"})
        self.send("B", {"t": "estop"})
        self.assertIn("estop", self.p.calls)
        self.assertIn("estop=True", self.c.calls)
        self.step(cmd(left=1.0))
        self.assertEqual(self.p.duties[0], 0)
        self.assertEqual(self.send("A", {"t": "arm"})["error"], "estop_active")
        self.assertEqual(self.send("B", {"t": "clear"})["error"], "not_operator")
        self.send("A", {"t": "clear"})
        self.assertIn("estop=False", self.c.calls)
        self.assertTrue(self.c.disarm_flag)
        self.step(cmd(left=1.0))
        self.assertEqual(self.p.duties[0], 0)  # clear 後も arm するまで動かない

    def test_lid_close_needs_confirm(self):
        self.take_and_arm()
        self.step(cmd(lid=1.0))
        self.assertEqual(self.p.duties[6], 1000)
        self.step(cmd(lid=-1.0))
        self.assertEqual(self.p.duties[6], 0)
        self.step(cmd(lid=-1.0, lid_confirm=True))
        self.assertEqual(self.p.duties[6], -1000)

    def test_bad_axis_values(self):
        self.take_and_arm()
        self.step(cmd(left="abc", right=float("nan"), sub_front=5.0))
        self.assertEqual(self.p.duties[:4], [0, 0, 1000, 1000])


if __name__ == "__main__":
    unittest.main()
