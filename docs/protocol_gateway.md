# ブラウザ ⇔ ゲートウェイ WebSocket（`/ws`、JSON）

実装：`parent/server/gateway.py`、`parent/server/ros_backend.py`、`parent/server/map_core.py`。設定：`parent/config/gateway.json`。

ゲートウェイは操縦サーバー（`app.py`）とは別プロセスで、ポートも別（既定 8082）。ROS が止まっても操縦と非常停止に影響しない。
ページは操縦サーバーの `/map` と `/status` で配信する。センサーの ON/OFF と地図の操作はモーターを動かさないので、操縦権は不要。

## 親機 → ブラウザ

| t | 頻度 | 内容 |
|---|------|------|
| `map` | 変化時、最大 `map_hz` | `seq`, `w`, `h`, `res`, `ox`, `oy`, `cells`（base64。1マス1バイト、下の行から。255 = 不明、0〜100 = 占有度） |
| `map_clear` | リセット時 | 地図を消す |
| `pose` | 10Hz | `pose`: `{x, y, yaw}`（`map` → `base_link`。無ければ null） |
| `scan` | 最大 `scan_hz` | `angle_min`, `angle_inc`, `ranges`（cm の整数、0 = 無効）, `laser`: `{x, y, yaw}` |
| `sensors` | 1Hz | `ros`, `slam`, `lidar`: `{driver, wanted, scan_hz}`, `d455`: `{state}`, `system`: `{temp_c, cpu_pct, mem_pct}` |
| `result` | 操作の結果 | `op`, `ok`, `error`（失敗時）, `path`（保存時） |

## ブラウザ → 親機

| t | 内容 |
|---|------|
| `lidar` | `on`: true/false。ドライバの `/start_scan`・`/stop_scan` を呼ぶ |
| `map_save` | `parent/maps/map-<日時>` に PGM・YAML（nav2 形式）と、続きから作るためのデータ（`.posegraph`・`.data`）を保存 |
| `map_reset` | `/slam_toolbox/reset` で地図を消す |

## 補足

- ドライバが再起動するとスキャンを始めるので、OFF の間は止め直す。起動時の既定状態は `lidar_default_on`。
- OFF は異常扱いせず、画面に OFF と明示する。ON に戻すと同じ地図の上で SLAM を続ける。
