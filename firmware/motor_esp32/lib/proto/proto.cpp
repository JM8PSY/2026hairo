#include "proto.h"

namespace proto {

uint16_t crc16(const uint8_t* data, size_t len, uint16_t crc) {
  for (size_t i = 0; i < len; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (int b = 0; b < 8; ++b) {
      crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                           : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

size_t encode(uint8_t type, uint8_t seq, const uint8_t* payload, size_t len,
              uint8_t* out, size_t out_size) {
  if (len > MAX_PAYLOAD || out_size < HEADER_LEN + len + 2) return 0;
  out[0] = SYNC0;
  out[1] = SYNC1;
  out[2] = type;
  out[3] = seq;
  out[4] = static_cast<uint8_t>(len);
  for (size_t i = 0; i < len; ++i) out[HEADER_LEN + i] = payload[i];
  put_u16(out + HEADER_LEN + len, crc16(out + 2, 3 + len));
  return HEADER_LEN + len + 2;
}

void Parser::error() {
  if (errors_ != 0xFFFF) ++errors_;
  state_ = WAIT_SYNC0;
}

bool Parser::feed(uint8_t b) {
  switch (state_) {
    case WAIT_SYNC0:
      if (b == SYNC0) state_ = WAIT_SYNC1;
      return false;
    case WAIT_SYNC1:
      // 0xAA 0xAA 0x55 のような並びでも同期を取り直せるようにする
      state_ = (b == SYNC1) ? TYPE : (b == SYNC0 ? WAIT_SYNC1 : WAIT_SYNC0);
      return false;
    case TYPE:
      frame_.type = b;
      state_ = SEQ;
      return false;
    case SEQ:
      frame_.seq = b;
      state_ = LEN;
      return false;
    case LEN:
      if (b > MAX_PAYLOAD) {
        error();
        return false;
      }
      frame_.len = b;
      pos_ = 0;
      state_ = (b == 0) ? CRC_LO : PAYLOAD;
      return false;
    case PAYLOAD:
      frame_.payload[pos_++] = b;
      if (pos_ == frame_.len) state_ = CRC_LO;
      return false;
    case CRC_LO:
      crc_lo_ = b;
      state_ = CRC_HI;
      return false;
    case CRC_HI: {
      uint8_t hdr[3] = {frame_.type, frame_.seq, frame_.len};
      uint16_t crc = crc16(hdr, 3);
      crc = crc16(frame_.payload, frame_.len, crc);
      uint16_t got = static_cast<uint16_t>(crc_lo_ | (b << 8));
      if (crc != got) {
        error();
        return false;
      }
      state_ = WAIT_SYNC0;
      return true;
    }
  }
  return false;
}

}  // namespace proto
