// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// 映像ページの DOM に依存しない部分（node --test で検査する）。

export const STALE_MS = 1500;

export function parseParams(search, defaults) {
  const q = new URLSearchParams(search);
  const fps = Number.parseInt(q.get("fps"), 10);
  return {
    cam: q.get("cam") || defaults.cam,
    fps: Number.isFinite(fps) ? fps : defaults.fps,
    port: q.get("vport") || defaults.port,
  };
}

export function videoUrl(loc, params) {
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${loc.hostname}:${params.port}/ws?cam=${encodeURIComponent(params.cam)}&fps=${params.fps}`;
}

// 最後のフレームから一定時間過ぎたら「映像なし」（止まった映像を生きているように見せない）
export function isStale(lastFrameMs, nowMs, limitMs = STALE_MS) {
  return lastFrameMs === null || nowMs - lastFrameMs > limitMs;
}

// 直近 windowMs の fps と Mbps を求める
export class RateMeter {
  constructor(windowMs = 2000) {
    this.windowMs = windowMs;
    this.samples = [];
  }
  add(nowMs, bytes) {
    this.samples.push([nowMs, bytes]);
    this.trim(nowMs);
  }
  trim(nowMs) {
    while (this.samples.length && nowMs - this.samples[0][0] > this.windowMs) this.samples.shift();
  }
  rate(nowMs) {
    this.trim(nowMs);
    const seconds = this.windowMs / 1000;
    const bytes = this.samples.reduce((sum, s) => sum + s[1], 0);
    return { fps: this.samples.length / seconds, mbps: (bytes * 8) / seconds / 1e6 };
  }
}
