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
- [docs/protocol_childlink.md](docs/protocol_childlink.md) — 親機 ⇔ 子機 UDP プロトコル
- [docs/protocol_web.md](docs/protocol_web.md) — ブラウザ ⇔ 親機 WebSocket
- [docs/protocol_video.md](docs/protocol_video.md) — ブラウザ ⇔ 映像サーバー WebSocket
- [docs/roadmap.md](docs/roadmap.md) — 開発の進め方

## ライセンス

Copyright (C) 2026 旭川工業高等専門学校 最先端テクノロジー同好会

このソフトウェアは [GNU General Public License v3.0 以降](LICENSE)（`GPL-3.0-or-later`）で公開しています。
GPL の条件に従う限り、利用・改変・再配布できます。改変版を配布する場合は、同じライセンスでソースコードを公開してください。

各ソースファイルの先頭には [SPDX](https://spdx.dev/) 形式の著作権・ライセンス表示（`SPDX-FileCopyrightText` / `SPDX-License-Identifier`）を入れています。新しくファイルを作るときも同じ2行を入れてください。

## 免責

- 本ソフトウェアは、ロボットコンテスト参加のための研究開発・学習を目的として作成したものです。実用・製品用途での動作実績はなく、そのような用途での品質・安全性は検証していません。
- 本ソフトウェアは「現状のまま」提供され、明示・黙示を問わず一切の保証をしません（GPL-3.0 第15条・第16条）。
- 本ソフトウェアの利用または利用できなかったことにより生じた損害・不利益（モーター等の機器の故障、人身事故、データの損失を含む）について、著作権者は一切の責任を負いません。
- 実機（モーター・アクチュエータ等）を動かす場合は、利用者自身の責任で安全を確保してください。
