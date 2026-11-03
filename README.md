# 廃炉ロボコン2026 制御システム

親機（Jetson Orin Nano）＋子機（Raspberry Pi 4B）の2台構成ロボットの制御ソフト。
設計方針・安全ルールは [CLAUDE.md](CLAUDE.md) を参照。

## はじめかた（親機 Jetson）

```bash
git clone https://github.com/JM8PSY/2026hairo.git
cd 2026hairo
sudo ./tools/setup_jetson.sh   # 詳細は docs/setup_jetson.md
make test
```

## 実機なしで動かす

```bash
make test                                              # ファーム単体テスト + Python テスト
firmware/motor_esp32/test_host/build/motor_sim child   # ESP32 シミュレータ（pty のパスを表示）
```

## ドキュメント

- [docs/setup_jetson.md](docs/setup_jetson.md) — Jetson の環境構築
- [docs/protocol_motor_esp32.md](docs/protocol_motor_esp32.md) — ホスト ⇔ ESP32 プロトコル
- [docs/wiring_motor_esp32.md](docs/wiring_motor_esp32.md) — モーター駆動の配線
