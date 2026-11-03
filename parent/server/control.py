"""操縦ロジック（CLAUDE.md §5, §6）。aiohttp・ROS に依存しない。

ブラウザからのメッセージ（dict）を受け、50Hz の tick() で親機・子機のバックエンドへ指令を出す。

安全上の決まり：
- 操縦権は1つ。最初に take_control したクライアントだけが操作でき、他は閲覧専用。
- 非常停止（estop）は閲覧者からでも受け付ける。解除（clear）は操縦者のみ。
- 次のどれかで「全機停止」＝両機の ARM を解除する。再開は操縦者の arm から。
  ハートビート（cmd）途絶 / 操縦者の切断・操縦権の返上 / ブラウザが ok=false を送った
  （タブ非表示・フォーカス喪失・ゲームパッド切断はブラウザ側で ok=false にする）
- arm の直後は、スティック等が一度ニュートラルに戻るまで指令を通さない。
- 操作対象でない機体には 0 を送り続ける。
- ふたを閉じる方向（lid < 0）は lid_confirm（長押し等）が true の間だけ通す。
  子機がふたの開口部にいるかを検出できるようになったら、ここにインターロックを足す。
- リール（reel）を動かしている間は、子機の走行指令を 0 にする。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

NEUTRAL = 0.05  # これ以下の入力は 0 とみなす

PARENT_AXES = ("left", "right", "sub_front", "sub_rear", "lid", "reel")
CHILD_AXES = ("left", "right", "brush")


class ParentBackend(Protocol):
    def arm(self) -> None: ...
    def disarm(self) -> None: ...
    def estop(self) -> None: ...
    def clear(self) -> None: ...
    def set_duties(self, duties: list[int]) -> None: ...


class ChildBackend(Protocol):
    def request_arm(self) -> None: ...
    def set_disarm(self, on: bool) -> None: ...
    def set_estop(self, on: bool) -> None: ...
    def request_clear(self) -> None: ...
    def set_duties(self, duties: list[int]) -> None: ...


@dataclass
class Config:
    hb_timeout: float = 0.3
    scale: int = 1000  # 入力 ±1.0 → デューティ ±1000（上限は ESP32 側でもかかる）


@dataclass
class Command:
    target: str = "parent"
    parent: dict[str, float] = field(default_factory=dict)
    child: dict[str, float] = field(default_factory=dict)
    lid_confirm: bool = False


def _axis(d: dict, key: str) -> float:
    try:
        v = float(d.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    v = max(-1.0, min(1.0, v))
    return 0.0 if abs(v) < NEUTRAL else v


class ControlCore:
    def __init__(self, parent: ParentBackend, child: ChildBackend, cfg: Config | None = None,
                 n_parent: int = 9, n_child: int = 3) -> None:
        self.parent = parent
        self.child = child
        self.cfg = cfg or Config()
        self.n_parent = n_parent
        self.n_child = n_child

        self.operator: str | None = None
        self.last_hb = float("-inf")
        self.armed = False          # 操縦者が arm して、まだ止めていない
        self.need_neutral = False   # arm 後、入力がニュートラルに戻るのを待っている
        self.estop = False
        self.stop_reason: str | None = "startup"
        self.cmd = Command()
        self.parent_duties = [0] * n_parent
        self.child_duties = [0] * n_child
        self.child.set_disarm(True)

    # ---- 接続 ----

    def role(self, client_id: str) -> str:
        return "operator" if client_id == self.operator else "viewer"

    def disconnect(self, client_id: str) -> None:
        if client_id == self.operator:
            self.operator = None
            self._stop_all("operator_disconnected")

    # ---- メッセージ ----

    def on_message(self, client_id: str, msg: dict, now: float) -> dict | None:
        t = msg.get("t")
        if t == "estop":  # 誰からでも受け付ける
            self.estop = True
            self.armed = False
            self.stop_reason = "estop"
            self.parent.estop()
            self.child.set_estop(True)
            return None
        if t == "take_control":
            if self.operator is None:
                self.operator = client_id
                self.last_hb = now
            return {"t": "role", "role": self.role(client_id)}
        if client_id != self.operator:
            return {"t": "error", "error": "not_operator"} if t != "cmd" else None
        if t == "release_control":
            self.operator = None
            self._stop_all("released")
            return {"t": "role", "role": "viewer"}
        if t == "cmd":
            self.last_hb = now
            if not msg.get("ok", False):
                self._stop_all(str(msg.get("why") or "client_not_ok"))
            self.cmd = Command(
                target="child" if msg.get("target") == "child" else "parent",
                parent=msg.get("parent") or {},
                child=msg.get("child") or {},
                lid_confirm=bool(msg.get("lid_confirm", False)),
            )
            return None
        if t == "arm":
            if self.estop:
                return {"t": "error", "error": "estop_active"}
            self.armed = True
            self.need_neutral = True
            self.stop_reason = None
            self.parent.arm()
            self.child.request_arm()
            return None
        if t == "disarm":
            self._stop_all("operator_disarm")
            return None
        if t == "clear":
            self.estop = False
            self.armed = False
            self.stop_reason = "cleared"
            self.parent.clear()
            self.child.set_estop(False)
            self.child.request_clear()
            self.child.set_disarm(True)
            return None
        return {"t": "error", "error": f"unknown:{t}"}

    def _stop_all(self, reason: str) -> None:
        if self.armed:
            self.parent.disarm()
            self.child.set_disarm(True)
        self.armed = False
        if not self.estop:
            self.stop_reason = reason

    # ---- 周期処理 ----

    def tick(self, now: float) -> None:
        if self.operator is not None and now - self.last_hb > self.cfg.hb_timeout:
            self._stop_all("heartbeat_timeout")

        p = [0] * self.n_parent
        c = [0] * self.n_child
        if self.armed and not self.estop:
            cmd = self.cmd
            pa = {k: _axis(cmd.parent, k) for k in PARENT_AXES}
            ca = {k: _axis(cmd.child, k) for k in CHILD_AXES}
            active = pa if cmd.target == "parent" else ca
            if self.need_neutral and all(v == 0.0 for v in active.values()):
                self.need_neutral = False
            if not self.need_neutral:
                s = self.cfg.scale
                if cmd.target == "parent":
                    if pa["lid"] < 0 and not cmd.lid_confirm:
                        pa["lid"] = 0.0
                    p[0] = round(pa["left"] * s)        # P1
                    p[1] = round(pa["right"] * s)       # P2
                    p[2] = p[3] = round(pa["sub_front"] * s)  # P3, P4
                    p[4] = p[5] = round(pa["sub_rear"] * s)   # P5, P6
                    p[6] = round(pa["lid"] * s)         # P7
                    p[7] = round(pa["reel"] * s)        # P8（P9 は常に 0）
                else:
                    c[0] = round(ca["left"] * s)
                    c[1] = round(ca["right"] * s)
                    c[2] = round(ca["brush"] * s)
            if p[7] != 0:
                c = [0] * self.n_child  # リール動作中は子機を走らせない
        self.parent_duties = p
        self.child_duties = c
        self.parent.set_duties(p)
        self.child.set_duties(c)

    def snapshot(self) -> dict:
        return {
            "operator": self.operator is not None,
            "armed": self.armed,
            "need_neutral": self.need_neutral,
            "estop": self.estop,
            "stop_reason": self.stop_reason,
            "target": self.cmd.target,
            "parent_cmd": self.parent_duties,
            "child_cmd": self.child_duties,
        }
