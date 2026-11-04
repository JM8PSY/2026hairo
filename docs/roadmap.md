# 開発の進め方（ロードマップ）

実機なしで進められるものから順に。終わったら [x] にする。

## 実機なし（Mac / Jetson どちらでも）

- [x] Jetson 環境構築スクリプト（Docker で検証済み）
- [x] ESP32 ファーム：プロトコル・状態遷移・ウォッチドッグ・出力制限（ホスト単体テスト）
- [x] ESP32 ファーム：Arduino 側（PCA9685・OE・リミット・LED）。ビルドのみ確認
- [x] `common/motorlink`（Python）＋ ESP32 シミュレータとの結合テスト
- [x] `tools/motor_test.py`：1モーターずつ低出力で回す確認ツール（実機の最初の通電用）
- [x] 親機⇔子機 UDP プロトコル（`common/childlink`）：シーケンス番号・古いパケット破棄・子機側ウォッチドッグ
- [x] `child/control`：UDP 受信 → motorlink（子機プロセス）＋ダミー子機
- [x] 親機 Web サーバー（aiohttp）：操縦権1つ・ハートビート・E-Stop・全機停止条件（§5）
- [x] Web UI（素の JS）：ゲームパッド・非常停止ボタン・状態表示
- [x] 設定ファイル（`parent/config/parent.json`・`child/config/child.json`・`web/keymap.json`）と systemd ユニット

## Jetson につないでから

- [ ] `sudo ./tools/setup_jetson.sh` を実機で実行、`make test`
- [ ] Chrome＋ゲームパッドで Web UI を操作確認（シミュレータ相手でよい）：ARM・ニュートラル待ち・タブ切替/ゲームパッド抜去での停止・ふた長押し
- [ ] ESP32 のシリアル番号を udev ルールに設定、ファーム書き込み（モーター電源 OFF で）
- [ ] `tools/motor_test.py` で1モーターずつ確認（**ユーザー立ち会い**）
- [x] YD-LiDAR ドライバ（Jazzy）ビルド、`/scan` 確認
- [x] Web UI：マップ（`/map`）、センサーと状態（`/status`）、ROS ゲートウェイ
- [ ] LiDAR を手で動かして地図が正しく広がるか確認
- [ ] Meta Quest 3 の実機で `/vr` を確認
- [ ] RealSense D455 認識確認、SLAM（slam_toolbox）
- [x] Insta360 X4 の出力形式確認 → 配信方式決定（MJPEG パススルー）
- [x] Insta360 の配信をブラウザで確認（遅延はユーザーが目視で OK）
