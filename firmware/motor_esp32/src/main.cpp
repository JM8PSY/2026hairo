// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// モーター駆動 ESP32：シリアル受信 → motor_core → PCA9685 → MD20A（CLAUDE.md §4）
// 状態遷移・制限は lib/motor_core（ホストでテスト済み）に任せ、ここはハードウェアの入出力だけ。
#include <Arduino.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include "board_config.h"
#include "motor_core.h"
#include "pca9685.h"
#include "proto.h"

#if !defined(BOARD_PARENT) && !defined(BOARD_CHILD)
#error "BOARD_PARENT か BOARD_CHILD を定義すること（platformio.ini の env）"
#endif

namespace {

constexpr uint32_t STATUS_PERIOD_MS = 50;  // 20Hz
constexpr uint32_t TASK_WDT_S = 1;

motor_core::Controller ctrl(board::kBoard);
proto::Parser parser;
uint8_t tx_seq = 0;
uint32_t last_status_ms = 0;
uint8_t frame_buf[proto::MAX_FRAME];

// PCA9685 に最後に書いた値（変化したときだけ書く）。-1 = 未書き込み
int32_t written_pwm[proto::MAX_MOTORS];
int8_t written_dir[proto::MAX_MOTORS];

void set_oe(bool enable) { digitalWrite(board::PIN_PCA_OE, enable ? LOW : HIGH); }

bool init_pcas() {
  // 使っているアドレスを重複なく初期化する
  uint8_t done[4];
  int n_done = 0;
  for (int i = 0; i < board::kBoard.n_motors; ++i) {
    const uint8_t addrs[2] = {board::kChannels[i].pwm_addr, board::kChannels[i].dir_addr};
    for (uint8_t a : addrs) {
      bool seen = false;
      for (int k = 0; k < n_done; ++k) seen |= done[k] == a;
      if (seen) continue;
      if (!pca9685::begin(a, board::PWM_HZ)) return false;
      done[n_done++] = a;
    }
  }
  for (int i = 0; i < proto::MAX_MOTORS; ++i) {
    written_pwm[i] = -1;
    written_dir[i] = -1;
  }
  return true;
}

uint16_t read_limits() {
  if (!board::kHasLid) return 0;
  // NC スイッチ → GND、INPUT_PULLUP。押された・断線した = High = 作動
  uint16_t v = 0;
  if (digitalRead(board::PIN_LID_OPEN) == HIGH) v |= 1u << board::LIMIT_LID_OPEN;
  if (digitalRead(board::PIN_LID_CLOSED) == HIGH) v |= 1u << board::LIMIT_LID_CLOSED;
  return v;
}

bool write_outputs() {
  for (int i = 0; i < board::kBoard.n_motors; ++i) {
    const board::Channel& ch = board::kChannels[i];
    const int16_t out = ctrl.output(i);
    const int8_t dir = ((out < 0) != ch.invert) ? 1 : 0;
    const int32_t pwm = static_cast<int32_t>(out < 0 ? -out : out) * 4095 / proto::DUTY_MAX;
    // 方向を変えるときは先に PWM を 0 にしてから DIR を切り替える
    if (dir != written_dir[i] && written_pwm[i] != 0) {
      if (!pca9685::set(ch.pwm_addr, ch.pwm_ch, 0)) return false;
      written_pwm[i] = 0;
    }
    if (dir != written_dir[i]) {
      if (!pca9685::set(ch.dir_addr, ch.dir_ch, dir ? 4095 : 0)) return false;
      written_dir[i] = dir;
    }
    if (pwm != written_pwm[i]) {
      if (!pca9685::set(ch.pwm_addr, ch.pwm_ch, static_cast<uint16_t>(pwm))) return false;
      written_pwm[i] = pwm;
    }
  }
  return true;
}

void update_led(uint32_t now) {
  bool on;
  switch (ctrl.state()) {
    case motor_core::ARMED: on = true; break;
    case motor_core::DISARMED: on = (now / 500) % 2; break;  // 1Hz
    default: on = (now / 100) % 2; break;                    // ESTOP / FAULT 5Hz
  }
  digitalWrite(board::PIN_LED, on ? HIGH : LOW);
}

}  // namespace

void setup() {
  // まず出力を無効にする（OE は外付けプルアップで起動中も High）
  pinMode(board::PIN_PCA_OE, OUTPUT);
  set_oe(false);
  pinMode(board::PIN_LED, OUTPUT);
  if (board::kHasLid) {
    pinMode(board::PIN_LID_OPEN, INPUT_PULLUP);
    pinMode(board::PIN_LID_CLOSED, INPUT_PULLUP);
  }

  Serial.setRxBufferSize(1024);
  Serial.begin(board::SERIAL_BAUD);
  Wire.begin(board::PIN_I2C_SDA, board::PIN_I2C_SCL, board::I2C_HZ);
  Wire.setTimeOut(5);
  if (!init_pcas()) ctrl.set_fault(motor_core::FAULT_I2C);

  esp_task_wdt_init(TASK_WDT_S, true);
  esp_task_wdt_add(nullptr);

  Serial.write(frame_buf, ctrl.build_info(tx_seq++, frame_buf, sizeof(frame_buf)));
}

void loop() {
  esp_task_wdt_reset();
  const uint32_t now = millis();

  while (Serial.available() > 0) {
    if (!parser.feed(static_cast<uint8_t>(Serial.read()))) continue;
    size_t n = ctrl.on_frame(parser.frame(), now, frame_buf, sizeof(frame_buf));
    if (n) Serial.write(frame_buf, n);
  }

  ctrl.tick(now, read_limits());

  if (ctrl.take_reinit_request() && !init_pcas()) ctrl.set_fault(motor_core::FAULT_I2C);

  // 止めるときは OE を先に切る。動かすときは出力値を書いてから OE を入れる
  if (!ctrl.output_enabled()) set_oe(false);
  if (ctrl.state() != motor_core::FAULT && !write_outputs()) {
    ctrl.set_fault(motor_core::FAULT_I2C);
  }
  set_oe(ctrl.output_enabled());

  if (now - last_status_ms >= STATUS_PERIOD_MS) {
    last_status_ms = now;
    Serial.write(frame_buf, ctrl.build_status(tx_seq++, parser.errors(), frame_buf, sizeof(frame_buf)));
  }
  update_led(now);
}
