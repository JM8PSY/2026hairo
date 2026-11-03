// 入力（ゲームパッド・キーボード）→ 軸の値（-1〜1）への変換。DOM に依存しない（node --test で検査する）。

export const PARENT_AXES = ["left", "right", "sub_front", "sub_rear", "lid", "reel"];
export const CHILD_AXES = ["left", "right", "brush"];

export function applyDeadzone(v, dz) {
  if (!Number.isFinite(v)) return 0;
  const a = Math.abs(v);
  if (a < dz) return 0;
  // デッドゾーンの外側を 0〜1 に引き伸ばす
  return Math.sign(v) * Math.min(1, (a - dz) / (1 - dz));
}

function buttonValue(pad, idx) {
  const b = pad.buttons[idx];
  if (!b) return 0;
  return typeof b === "object" ? (b.value || (b.pressed ? 1 : 0)) : Number(b);
}

// ゲームパッドの状態（{axes: [], buttons: [{pressed, value}]}）から軸の値を作る
export function readGamepad(pad, map, deadzone) {
  const out = {};
  for (const [name, m] of Object.entries(map)) {
    let v = 0;
    if (m.axis !== undefined) {
      v = pad.axes[m.axis] ?? 0;
      if (m.invert) v = -v;
    } else {
      v = buttonValue(pad, m.plus) - buttonValue(pad, m.minus);
    }
    out[name] = applyDeadzone(Math.max(-1, Math.min(1, v)), deadzone);
  }
  return out;
}

// 押されているキー（Set of KeyboardEvent.code）から軸の値を作る
export function readKeyboard(keys, map, speed) {
  const out = {};
  for (const [name, m] of Object.entries(map)) {
    out[name] = ((keys.has(m.plus) ? 1 : 0) - (keys.has(m.minus) ? 1 : 0)) * speed;
  }
  return out;
}

// ふたを閉じる操作（lid < 0）が holdMs 以上続いたら confirm にする
export class LidConfirm {
  constructor(holdMs) {
    this.holdMs = holdMs;
    this.since = null;
  }
  update(lid, nowMs) {
    if (lid < 0) {
      if (this.since === null) this.since = nowMs;
      return nowMs - this.since >= this.holdMs;
    }
    this.since = null;
    return false;
  }
  progress(nowMs) {
    return this.since === null ? 0 : Math.min(1, (nowMs - this.since) / this.holdMs);
  }
}

// 「押した瞬間」を検出する（押しっぱなしで連続発火しない）
export class EdgeDetector {
  constructor() {
    this.prev = false;
  }
  rising(pressed) {
    const r = pressed && !this.prev;
    this.prev = pressed;
    return r;
  }
}

export function zeros(names) {
  return Object.fromEntries(names.map((n) => [n, 0]));
}
