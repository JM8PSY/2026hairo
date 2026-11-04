// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

import assert from "node:assert/strict";
import test from "node:test";
import { cellColor, cellsToRgba, fitView, scanPoints, screenToWorld, worldToScreen, zoomAt } from "../map_core.js";

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test("cell colors distinguish unknown, free and occupied", () => {
  assert.notDeepEqual(cellColor(255), cellColor(0));
  assert.notDeepEqual(cellColor(0), cellColor(100));
  assert.deepEqual(cellColor(50), cellColor(0));
  assert.deepEqual(cellColor(51), cellColor(100));
});

test("cellsToRgba writes opaque pixels", () => {
  const out = cellsToRgba(Uint8Array.of(0, 255), new Uint8ClampedArray(8));
  assert.equal(out[3], 255);
  assert.deepEqual([...out.slice(4, 7)], cellColor(255));
});

test("fitView centers the map and keeps it inside", () => {
  const m = { w: 100, h: 50, res: 0.1, ox: -5, oy: -2 };
  const v = fitView(m, 1000, 1000, 1);
  assert.deepEqual([v.cx, v.cy, v.scale], [0, 0.5, 100]);
  assert.deepEqual(worldToScreen(v, 1000, 1000, -5, 0.5), [0, 500]);
});

test("y points up on screen and conversions are inverse", () => {
  const v = { cx: 1, cy: 2, scale: 50 };
  const [, up] = worldToScreen(v, 800, 600, 1, 3);
  assert.ok(up < 300);
  const [x, y] = screenToWorld(v, 800, 600, ...worldToScreen(v, 800, 600, 4, -7));
  near(x, 4);
  near(y, -7);
});

test("zoom keeps the point under the cursor", () => {
  const v = { cx: 0, cy: 0, scale: 100 };
  const before = screenToWorld(v, 800, 600, 700, 100);
  const after = screenToWorld(zoomAt(v, 800, 600, 700, 100, 1.5), 800, 600, 700, 100);
  near(after[0], before[0]);
  near(after[1], before[1]);
});

test("scanPoints applies laser pose and skips invalid ranges", () => {
  const pts = scanPoints({ angle_min: 0, angle_inc: Math.PI / 2, ranges: [100, 0, 200],
    laser: { x: 1, y: 1, yaw: Math.PI / 2 } });
  assert.equal(pts.length, 2);
  near(pts[0][0], 1);
  near(pts[0][1], 2);
  near(pts[1][0], 1);
  near(pts[1][1], -1);
});
