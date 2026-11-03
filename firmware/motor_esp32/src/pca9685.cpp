// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

#include "pca9685.h"

namespace pca9685 {

namespace {

constexpr uint8_t REG_MODE1 = 0x00;
constexpr uint8_t REG_MODE2 = 0x01;
constexpr uint8_t REG_LED0 = 0x06;
constexpr uint8_t REG_ALL_LED = 0xFA;
constexpr uint8_t REG_PRESCALE = 0xFE;

constexpr uint8_t MODE1_SLEEP = 0x10;
constexpr uint8_t MODE1_AI = 0x20;
constexpr uint8_t MODE1_RESTART = 0x80;
constexpr uint8_t MODE2_OUTDRV = 0x04;

bool write(uint8_t addr, uint8_t reg, const uint8_t* data, size_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(data, n);
  return Wire.endTransmission() == 0;
}

bool write8(uint8_t addr, uint8_t reg, uint8_t v) { return write(addr, reg, &v, 1); }

}  // namespace

bool begin(uint8_t addr, float pwm_hz) {
  // 全出力をフル OFF にしてから設定する
  const uint8_t all_off[4] = {0, 0, 0, 0x10};
  if (!write8(addr, REG_MODE1, MODE1_SLEEP | MODE1_AI)) return false;
  if (!write(addr, REG_ALL_LED, all_off, 4)) return false;
  // prescale = round(25MHz / (4096 * f)) - 1
  int prescale = static_cast<int>(25000000.0f / (4096.0f * pwm_hz) + 0.5f) - 1;
  if (prescale < 3) prescale = 3;
  if (prescale > 255) prescale = 255;
  if (!write8(addr, REG_PRESCALE, static_cast<uint8_t>(prescale))) return false;
  if (!write8(addr, REG_MODE2, MODE2_OUTDRV)) return false;
  if (!write8(addr, REG_MODE1, MODE1_AI)) return false;  // SLEEP 解除
  delayMicroseconds(500);                                 // 発振器の安定待ち
  return write8(addr, REG_MODE1, MODE1_AI | MODE1_RESTART);
}

bool set(uint8_t addr, uint8_t ch, uint16_t duty) {
  uint8_t d[4];
  if (duty == 0) {
    d[0] = 0; d[1] = 0; d[2] = 0; d[3] = 0x10;  // フル OFF
  } else if (duty >= 4095) {
    d[0] = 0; d[1] = 0x10; d[2] = 0; d[3] = 0;  // フル ON
  } else {
    d[0] = 0; d[1] = 0;
    d[2] = duty & 0xFF; d[3] = (duty >> 8) & 0x0F;
  }
  return write(addr, REG_LED0 + 4 * ch, d, 4);
}

}  // namespace pca9685
