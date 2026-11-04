// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// マップの DOM に依存しない部分（node --test で検査する）。

const UNKNOWN = [58, 64, 72];
const FREE = [235, 238, 240];
const OCCUPIED = [15, 18, 21];

// 占有格子の1マス（0〜100、255 = 不明）の色
export function cellColor(v) {
  if (v === 255) return UNKNOWN;
  return v > 50 ? OCCUPIED : FREE;
}

// cells（1マス1バイト）を RGBA の配列にする
export function cellsToRgba(cells, out) {
  for (let i = 0; i < cells.length; i++) {
    const [r, g, b] = cellColor(cells[i]);
    out[i * 4] = r;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = b;
    out[i * 4 + 3] = 255;
  }
  return out;
}

// 地図全体が画面に収まる表示（中心 cx, cy と 1m あたりのピクセル数 scale）
export function fitView(map, width, height, margin = 0.95) {
  const w = map.w * map.res;
  const h = map.h * map.res;
  return { cx: map.ox + w / 2, cy: map.oy + h / 2, scale: Math.min(width / w, height / h) * margin };
}

// 世界座標（y が上）→ 画面座標（y が下）
export function worldToScreen(view, width, height, x, y) {
  return [width / 2 + (x - view.cx) * view.scale, height / 2 - (y - view.cy) * view.scale];
}

export function screenToWorld(view, width, height, sx, sy) {
  return [view.cx + (sx - width / 2) / view.scale, view.cy - (sy - height / 2) / view.scale];
}

// カーソルの下の点を動かさずに拡大・縮小する
export function zoomAt(view, width, height, sx, sy, factor) {
  const [wx, wy] = screenToWorld(view, width, height, sx, sy);
  const scale = view.scale * factor;
  return { scale, cx: wx - (sx - width / 2) / scale, cy: wy + (sy - height / 2) / scale };
}

// スキャン（距離はセンチメートル、0 = 無効）を世界座標の点にする
export function scanPoints(scan) {
  const { x, y, yaw } = scan.laser;
  const points = [];
  scan.ranges.forEach((cm, i) => {
    if (cm <= 0) return;
    const a = yaw + scan.angle_min + i * scan.angle_inc;
    const r = cm / 100;
    points.push([x + r * Math.cos(a), y + r * Math.sin(a)]);
  });
  return points;
}
