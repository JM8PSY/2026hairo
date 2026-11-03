// 親機/子機ごとのピン・モーター割当・出力制限（CLAUDE.md §4）。
// docs/wiring_motor_esp32.md と必ず一致させること。
// ビルド時に BOARD_PARENT か BOARD_CHILD を定義する（platformio.ini の env で切替）。
// ホストのテスト・シミュレータは kParent / kChild の両方を参照する。
#pragma once
#include <stdint.h>

#include "motor_core.h"

namespace board {

constexpr uint8_t FW_MAJOR = 0, FW_MINOR = 1, FW_PATCH = 0;

// ---- ESP32 のピン（仮。配線確定時に docs と合わせて更新） ----
constexpr int PIN_I2C_SDA = 21;
constexpr int PIN_I2C_SCL = 22;
constexpr int PIN_PCA_OE = 25;   // 外付け 2.2kΩ でプルアップ。High = 全出力 Low
constexpr int PIN_LED = 2;
constexpr int PIN_LID_OPEN = 32;   // 親機のみ。NC スイッチ → GND、INPUT_PULLUP
constexpr int PIN_LID_CLOSED = 33; // 親機のみ

constexpr uint32_t I2C_HZ = 400000;
constexpr float PWM_HZ = 1500.0f;  // PCA9685 の上限付近
constexpr uint32_t SERIAL_BAUD = 921600;

// ---- PCA9685 のチャンネル割当 ----
struct Channel {
  uint8_t pwm_addr, pwm_ch;
  uint8_t dir_addr, dir_ch;
  bool invert;  // 配線の都合で正転方向を反転する
};

// ---- リミット入力のビット番号（STATUS の limits と共通） ----
constexpr int8_t LIMIT_LID_OPEN = 0;
constexpr int8_t LIMIT_LID_CLOSED = 1;

using motor_core::MotorConfig;
using motor_core::NO_LIMIT;

// 親機：P1〜P9。P7 ふたは正転=開く
constexpr MotorConfig kParentMotors[9] = {
    // enabled max_duty accel  limit_fwd       limit_rev         max_run_ms
    {true, 1000, 2000, NO_LIMIT, NO_LIMIT, 0},                   // P1 メインクローラー左
    {true, 1000, 2000, NO_LIMIT, NO_LIMIT, 0},                   // P2 メインクローラー右
    {true, 800, 2000, NO_LIMIT, NO_LIMIT, 0},                    // P3 サブクローラー左前
    {true, 800, 2000, NO_LIMIT, NO_LIMIT, 0},                    // P4 サブクローラー右前
    {true, 800, 2000, NO_LIMIT, NO_LIMIT, 0},                    // P5 サブクローラー左後
    {true, 800, 2000, NO_LIMIT, NO_LIMIT, 0},                    // P6 サブクローラー右後
    {true, 600, 2000, LIMIT_LID_OPEN, LIMIT_LID_CLOSED, 5000},   // P7 ふた
    {true, 400, 1000, NO_LIMIT, NO_LIMIT, 0},                    // P8 リール（初期値40%）
    {false, 0, 0, NO_LIMIT, NO_LIMIT, 0},                        // P9 役割未定。出力0固定
};
constexpr Channel kParentChannels[9] = {
    // PWM は 0x40 の ch0〜8、DIR は 0x41 の ch0〜8
    {0x40, 0, 0x41, 0, false}, {0x40, 1, 0x41, 1, false}, {0x40, 2, 0x41, 2, false},
    {0x40, 3, 0x41, 3, false}, {0x40, 4, 0x41, 4, false}, {0x40, 5, 0x41, 5, false},
    {0x40, 6, 0x41, 6, false}, {0x40, 7, 0x41, 7, false}, {0x40, 8, 0x41, 8, false},
};

// 子機：C1〜C3
constexpr MotorConfig kChildMotors[3] = {
    {true, 1000, 2000, NO_LIMIT, NO_LIMIT, 0},  // C1 クローラー左
    {true, 1000, 2000, NO_LIMIT, NO_LIMIT, 0},  // C2 クローラー右
    {true, 800, 2000, NO_LIMIT, NO_LIMIT, 0},   // C3 デブリ回収ブラシ
};
constexpr Channel kChildChannels[3] = {
    // PCA9685 1枚（0x40）。モーター i の PWM = ch 2i、DIR = ch 2i+1
    {0x40, 0, 0x40, 1, false}, {0x40, 2, 0x40, 3, false}, {0x40, 4, 0x40, 5, false},
};

constexpr motor_core::BoardConfig kParent = {proto::BOARD_ID_PARENT, 9, kParentMotors,
                                             FW_MAJOR, FW_MINOR, FW_PATCH};
constexpr motor_core::BoardConfig kChild = {proto::BOARD_ID_CHILD, 3, kChildMotors,
                                            FW_MAJOR, FW_MINOR, FW_PATCH};

#if defined(BOARD_PARENT)
constexpr const motor_core::BoardConfig& kBoard = kParent;
constexpr const Channel* kChannels = kParentChannels;
constexpr bool kHasLid = true;
#elif defined(BOARD_CHILD)
constexpr const motor_core::BoardConfig& kBoard = kChild;
constexpr const Channel* kChannels = kChildChannels;
constexpr bool kHasLid = false;
#endif

}  // namespace board
