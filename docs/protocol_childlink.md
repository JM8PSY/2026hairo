# 親機 ⇔ 子機 UDP プロトコル（v1）

実装：`common/childlink/`（親機側 `ChildClient`、子機側 `ChildController`）。子機プロセスは `child/control/child_control.py`。
既定ポート：子機 UDP **47100**（仮。IP・ポートは CLAUDE.md §12 で未決定。設定ファイル化の際に移す）。

## 方針

UDP は落ちる・順番が入れ替わる前提。**どのパケットも単独で意味が通る**ようにする。

- DRIVE（親機→子機、約50Hz）は毎回、全モーターのデューティと ESTOP フラグを丸ごと送る。
- ARM / CLEAR は **要求カウンタ**（0〜255）で送る。子機は値が変わったときだけ実行する。
  落ちても次のパケットで伝わり、重複しても1回しか実行されない。
- `session` は送信側の起動ごとの乱数。`seq` は session 内で単調増加し、古い・重複は捨てる。
- session が変わった直後（親機の再起動・子機の起動直後）は、カウンタを基準値として覚えるだけで **実行しない**。
- 子機は DRIVE が 0.3 秒途絶えたら ARM を解除する。再開は操作者の ARM 要求（カウンタを進める）から。
- ESTOP フラグ中は ESP32 を ESTOP にし続け、ARM 要求は捨てる。解除は CLEAR 要求。

## パケット（リトルエンディアン）

共通ヘッダ（16バイト）：`magic "HC"` `version(u8)=1` `type(u8)` `session(u32)` `seq(u32)` `time_ms(u32)`

| type | 向き | 本体 |
|------|------|------|
| 0x01 DRIVE | 親→子 | `flags(u8: bit0=ESTOP)` `arm_req(u8)` `clear_req(u8)` `n(u8)` `duty(i16)×n` |
| 0x81 STATUS | 子→親（20Hz） | `ack_session(u32)` `ack_seq(u32)` `ack_time_ms(u32)` `rx_count(u32)` `stale(u32)` `esp_state(u8)` `esp_reason(u8)` `esp_fault(u8)` `phase(u8)` `connected(u8)` `n(u8)` `out(i16)×n` |

- `ack_*` は子機が最後に受け取った DRIVE。親機は `ack_time_ms` から往復時間を、`ack_seq` と `rx_count` の増え方からロス率を出す。
- `esp_state` は ESP32 の状態（`docs/protocol_motor_esp32.md`）。子機が ESP32 と通信できていなければ 0xFF。
- `phase`：0 disarmed / 1 arming / 2 armed（子機の motorlink の状態）。
- STATUS は最後に有効な DRIVE をくれた送信元アドレスへ返す。
