// プロトコルと motor_core のホストPC用単体テスト。`make test` で実行する。
#include <cstdio>
#include <cstring>
#include <vector>

#include "board_config.h"
#include "motor_core.h"
#include "proto.h"

using namespace motor_core;

static int g_fail = 0, g_pass = 0;
#define CHECK(cond)                                                    \
  do {                                                                 \
    if (cond) {                                                        \
      ++g_pass;                                                        \
    } else {                                                           \
      ++g_fail;                                                        \
      std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
    }                                                                  \
  } while (0)
#define CHECK_EQ(a, b)                                                           \
  do {                                                                           \
    long _a = (long)(a), _b = (long)(b);                                         \
    if (_a == _b) {                                                              \
      ++g_pass;                                                                  \
    } else {                                                                     \
      ++g_fail;                                                                  \
      std::printf("  FAIL %s:%d: %s == %s (%ld != %ld)\n", __FILE__, __LINE__, #a, \
                  #b, _a, _b);                                                   \
    }                                                                            \
  } while (0)

// ---- ヘルパー ----

static std::vector<uint8_t> frame(uint8_t type, uint8_t seq, const std::vector<uint8_t>& p) {
  std::vector<uint8_t> out(proto::MAX_FRAME);
  size_t n = proto::encode(type, seq, p.data(), p.size(), out.data(), out.size());
  out.resize(n);
  return out;
}

static std::vector<uint8_t> set_payload(bool arm, const std::vector<int16_t>& duty) {
  std::vector<uint8_t> p(2 + 2 * duty.size());
  p[0] = arm ? proto::SET_FLAG_ARM : 0;
  p[1] = static_cast<uint8_t>(duty.size());
  for (size_t i = 0; i < duty.size(); ++i) proto::put_i16(&p[2 + 2 * i], duty[i]);
  return p;
}

static proto::Frame parse_one(const std::vector<uint8_t>& bytes) {
  proto::Parser ps;
  for (uint8_t b : bytes)
    if (ps.feed(b)) return ps.frame();
  proto::Frame f{};
  f.type = 0xFF;
  return f;
}

struct Rig {
  Controller c;
  uint32_t t = 0;
  uint8_t reply[proto::MAX_FRAME];
  explicit Rig(const BoardConfig& cfg) : c(cfg) { c.tick(t, 0); }
  size_t send(uint8_t type, const std::vector<uint8_t>& p = {}) {
    return c.on_frame(parse_one(frame(type, 0, p)), t, reply, sizeof(reply));
  }
  void set(bool arm, const std::vector<int16_t>& d) { send(proto::CMD_SET, set_payload(arm, d)); }
  // dt ミリ秒ずつ進めながら、毎周期同じ指令を送る（ホストが 50Hz で送り続ける状況）
  void run(uint32_t ms, const std::vector<int16_t>& d, uint16_t limits = 0, uint32_t dt = 20) {
    for (uint32_t e = 0; e < ms; e += dt) {
      t += dt;
      set(true, d);
      c.tick(t, limits);
    }
  }
  void idle(uint32_t ms, uint16_t limits = 0, uint32_t dt = 10) {
    for (uint32_t e = 0; e < ms; e += dt) {
      t += dt;
      c.tick(t, limits);
    }
  }
};

static const std::vector<int16_t> Z3 = {0, 0, 0};

// テスト用の設定：加速制限なしのモーター、加速制限ありのモーター、リミットと時間制限付きのモーター
static const MotorConfig kTestMotors[3] = {
    {true, 1000, 0, NO_LIMIT, NO_LIMIT, 0},
    {true, 500, 1000, NO_LIMIT, NO_LIMIT, 0},
    {true, 600, 0, 0, 1, 1000},
};
static const BoardConfig kTest = {proto::BOARD_ID_CHILD, 3, kTestMotors, 0, 1, 0};

// ---- proto ----

static void test_crc() {
  const uint8_t s[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
  CHECK_EQ(proto::crc16(s, sizeof(s)), 0x29B1);  // CRC-16/CCITT-FALSE の検査値
}

static void test_roundtrip() {
  auto bytes = frame(proto::CMD_SET, 7, set_payload(true, {100, -200, 1000}));
  CHECK_EQ(bytes.size(), 5 + 8 + 2);
  proto::Frame f = parse_one(bytes);
  CHECK_EQ(f.type, proto::CMD_SET);
  CHECK_EQ(f.seq, 7);
  CHECK_EQ(f.len, 8);
  CHECK_EQ(proto::get_i16(f.payload + 4), -200);
}

static void test_resync() {
  proto::Parser ps;
  auto good = frame(proto::CMD_PING, 3, {});
  auto bad = frame(proto::CMD_SET, 1, set_payload(false, {1, 2, 3}));
  bad[6] ^= 0xFF;  // payload を壊す → CRC 不一致
  std::vector<uint8_t> stream = {0x00, 0xAA, 0x13, 0xAA};  // ゴミと偽 SYNC
  stream.insert(stream.end(), bad.begin(), bad.end());
  stream.push_back(0xAA);  // SYNC0 の重複
  stream.insert(stream.end(), good.begin(), good.end());
  int got = 0;
  for (uint8_t b : stream)
    if (ps.feed(b)) {
      ++got;
      CHECK_EQ(ps.frame().type, proto::CMD_PING);
      CHECK_EQ(ps.frame().seq, 3);
    }
  CHECK_EQ(got, 1);
  CHECK(ps.errors() >= 1);
}

static void test_len_too_long() {
  proto::Parser ps;
  const uint8_t hdr[] = {0xAA, 0x55, 0x01, 0x00, 0xFF};
  for (uint8_t b : hdr) ps.feed(b);
  CHECK_EQ(ps.errors(), 1);
  uint8_t out[8];
  CHECK_EQ(proto::encode(0x01, 0, hdr, 100, out, sizeof(out)), 0);
}

// ---- motor_core ----

static void test_boot_disarmed() {
  Rig r(kTest);
  CHECK_EQ(r.c.state(), DISARMED);
  CHECK_EQ(r.c.reason(), REASON_BOOT);
  CHECK(!r.c.output_enabled());
  // ARM フラグなしの指令では動かない
  r.set(false, {500, 0, 0});
  r.idle(20);
  CHECK_EQ(r.c.output(0), 0);
}

static void test_arm_requires_all_zero() {
  Rig r(kTest);
  r.set(true, {300, 0, 0});  // 非ゼロでの ARM は拒否
  CHECK_EQ(r.c.state(), DISARMED);
  r.set(true, Z3);
  CHECK_EQ(r.c.state(), ARMED);
  CHECK(r.c.output_enabled());
  r.run(20, {300, 0, 0});
  CHECK_EQ(r.c.output(0), 300);
}

static void test_wrong_motor_count_ignored() {
  Rig r(kTest);
  r.set(true, {0, 0});  // 3モーターの基板に2個分
  CHECK_EQ(r.c.state(), DISARMED);
}

static void test_watchdog() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(100, {500, 0, 0});
  CHECK_EQ(r.c.state(), ARMED);
  r.idle(200);  // ちょうど 200ms はまだ ARMED
  CHECK_EQ(r.c.state(), ARMED);
  r.idle(10);
  CHECK_EQ(r.c.state(), DISARMED);
  CHECK_EQ(r.c.reason(), REASON_WATCHDOG);
  CHECK_EQ(r.c.output(0), 0);
  // 指令が再開しても非ゼロのままでは再 ARM しない
  r.run(100, {500, 0, 0});
  CHECK_EQ(r.c.state(), DISARMED);
  CHECK_EQ(r.c.output(0), 0);
}

static void test_host_disarm() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(40, {500, 0, 0});
  r.set(false, {500, 0, 0});
  CHECK_EQ(r.c.state(), DISARMED);
  CHECK_EQ(r.c.reason(), REASON_HOST);
  r.idle(10);
  CHECK_EQ(r.c.output(0), 0);
}

static void test_estop_latch() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(40, {500, 0, 0});
  r.send(proto::CMD_ESTOP);
  CHECK_EQ(r.c.state(), ESTOP);
  CHECK_EQ(r.c.output(0), 0);
  r.set(true, Z3);  // ESTOP 中は ARM できない
  CHECK_EQ(r.c.state(), ESTOP);
  r.send(proto::CMD_CLEAR);
  CHECK_EQ(r.c.state(), DISARMED);  // CLEAR 後もすぐには動かない
  CHECK_EQ(r.c.reason(), REASON_CLEAR);
  CHECK(!r.c.take_reinit_request());
  r.set(true, Z3);
  CHECK_EQ(r.c.state(), ARMED);
}

static void test_fault() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(40, {500, 0, 0});
  r.c.set_fault(FAULT_I2C);
  CHECK_EQ(r.c.state(), FAULT);
  CHECK_EQ(r.c.fault(), FAULT_I2C);
  CHECK(!r.c.output_enabled());
  r.send(proto::CMD_ESTOP);  // FAULT は ESTOP で上書きしない
  CHECK_EQ(r.c.state(), FAULT);
  r.send(proto::CMD_CLEAR);
  CHECK_EQ(r.c.state(), DISARMED);
  CHECK_EQ(r.c.fault(), 0);
  CHECK(r.c.take_reinit_request());
  CHECK(!r.c.take_reinit_request());
}

static void test_duty_clamp() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(20, {2000, 0, -900});
  CHECK_EQ(r.c.output(0), 1000);  // プロトコル上限
  CHECK_EQ(r.c.output(2), -600);  // モーターごとの上限
}

static void test_accel_limit() {
  Rig r(kTest);
  r.set(true, Z3);
  // motor1: 上限 500、1000/s → 20ms で 20 ずつ
  r.run(20, {0, 500, 0});
  CHECK_EQ(r.c.output(1), 20);
  r.run(200, {0, 500, 0});
  CHECK_EQ(r.c.output(1), 220);
  r.run(1000, {0, 500, 0});
  CHECK_EQ(r.c.output(1), 500);
  // 減速は即時
  r.run(20, {0, 100, 0});
  CHECK_EQ(r.c.output(1), 100);
  // 反転は一度0を通る
  r.run(20, {0, -500, 0});
  CHECK_EQ(r.c.output(1), 0);
  r.run(20, {0, -500, 0});
  CHECK_EQ(r.c.output(1), -20);
}

static void test_accel_fraction() {
  // 1000/s を 7ms 周期で回しても、端数を持ち越して平均どおりに増える
  Rig r(kTest);
  r.set(true, Z3);
  r.run(700, {0, 500, 0}, 0, 7);
  CHECK_EQ(r.c.output(1), 500);  // 700 まで増える分は上限 500 で止まる
  Rig r2(kTest);
  r2.set(true, Z3);
  r2.run(350, {0, 500, 0}, 0, 7);
  CHECK_EQ(r2.c.output(1), 350);
}

static void test_limit_switch() {
  Rig r(kTest);
  r.set(true, Z3);
  const uint16_t FWD = 1 << 0, REV = 1 << 1;
  r.run(20, {0, 0, 400}, FWD);
  CHECK_EQ(r.c.output(2), 0);  // 正転側リミット作動中は正転しない
  r.run(20, {0, 0, -400}, FWD);
  CHECK_EQ(r.c.output(2), -400);  // 逆方向には動かせる
  r.run(20, {0, 0, -400}, REV);
  CHECK_EQ(r.c.output(2), 0);
  // 断線（両方作動）ならどちらにも動かない
  r.run(20, {0, 0, 400}, FWD | REV);
  CHECK_EQ(r.c.output(2), 0);
}

static void test_max_run_time() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(1000, {0, 0, 400});
  CHECK_EQ(r.c.output(2), 400);
  r.run(40, {0, 0, 400});
  CHECK_EQ(r.c.output(2), 0);  // 1000ms 超で停止
  r.run(500, {0, 0, -400});    // 向きを変えても一度0に戻すまでは止まったまま
  CHECK_EQ(r.c.output(2), 0);
  r.run(20, Z3);
  r.run(20, {0, 0, -400});
  CHECK_EQ(r.c.output(2), -400);
}

static void test_disabled_motor() {
  Rig r(board::kParent);
  std::vector<int16_t> z(9, 0), d(9, 0);
  r.set(true, z);
  d[8] = 500;  // P9
  d[7] = 1000; // P8 リール（上限 400）
  r.run(2000, d);
  CHECK_EQ(r.c.output(8), 0);
  CHECK_EQ(r.c.output(7), 400);
}

static void test_status_info() {
  Rig r(kTest);
  r.set(true, Z3);
  r.run(20, {123, 0, -45}, 0x0002);
  uint8_t buf[proto::MAX_FRAME];
  size_t n = r.c.build_status(9, 4, buf, sizeof(buf));
  proto::Frame f = parse_one(std::vector<uint8_t>(buf, buf + n));
  CHECK_EQ(f.type, proto::STATUS);
  CHECK_EQ(f.seq, 9);
  CHECK_EQ(f.len, 8 + 6);
  CHECK_EQ(f.payload[0], ARMED);
  CHECK_EQ(proto::get_u16(f.payload + 3), 0x0002);
  CHECK_EQ(proto::get_u16(f.payload + 5), 4);
  CHECK_EQ(f.payload[7], 3);
  CHECK_EQ(proto::get_i16(f.payload + 8), 123);
  CHECK_EQ(proto::get_i16(f.payload + 12), 0);  // 逆転側リミット作動中

  n = r.send(proto::CMD_PING);
  f = parse_one(std::vector<uint8_t>(r.reply, r.reply + n));
  CHECK_EQ(f.type, proto::INFO);
  CHECK_EQ(f.len, 6);
  CHECK_EQ(f.payload[0], proto::VERSION);
  CHECK_EQ(f.payload[1], proto::BOARD_ID_CHILD);
  CHECK_EQ(f.payload[2], 3);
}

int main() {
  struct {
    const char* name;
    void (*fn)();
  } tests[] = {
      {"crc", test_crc},
      {"roundtrip", test_roundtrip},
      {"resync", test_resync},
      {"len_too_long", test_len_too_long},
      {"boot_disarmed", test_boot_disarmed},
      {"arm_requires_all_zero", test_arm_requires_all_zero},
      {"wrong_motor_count_ignored", test_wrong_motor_count_ignored},
      {"watchdog", test_watchdog},
      {"host_disarm", test_host_disarm},
      {"estop_latch", test_estop_latch},
      {"fault", test_fault},
      {"duty_clamp", test_duty_clamp},
      {"accel_limit", test_accel_limit},
      {"accel_fraction", test_accel_fraction},
      {"limit_switch", test_limit_switch},
      {"max_run_time", test_max_run_time},
      {"disabled_motor", test_disabled_motor},
      {"status_info", test_status_info},
  };
  for (auto& t : tests) {
    int before = g_fail;
    t.fn();
    std::printf("%s %s\n", g_fail == before ? "ok  " : "FAIL", t.name);
  }
  std::printf("\n%d passed, %d failed\n", g_pass, g_fail);
  return g_fail ? 1 : 0;
}
