import struct
import unittest

from motorlink import proto


class ProtoTest(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(proto.crc16(b"123456789"), 0x29B1)  # CRC-16/CCITT-FALSE

    def test_set_roundtrip(self):
        data = proto.encode_set(7, [100, -200, 5000], arm=True)
        frames = proto.Parser().feed(data)
        self.assertEqual(len(frames), 1)
        f = frames[0]
        self.assertEqual((f.type, f.seq), (proto.CMD_SET, 7))
        self.assertEqual(f.payload[:2], bytes([proto.SET_FLAG_ARM, 3]))
        self.assertEqual(struct.unpack("<3h", f.payload[2:]), (100, -200, 1000))

    def test_resync_after_garbage_and_bad_crc(self):
        good = proto.encode(proto.CMD_PING, 3)
        bad = bytearray(proto.encode_set(1, [1, 2, 3], arm=False))
        bad[6] ^= 0xFF
        p = proto.Parser()
        frames = p.feed(b"\x00\xaa\x13\xaa" + bytes(bad) + b"\xaa" + good)
        self.assertEqual([(f.type, f.seq) for f in frames], [(proto.CMD_PING, 3)])
        self.assertGreaterEqual(p.errors, 1)

    def test_split_feed(self):
        data = proto.encode(proto.INFO, 1, bytes([1, 2, 3, 0, 1, 0]))
        p = proto.Parser()
        self.assertEqual(p.feed(data[:4]), [])
        frames = p.feed(data[4:])
        info = proto.decode_info(frames[0].payload)
        self.assertEqual((info.board_id, info.n_motors, info.fw_version), (2, 3, (0, 1, 0)))

    def test_decode_status(self):
        payload = bytes([1, 0, 0]) + struct.pack("<HHB3h", 0x2, 5, 3, 10, -20, 0)
        st = proto.decode_status(payload)
        self.assertEqual(st.state, proto.State.ARMED)
        self.assertEqual(st.limits, 2)
        self.assertEqual(st.outputs, (10, -20, 0))
        with self.assertRaises(ValueError):
            proto.decode_status(payload[:-1])


if __name__ == "__main__":
    unittest.main()
