// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

#include "motor_core.h"

namespace motor_core {

namespace {

int16_t clamp(int32_t v, int16_t lim) {
  if (v > lim) return lim;
  if (v < -lim) return static_cast<int16_t>(-lim);
  return static_cast<int16_t>(v);
}

int16_t iabs(int16_t v) { return v < 0 ? static_cast<int16_t>(-v) : v; }

}  // namespace

Controller::Controller(const BoardConfig& cfg) : cfg_(cfg) {}

void Controller::disarm(State s, Reason r) {
  state_ = s;
  reason_ = r;
  for (int i = 0; i < proto::MAX_MOTORS; ++i) {
    target_[i] = 0;
    out_[i] = 0;
    running_[i] = false;
    run_locked_[i] = false;
    accel_rem_[i] = 0;
  }
}

void Controller::set_fault(uint8_t flags) {
  fault_ |= flags;
  disarm(FAULT, REASON_FAULT);
}

bool Controller::take_reinit_request() {
  bool r = reinit_request_;
  reinit_request_ = false;
  return r;
}

void Controller::handle_set(const proto::Frame& f, uint32_t now_ms) {
  if (state_ == ESTOP || state_ == FAULT) return;
  if (f.len < 2) return;
  const uint8_t n = f.payload[1];
  if (n != cfg_.n_motors || f.len != 2 + 2 * n) return;

  const bool arm = f.payload[0] & proto::SET_FLAG_ARM;
  int16_t duty[proto::MAX_MOTORS];
  bool all_zero = true;
  for (int i = 0; i < n; ++i) {
    duty[i] = clamp(proto::get_i16(f.payload + 2 + 2 * i), proto::DUTY_MAX);
    if (duty[i] != 0) all_zero = false;
  }

  if (state_ == DISARMED) {
    // ARM は「全モーター0」の指令でしか受け付けない（再接続直後に急に動き出さないため）
    if (arm && all_zero) {
      state_ = ARMED;
      reason_ = REASON_NONE;
      last_cmd_ms_ = now_ms;
    }
    return;
  }

  // ARMED
  if (!arm) {
    disarm(DISARMED, REASON_HOST);
    return;
  }
  for (int i = 0; i < n; ++i) target_[i] = duty[i];
  last_cmd_ms_ = now_ms;
}

size_t Controller::on_frame(const proto::Frame& f, uint32_t now_ms, uint8_t* reply,
                            size_t reply_size) {
  switch (f.type) {
    case proto::CMD_SET:
      handle_set(f, now_ms);
      return 0;
    case proto::CMD_ESTOP:
      // FAULT 中は出力が既に止まっており、CLEAR で再初期化が必要なので FAULT のままにする
      if (state_ != FAULT) disarm(ESTOP, REASON_ESTOP);
      return 0;
    case proto::CMD_CLEAR:
      if (state_ == FAULT) {
        fault_ = 0;
        reinit_request_ = true;
      }
      // CLEAR 後は必ず DISARMED（すぐには動かない）
      disarm(DISARMED, REASON_CLEAR);
      return 0;
    case proto::CMD_PING:
      return build_info(f.seq, reply, reply_size);
    default:
      return 0;
  }
}

void Controller::tick(uint32_t now_ms, uint16_t limits) {
  const uint32_t dt = ticked_ ? now_ms - last_tick_ms_ : 0;
  last_tick_ms_ = now_ms;
  ticked_ = true;
  limits_ = limits;

  if (state_ == ARMED && now_ms - last_cmd_ms_ > WATCHDOG_MS) {
    disarm(DISARMED, REASON_WATCHDOG);
  }
  if (state_ != ARMED) {
    for (int i = 0; i < proto::MAX_MOTORS; ++i) out_[i] = 0;
    return;
  }

  for (int i = 0; i < cfg_.n_motors; ++i) {
    const MotorConfig& m = cfg_.motors[i];

    // 連続駆動時間の上限：超えたら指令が一度0に戻るまで止める
    if (target_[i] == 0) {
      running_[i] = false;
      run_locked_[i] = false;
    } else if (!running_[i]) {
      running_[i] = true;
      run_start_ms_[i] = now_ms;
    } else if (m.max_run_ms && now_ms - run_start_ms_[i] > m.max_run_ms) {
      run_locked_[i] = true;
    }

    int16_t t = m.enabled ? clamp(target_[i], m.max_duty) : 0;
    if (run_locked_[i]) t = 0;
    // リミット作動中はその方向への駆動だけ止める
    if (t > 0 && m.limit_fwd != NO_LIMIT && (limits >> m.limit_fwd) & 1) t = 0;
    if (t < 0 && m.limit_rev != NO_LIMIT && (limits >> m.limit_rev) & 1) t = 0;

    const int16_t cur = out_[i];
    int16_t next;
    if ((cur > 0 && t < 0) || (cur < 0 && t > 0)) {
      next = 0;  // 反転時は一度0を通る
      accel_rem_[i] = 0;
    } else if (iabs(t) <= iabs(cur) || m.accel_per_s == 0) {
      next = t;  // 減速・停止は即時
      accel_rem_[i] = 0;
    } else {
      const uint32_t total = static_cast<uint32_t>(m.accel_per_s) * dt + accel_rem_[i];
      uint32_t step = total / 1000;
      accel_rem_[i] = total % 1000;
      const uint32_t gap = static_cast<uint32_t>(iabs(t) - iabs(cur));
      if (step >= gap) {
        step = gap;
        accel_rem_[i] = 0;
      }
      const int16_t mag = static_cast<int16_t>(iabs(cur) + step);
      next = t > 0 ? mag : static_cast<int16_t>(-mag);
    }
    out_[i] = next;
  }
}

size_t Controller::build_status(uint8_t seq, uint16_t rx_errors, uint8_t* out,
                                size_t out_size) const {
  uint8_t p[8 + 2 * proto::MAX_MOTORS];
  p[0] = state_;
  p[1] = reason_;
  p[2] = fault_;
  proto::put_u16(p + 3, limits_);
  proto::put_u16(p + 5, rx_errors);
  p[7] = cfg_.n_motors;
  for (int i = 0; i < cfg_.n_motors; ++i) proto::put_i16(p + 8 + 2 * i, out_[i]);
  return proto::encode(proto::STATUS, seq, p, 8 + 2 * cfg_.n_motors, out, out_size);
}

size_t Controller::build_info(uint8_t seq, uint8_t* out, size_t out_size) const {
  const uint8_t p[6] = {proto::VERSION, cfg_.board_id, cfg_.n_motors,
                        cfg_.fw_major,  cfg_.fw_minor, cfg_.fw_patch};
  return proto::encode(proto::INFO, seq, p, sizeof(p), out, out_size);
}

}  // namespace motor_core
