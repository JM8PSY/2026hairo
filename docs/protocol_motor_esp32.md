# ホスト ⇔ ESP32 通信プロトコル（v1）

実装：C++ `firmware/motor_esp32/lib/proto/`、Python `common/motorlink/proto.py`（必ず同時に変更する）。
USB シリアル 921600bps（ESP32 の USB-UART は速度に関係なく動くことが多いが、設定は合わせる）。

## フレーム

| バイト | 内容 |
|--------|------|
| 0–1 | `0xAA 0x55` |
| 2 | type |
| 3 | seq（送信側が 1 ずつ増やす。受信側は今のところ使わない） |
| 4 | len（payload 長、0〜64） |
| 5… | payload |
| 末尾2 | CRC16-CCITT（多項式 0x1021、初期値 0xFFFF、type〜payload 末尾）。リトルエンディアン |

CRC 不一致・len 超過のフレームは捨て、次の `0xAA 0x55` から再同期する。数値はすべてリトルエンディアン。

## ホスト → ESP32

| type | 名前 | payload |
|------|------|---------|
| 0x01 | CMD_SET | `flags(u8)` `n(u8)` `duty(i16) × n`。flags bit0 = ARM。duty は千分率 -1000〜+1000（正=正転） |
| 0x02 | CMD_ESTOP | なし |
| 0x03 | CMD_CLEAR | なし |
| 0x04 | CMD_PING | なし（INFO が返る） |

- `n` が基板のモーター数と違う CMD_SET は無視する。
- DISARMED 中は「ARM フラグ付き かつ 全0」の CMD_SET でだけ ARMED になる。
- ARMED 中に ARM フラグなしの CMD_SET を受けると DISARMED（理由 HOST）。
- ホストは約 50Hz で CMD_SET を送り続ける。200ms 途絶えると DISARMED（理由 WATCHDOG）。

## ESP32 → ホスト

| type | 名前 | payload |
|------|------|---------|
| 0x81 | STATUS（20Hz） | `state(u8)` `reason(u8)` `fault(u8)` `limits(u16)` `rx_errors(u16)` `n(u8)` `out(i16) × n` |
| 0x82 | INFO（起動時・PING 応答） | `proto_version(u8)` `board_id(u8)` `n_motors(u8)` `fw_major` `fw_minor` `fw_patch` |

| state | 意味 |
|-------|------|
| 0 DISARMED | 出力無効 |
| 1 ARMED | 出力有効 |
| 2 ESTOP | 非常停止ラッチ（CLEAR で DISARMED へ） |
| 3 FAULT | I2C 故障など（CLEAR で PCA9685 を再初期化して DISARMED へ） |

reason（最後に止まった理由）：0 NONE / 1 BOOT / 2 WATCHDOG / 3 HOST / 4 ESTOP / 5 FAULT / 6 CLEAR

fault ビット：bit0 = I2C

limits ビット（親機）：bit0 = ふた「開」リミット、bit1 = ふた「閉」リミット（1 = 作動中。断線も作動扱い）

board_id：1 = 親機、2 = 子機。ホストは期待と違えば接続を拒否する。

`out` はリミット・加速制限・上限を適用した後の実際の出力値。
