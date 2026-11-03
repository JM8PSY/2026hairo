"""tools/motor_test.py をシミュレータ相手に動かす。"""
import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "firmware/motor_esp32/test_host/build/motor_sim"

spec = importlib.util.spec_from_file_location("motor_test", ROOT / "tools/motor_test.py")
motor_test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motor_test)


@unittest.skipUnless(SIM.exists(), "motor_sim が未ビルド（make test-fw を先に実行）")
class MotorTestToolTest(unittest.TestCase):
    def setUp(self):
        self.sim = subprocess.Popen([str(SIM), "child"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True)
        self.port = self.sim.stdout.readline().strip()

    def tearDown(self):
        self.sim.kill()
        self.sim.wait()
        self.sim.stdin.close()
        self.sim.stdout.close()

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = motor_test.main(["--port", self.port, "--board", "child", *argv])
        return rc, out.getvalue(), err.getvalue()

    def test_spin_reaches_duty_then_stops(self):
        rc, out, _ = self.run_tool("spin", "c2", "--duty", "-250", "--seconds", "0.5", "--yes")
        self.assertEqual(rc, 0)
        self.assertIn("out=[   +0  -250    +0]", out)
        self.assertTrue(out.rstrip().endswith("停止しました"))

    def test_rejects_high_duty_without_flag(self):
        rc, _, err = self.run_tool("spin", "C1", "--duty", "600", "--yes")
        self.assertEqual(rc, 2)
        self.assertIn("±300", err)

    def test_board_mismatch(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = motor_test.main(["--port", self.port, "--board", "parent", "status", "--seconds", "0.1"])
        self.assertEqual(rc, 1)
        self.assertIn("基板IDが違います", err.getvalue())

    def test_bad_port(self):
        with tempfile.TemporaryDirectory() as d:
            rc = motor_test.main(["--port", f"{d}/none", "--board", "child", "status"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
