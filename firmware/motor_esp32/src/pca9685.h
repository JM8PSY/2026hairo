// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// PCA9685 の最小ドライバ（必要な機能だけ）。失敗したら false を返す。
#pragma once
#include <Arduino.h>
#include <Wire.h>

namespace pca9685 {

// MODE2: OUTDRV=1（トーテムポール）、OUTNE=00（OE=High のとき出力 Low）
bool begin(uint8_t addr, float pwm_hz);
// duty 0〜4095。0 は完全 Low、4095 は完全 High（フル ON ビットを使う）
bool set(uint8_t addr, uint8_t ch, uint16_t duty);

}  // namespace pca9685
