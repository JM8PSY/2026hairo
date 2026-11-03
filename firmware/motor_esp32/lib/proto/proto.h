// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// ホスト ⇔ ESP32 通信プロトコル（CLAUDE.md §4）。Arduino 非依存。
// Python 側 common/motorlink/proto.py と必ず同時に変更すること。
//
// フレーム: 0xAA 0x55 | type | seq | len | payload[len] | CRC16(LE)
// CRC16-CCITT（多項式 0x1021、初期値 0xFFFF）を type から payload 末尾まで計算する。
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace proto {

constexpr uint8_t SYNC0 = 0xAA;
constexpr uint8_t SYNC1 = 0x55;
constexpr uint8_t VERSION = 1;
constexpr size_t MAX_PAYLOAD = 64;
constexpr size_t HEADER_LEN = 5;  // SYNC0 SYNC1 type seq len
constexpr size_t MAX_FRAME = HEADER_LEN + MAX_PAYLOAD + 2;
constexpr int MAX_MOTORS = 9;
constexpr int16_t DUTY_MAX = 1000;  // 千分率

enum Type : uint8_t {
  CMD_SET = 0x01,    // flags(u8) n(u8) duty(i16 LE) x n
  CMD_ESTOP = 0x02,  // payload なし
  CMD_CLEAR = 0x03,  // payload なし
  CMD_PING = 0x04,   // payload なし → INFO を返す
  STATUS = 0x81,     // 下記 StatusPayload
  INFO = 0x82,       // 下記 InfoPayload
};

constexpr uint8_t SET_FLAG_ARM = 0x01;

enum BoardId : uint8_t {
  BOARD_ID_PARENT = 1,
  BOARD_ID_CHILD = 2,
};

// STATUS payload:
//   state(u8) reason(u8) fault(u8) limits(u16) rx_errors(u16) n(u8) out(i16) x n
// INFO payload:
//   proto_version(u8) board_id(u8) n_motors(u8) fw_major(u8) fw_minor(u8) fw_patch(u8)

uint16_t crc16(const uint8_t* data, size_t len, uint16_t crc = 0xFFFF);

// フレームを out に書き出し、書いたバイト数を返す（payload が長すぎれば 0）。
size_t encode(uint8_t type, uint8_t seq, const uint8_t* payload, size_t len,
              uint8_t* out, size_t out_size);

struct Frame {
  uint8_t type;
  uint8_t seq;
  uint8_t len;
  uint8_t payload[MAX_PAYLOAD];
};

// 1バイトずつ入れるとフレームを組み立てる。壊れたフレームは捨てて次の SYNC から再同期する。
class Parser {
 public:
  // フレームが完成したら true を返し、frame() で取り出せる。
  bool feed(uint8_t b);
  const Frame& frame() const { return frame_; }
  uint16_t errors() const { return errors_; }  // CRC 不一致・長さ超過の数（飽和する）

 private:
  enum State : uint8_t { WAIT_SYNC0, WAIT_SYNC1, TYPE, SEQ, LEN, PAYLOAD, CRC_LO, CRC_HI };
  void error();
  State state_ = WAIT_SYNC0;
  Frame frame_{};
  uint8_t pos_ = 0;
  uint8_t crc_lo_ = 0;
  uint16_t errors_ = 0;
};

inline void put_u16(uint8_t* p, uint16_t v) {
  p[0] = static_cast<uint8_t>(v & 0xFF);
  p[1] = static_cast<uint8_t>(v >> 8);
}
inline uint16_t get_u16(const uint8_t* p) {
  return static_cast<uint16_t>(p[0] | (p[1] << 8));
}
inline void put_i16(uint8_t* p, int16_t v) { put_u16(p, static_cast<uint16_t>(v)); }
inline int16_t get_i16(const uint8_t* p) { return static_cast<int16_t>(get_u16(p)); }

}  // namespace proto
