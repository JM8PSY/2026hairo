import unittest
from dataclasses import dataclass, field

from childlink import ChildClient, ChildController
from childlink import proto as cp
from motorlink.proto import Reason, State, Status


@dataclass
class FakeLink:
    """motorlink.MotorLink の代わり。呼ばれた操作を記録する。"""
    n: int = 3
    phase: str = "disarmed"
    connected: bool = True
    calls: list = field(default_factory=list)
    duties: list = field(default_factory=list)
    state: State = State.DISARMED

    @property
    def status(self):
        return Status(self.state, Reason.NONE, 0, 0, 0, tuple(self.duties or [0] * self.n))

    def arm(self):
        self.calls.append("arm")
        self.phase = "armed"
        self.state = State.ARMED

    def disarm(self):
        self.calls.append("disarm")
        self.phase = "disarmed"
        self.state = State.DISARMED

    def estop(self):
        self.calls.append("estop")
        self.phase = "disarmed"
        self.state = State.ESTOP

    def clear(self):
        self.calls.append("clear")
        self.phase = "disarmed"
        self.state = State.DISARMED

    def set_duties(self, d):
        self.duties = list(d)


def drive(session, seq, duties=(0, 0, 0), estop=False, arm=0, clear=0, t=0):
    return cp.encode_drive(session, seq, t, cp.Drive(estop, arm, clear, tuple(duties)))


class ProtoTest(unittest.TestCase):
    def test_drive_roundtrip(self):
        hdr, d = cp.decode(drive(7, 42, (100, -5, 0), estop=True, arm=3, clear=250, t=99))
        self.assertEqual((hdr.type, hdr.session, hdr.seq, hdr.time_ms), (cp.T_DRIVE, 7, 42, 99))
        self.assertEqual(d, cp.Drive(True, 3, 250, (100, -5, 0)))

    def test_status_roundtrip(self):
        s = cp.Status(1, 2, 3, 4, 5, 1, 0, 0, "armed", True, (10, -10, 0))
        _, got = cp.decode(cp.encode_status(9, 1, 0, s))
        self.assertEqual(got, s)

    def test_rejects_garbage(self):
        for bad in (b"", b"XX" + bytes(20), drive(1, 1)[:-1]):
            with self.assertRaises(cp.DecodeError):
                cp.decode(bad)

    def test_seq_filter(self):
        f = cp.SeqFilter()
        h = lambda s, q: cp.Header(cp.T_DRIVE, s, q, 0)  # noqa: E731
        self.assertTrue(f.accept(h(1, 10)))
        self.assertFalse(f.accept(h(1, 10)))  # 重複
        self.assertFalse(f.accept(h(1, 9)))   # 古い
        self.assertTrue(f.accept(h(1, 12)))
        self.assertTrue(f.accept(h(2, 1)))    # 送信側が再起動
        self.assertEqual(f.stale, 2)


class ChildControllerTest(unittest.TestCase):
    def setUp(self):
        self.link = FakeLink()
        self.c = ChildController(self.link, 3, timeout=0.3)

    def test_first_packet_does_not_arm(self):
        # 子機起動直後・親機再起動直後は、カウンタが何であっても ARM しない
        self.c.on_packet(drive(1, 1, arm=5), 0.0)
        self.assertEqual(self.link.calls, [])
        self.c.on_packet(drive(2, 1, arm=9), 0.02)
        self.assertEqual(self.link.calls, [])

    def test_arm_once_despite_duplicates_and_loss(self):
        self.c.on_packet(drive(1, 1, arm=0), 0.0)
        # seq 2 が落ちても、seq 3 以降に arm=1 が載っていれば1回だけ ARM する
        for seq in (3, 3, 4, 5):
            self.c.on_packet(drive(1, seq, arm=1), 0.01 * seq)
        self.assertEqual(self.link.calls, ["arm"])

    def test_duties_only_when_armed(self):
        self.c.on_packet(drive(1, 1, (500, 0, 0)), 0.0)
        self.assertEqual(self.link.duties, [])
        self.c.on_packet(drive(1, 2, (0, 0, 0), arm=1), 0.02)
        self.c.on_packet(drive(1, 3, (500, 0, -500), arm=1), 0.04)
        self.assertEqual(self.link.duties, [500, 0, -500])

    def test_timeout_disarms_and_does_not_rearm(self):
        self.c.on_packet(drive(1, 1), 0.0)
        self.c.on_packet(drive(1, 2, arm=1), 0.02)
        self.c.tick(0.30)
        self.assertEqual(self.link.phase, "armed")
        self.c.tick(0.33)
        self.assertEqual(self.link.phase, "disarmed")
        self.assertEqual(self.c.last_stop_reason, "parent_timeout")
        self.c.on_packet(drive(1, 3, (500, 0, 0), arm=1), 0.5)  # 同じカウンタのまま再開
        self.assertEqual(self.link.calls, ["arm", "disarm"])
        self.assertEqual(self.link.phase, "disarmed")

    def test_estop_blocks_arm_until_clear(self):
        self.c.on_packet(drive(1, 1), 0.0)
        self.c.on_packet(drive(1, 2, arm=1), 0.02)
        self.c.on_packet(drive(1, 3, (500, 0, 0), estop=True, arm=2), 0.04)
        self.c.on_packet(drive(1, 4, (500, 0, 0), estop=True, arm=2), 0.06)
        self.assertEqual(self.link.calls, ["arm", "estop"])  # ESTOP は1回、ARM 要求は捨てる
        self.c.on_packet(drive(1, 5, estop=False, arm=2, clear=1), 0.08)
        self.assertEqual(self.link.calls, ["arm", "estop", "clear"])
        self.c.on_packet(drive(1, 6, arm=3, clear=1), 0.10)
        self.assertEqual(self.link.calls[-1], "arm")

    def test_wrong_motor_count_ignored(self):
        self.assertFalse(self.c.on_packet(drive(1, 1, (0, 0)), 0.0))


class ChildClientTest(unittest.TestCase):
    def test_rate_and_estop_zeroes(self):
        cl = ChildClient(3, rate_hz=50)
        cl.set_duties([100, 200, 300])
        self.assertIsNotNone(cl.step(0.0))
        self.assertIsNone(cl.step(0.01))
        cl.set_estop(True)
        _, d = cp.decode(cl.step(0.02))
        self.assertEqual((d.estop, d.duties), (True, (0, 0, 0)))

    def test_rtt_and_loss(self):
        cl = ChildClient(3)
        child = ChildController(FakeLink(), 3)
        sent = 0
        for i in range(20):
            now = i * 0.021
            pkt = cl.step(now)
            sent += 1
            if i % 4 != 0:  # 4つに1つ落とす
                child.on_packet(pkt, now)
            st = cp.encode_status(5, i + 1, 0, child.status())
            cl.on_packet(st, now + 0.003)
        self.assertAlmostEqual(cl.rtt_ms, 3, delta=1)
        self.assertAlmostEqual(cl.loss_rate, 0.25, delta=0.06)
        self.assertTrue(cl.connected(0.4))
        self.assertFalse(cl.connected(2.0))


if __name__ == "__main__":
    unittest.main()
