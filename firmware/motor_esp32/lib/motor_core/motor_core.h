// モーター出力の状態遷移・ウォッチドッグ・出力制限（CLAUDE.md §4）。Arduino 非依存。
// 時刻はすべて呼び出し側が渡す（ミリ秒）。ホストPCの単体テストとシミュレータで同じコードを使う。
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "proto.h"

namespace motor_core {

enum State : uint8_t {
  DISARMED = 0,
  ARMED = 1,
  ESTOP = 2,
  FAULT = 3,
};

// 最後に DISARMED / ESTOP / FAULT になった理由
enum Reason : uint8_t {
  REASON_NONE = 0,
  REASON_BOOT = 1,
  REASON_WATCHDOG = 2,
  REASON_HOST = 3,    // ホストが ARM フラグなしの CMD_SET を送った
  REASON_ESTOP = 4,
  REASON_FAULT = 5,
  REASON_CLEAR = 6,
};

enum FaultFlag : uint8_t {
  FAULT_I2C = 0x01,
};

constexpr int8_t NO_LIMIT = -1;
constexpr uint32_t WATCHDOG_MS = 200;

struct MotorConfig {
  bool enabled;          // false の間は出力を常に 0（役割未定のモーター等）
  int16_t max_duty;      // デューティ上限（0〜1000）
  uint16_t accel_per_s;  // 1秒あたりに増やせるデューティ（0 = 制限なし）。減速は常に即時
  int8_t limit_fwd;      // 正転方向のリミット入力のビット番号（NO_LIMIT = なし）
  int8_t limit_rev;      // 逆転方向のリミット入力のビット番号
  uint32_t max_run_ms;   // 連続駆動時間の上限（0 = なし）
};

struct BoardConfig {
  uint8_t board_id;  // proto::BoardId
  uint8_t n_motors;
  const MotorConfig* motors;
  uint8_t fw_major, fw_minor, fw_patch;
};

class Controller {
 public:
  explicit Controller(const BoardConfig& cfg);

  // 受信フレームを処理する。応答が必要なら reply に書いて長さを返す（なければ 0）。
  size_t on_frame(const proto::Frame& f, uint32_t now_ms, uint8_t* reply, size_t reply_size);

  // 周期処理。limits はリミット入力（ビットが立っている = 作動中）。出力値を更新する。
  void tick(uint32_t now_ms, uint16_t limits);

  // I2C 失敗などハードウェア故障を知らせる。出力を止めて FAULT にする。
  void set_fault(uint8_t flags);

  // CLEAR で FAULT から抜けたとき true（呼び出し側は PCA9685 を再初期化し、
  // 失敗したら set_fault() を呼ぶ）。読むとフラグは下りる。
  bool take_reinit_request();

  State state() const { return state_; }
  Reason reason() const { return reason_; }
  uint8_t fault() const { return fault_; }
  bool output_enabled() const { return state_ == ARMED; }  // PCA9685 の OE を有効にしてよいか
  int16_t output(int i) const { return out_[i]; }
  uint8_t n_motors() const { return cfg_.n_motors; }

  // STATUS / INFO フレームを作る（seq は呼び出し側が管理）
  size_t build_status(uint8_t seq, uint16_t rx_errors, uint8_t* out, size_t out_size) const;
  size_t build_info(uint8_t seq, uint8_t* out, size_t out_size) const;

 private:
  void disarm(State s, Reason r);
  void handle_set(const proto::Frame& f, uint32_t now_ms);

  const BoardConfig& cfg_;
  State state_ = DISARMED;
  Reason reason_ = REASON_BOOT;
  uint8_t fault_ = 0;
  bool reinit_request_ = false;
  uint32_t last_cmd_ms_ = 0;
  uint32_t last_tick_ms_ = 0;
  bool ticked_ = false;
  uint16_t limits_ = 0;
  int16_t target_[proto::MAX_MOTORS] = {};
  int16_t out_[proto::MAX_MOTORS] = {};
  uint32_t run_start_ms_[proto::MAX_MOTORS] = {};
  bool running_[proto::MAX_MOTORS] = {};
  bool run_locked_[proto::MAX_MOTORS] = {};
  uint32_t accel_rem_[proto::MAX_MOTORS] = {};  // 加速制限の端数（duty*ms）
};

}  // namespace motor_core
