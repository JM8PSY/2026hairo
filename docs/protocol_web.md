# ブラウザ ⇔ 親機 WebSocket（`/ws`、JSON）

実装：`parent/server/app.py`（配線）、`parent/server/control.py`（操縦ロジック・安全ルール）。

## ブラウザ → 親機

| t | 誰が | 内容 |
|---|------|------|
| `take_control` | 誰でも | 操縦権を要求。空いていれば操縦者になる。応答 `role` |
| `release_control` | 操縦者 | 操縦権を返す（全機停止） |
| `cmd` | 操縦者 | **約50Hzで送り続ける（ハートビートを兼ねる）**。下記 |
| `arm` | 操縦者 | 両機を ARM。直後は入力がニュートラルに戻るまで動かない |
| `disarm` | 操縦者 | 両機の ARM 解除 |
| `estop` | **誰でも** | 非常停止（両機）。ラッチする |
| `clear` | 操縦者 | 非常停止の解除。解除後も ARM するまで動かない |

`cmd` の中身：

```json
{"t": "cmd", "ok": true, "why": null, "target": "parent",
 "parent": {"left": 0, "right": 0, "sub_front": 0, "sub_rear": 0, "lid": 0, "reel": 0},
 "child":  {"left": 0, "right": 0, "brush": 0},
 "lid_confirm": false}
```

- 値は -1.0〜1.0（|値| < 0.05 は 0 扱い）。`target` でない側の機体には 0 が送られる。
- `ok` が false なら全機停止（`why` に理由：`hidden` / `blur` / `gamepad_disconnected` など）。
  ブラウザはタブ非表示・フォーカス喪失・ゲームパッド切断で ok=false を送る。
- `lid` < 0（閉じる）は `lid_confirm` が true の間だけ有効。
- `reel` ≠ 0 の間、子機の走行指令は 0 になる。

## 親機 → ブラウザ

| t | 内容 |
|---|------|
| `hello` | 接続直後。`id`, `role`（最初は `viewer`） |
| `role` | `take_control` / `release_control` の結果 |
| `error` | `not_operator` / `estop_active` など |
| `status` | 10Hz。下記 |

```json
{"t": "status", "role": "operator",
 "core":   {"operator": true, "armed": true, "need_neutral": false, "estop": false,
            "stop_reason": null, "target": "parent", "parent_cmd": [..9], "child_cmd": [..3]},
 "parent": {"connected": true, "error": null, "phase": "armed", "state": "ARMED", "reason": "NONE",
            "fault": 0, "limits": 0, "outputs": [..9], "last_disarm_reason": null},
 "child":  {"connected": true, "rtt_ms": 3.0, "loss": 0.0, "phase": "armed",
            "esp_connected": true, "esp_state": "ARMED", "outputs": [..3]}}
```

`stop_reason`：`startup` / `heartbeat_timeout` / `operator_disconnected` / `released` / `operator_disarm` / `estop` / `cleared` / ブラウザの `why`
