"""ESP32 シミュレータ（firmware/motor_esp32/test_host/build/motor_sim）を相手にした結合テスト。
C++ 側と Python 側のプロトコル実装が噛み合っていることもここで確かめる。"""
import os
import subprocess
import time
import unittest
from pathlib import Path

from motorlink import BoardMismatch, LinkError, MotorLink, Phase, proto

SIM = Path(__file__).resolve().parents[2] / "firmware/motor_esp32/test_host/build/motor_sim"


def wait_for(cond, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@unittest.skipUnless(SIM.exists(), "motor_sim が未ビルド（make test-fw を先に実行）")
class LinkSimTest(unittest.TestCase):
    def start_sim(self, board="child"):
        self.sim = subprocess.Popen([str(SIM), board], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_sim)
        return self.sim.stdout.readline().strip()

    def stop_sim(self):
        if self.sim.poll() is None:
            self.sim.kill()
        self.sim.wait()
        self.sim.stdin.close()
        self.sim.stdout.close()

    def sim_cmd(self, line):
        self.sim.stdin.write(line + "\n")
        self.sim.stdin.flush()

    def open_link(self, port, board=proto.BOARD_ID_CHILD):
        link = MotorLink(port, board)
        info = link.open()
        self.addCleanup(link.close)
        return link, info

    def test_info_and_board_check(self):
        port = self.start_sim("child")
        link, info = self.open_link(port)
        self.assertEqual((info.board_id, info.n_motors), (proto.BOARD_ID_CHILD, 3))
        with self.assertRaises(LinkError):  # 二重 open は拒否
            link.open()
        link.close()
        with self.assertRaises(BoardMismatch):
            MotorLink(port, proto.BOARD_ID_PARENT).open()

    def test_no_motion_until_armed(self):
        link, _ = self.open_link(self.start_sim())
        link.set_duties([500, 0, 0])
        time.sleep(0.2)
        self.assertEqual(link.status.state, proto.State.DISARMED)
        self.assertEqual(link.status.outputs, (0, 0, 0))

    def test_arm_drive_and_cmd_timeout(self):
        link, _ = self.open_link(self.start_sim())
        link.arm()
        self.assertTrue(wait_for(lambda: link.phase is Phase.ARMED))
        # 加速制限 2000/s なので 300 までは 0.15 秒ほど
        self.assertTrue(wait_for(lambda: (link.set_duties([300, 0, -300]) or
                                          link.status.outputs == (300, 0, -300)), 1.0))
        # 上位からの指令が止まったら 0.3 秒で自動的に全0（ARM は維持）
        self.assertTrue(wait_for(lambda: link.status.outputs == (0, 0, 0), 1.0))
        self.assertEqual(link.phase, Phase.ARMED)
        self.assertEqual(link.status.state, proto.State.ARMED)

    def test_estop_and_clear(self):
        link, _ = self.open_link(self.start_sim())
        link.arm()
        self.assertTrue(wait_for(lambda: link.phase is Phase.ARMED))
        link.estop()
        self.assertTrue(wait_for(lambda: link.status.state == proto.State.ESTOP))
        self.assertEqual(link.phase, Phase.DISARMED)
        link.clear()
        self.assertTrue(wait_for(lambda: link.status.state == proto.State.DISARMED))
        link.set_duties([500, 0, 0])
        time.sleep(0.2)
        self.assertEqual(link.status.outputs, (0, 0, 0))

    def test_esp32_fault_disarms_without_rearm(self):
        link, _ = self.open_link(self.start_sim())
        link.arm()
        self.assertTrue(wait_for(lambda: link.phase is Phase.ARMED))
        self.sim_cmd("fault")
        self.assertTrue(wait_for(lambda: link.phase is Phase.DISARMED))
        self.assertEqual(link.last_disarm_reason, "esp32:fault")
        link.clear()
        self.assertTrue(wait_for(lambda: link.status.state == proto.State.DISARMED))
        time.sleep(0.2)
        self.assertEqual(link.status.state, proto.State.DISARMED)  # 勝手に再ARMしない

    def test_limit_reported(self):
        link, _ = self.open_link(self.start_sim("parent"), proto.BOARD_ID_PARENT)
        self.sim_cmd("limit 2")
        self.assertTrue(wait_for(lambda: link.status.limits == 2))

    def test_link_lost(self):
        link, _ = self.open_link(self.start_sim())
        link.arm()
        self.assertTrue(wait_for(lambda: link.phase is Phase.ARMED))
        self.sim.kill()
        self.assertTrue(wait_for(lambda: not link.connected, 1.5))
        self.assertTrue(wait_for(lambda: link.phase is Phase.DISARMED, 1.5))


if __name__ == "__main__":
    unittest.main()
