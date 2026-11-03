"""ESP32 シミュレータ ⇔ child_control.py ⇔（UDP）⇔ ChildClient の結合テスト。"""
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from childlink import ChildClient
from childlink.parent import run_forever
from motorlink.proto import State

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "firmware/motor_esp32/test_host/build/motor_sim"
CHILD = ROOT / "child/control/child_control.py"


def wait_for(cond, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@unittest.skipUnless(SIM.exists(), "motor_sim が未ビルド（make test-fw を先に実行）")
class ChildE2ETest(unittest.TestCase):
    def setUp(self):
        self.procs = []
        self.sim = sim = self._spawn([str(SIM), "child"], stdin=subprocess.PIPE)
        serial = sim.stdout.readline().strip()
        self.child = child = self._spawn([sys.executable, str(CHILD), "--serial", serial,
                             "--bind", "127.0.0.1", "--port", "0"])
        port = None
        for _ in range(2):
            line = child.stdout.readline()
            if line.startswith("UDP 待受"):
                port = int(line.rsplit(":", 1)[1])
        self.assertIsNotNone(port, "child_control が起動しない")
        self.child_addr = ("127.0.0.1", port)
        self.client = ChildClient(3)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.addCleanup(self.sock.close)
        self.sending = None
        self.start_sending()
        self.addCleanup(self.stop_sending)

    def _spawn(self, cmd, **kw):
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, **kw)
        self.procs.append(p)

        def cleanup():
            p.kill()
            p.wait()
            for f in (p.stdin, p.stdout):
                if f:
                    f.close()
        self.addCleanup(cleanup)
        return p

    def start_sending(self):
        stop = threading.Event()
        t = threading.Thread(target=run_forever,
                             args=(self.client, self.child_addr, self.sock, stop.is_set), daemon=True)
        t.start()
        self.sending = (stop, t)

    def stop_sending(self):
        if self.sending:
            stop, t = self.sending
            stop.set()
            t.join()
            self.sending = None

    def st(self):
        return self.client.status

    def arm(self):
        self.assertTrue(wait_for(lambda: self.client.connected(time.monotonic())))
        self.client.request_arm()
        self.assertTrue(wait_for(lambda: self.st().phase == "armed"))

    def test_drive_through_udp(self):
        self.arm()
        self.client.set_duties([300, 0, -300])
        self.assertTrue(wait_for(lambda: self.st().outputs == (300, 0, -300)))
        self.assertEqual(self.st().esp_state, State.ARMED)
        self.assertIsNotNone(self.client.rtt_ms)
        self.assertLess(self.client.loss_rate, 0.1)

    def test_parent_silence_stops_child_and_needs_rearm(self):
        self.arm()
        self.client.set_duties([300, 0, 0])
        self.assertTrue(wait_for(lambda: self.st().outputs[0] == 300))
        self.stop_sending()
        time.sleep(0.6)  # 子機の timeout 0.3秒 + ESP32 の反映
        self.start_sending()  # 同じ指令で再開しても動かない
        self.assertTrue(wait_for(lambda: self.st() is not None and
                                 self.client.connected(time.monotonic()) and
                                 self.st().ack_seq > 0 and self.st().phase == "disarmed"))
        time.sleep(0.2)
        self.assertEqual(self.st().outputs, (0, 0, 0))
        self.assertNotEqual(self.st().esp_state, State.ARMED)

    def test_estop_and_clear(self):
        self.arm()
        self.client.set_duties([300, 0, 0])
        self.client.set_estop(True)
        self.assertTrue(wait_for(lambda: self.st().esp_state == State.ESTOP))
        self.client.request_arm()  # ESTOP 中の ARM 要求は無視される
        time.sleep(0.2)
        self.assertEqual(self.st().esp_state, State.ESTOP)
        self.client.set_estop(False)
        self.client.request_clear()
        self.assertTrue(wait_for(lambda: self.st().esp_state == State.DISARMED))
        self.arm()

    def test_child_exits_when_esp32_lost(self):
        # USB が抜けた等。終了して systemd に再起動（再接続）させる
        self.arm()
        self.sim.kill()
        self.assertEqual(self.child.wait(timeout=5), 1)


if __name__ == "__main__":
    unittest.main()
