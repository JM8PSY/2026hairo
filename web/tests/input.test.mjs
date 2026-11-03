// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// node --test web/tests
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { applyDeadzone, EdgeDetector, LidConfirm, readGamepad, readKeyboard } from "../input.js";

const km = JSON.parse(readFileSync(new URL("../keymap.json", import.meta.url)));

function pad(axes = [], pressed = []) {
  const buttons = Array.from({ length: 17 }, (_, i) => ({ pressed: pressed.includes(i), value: pressed.includes(i) ? 1 : 0 }));
  return { axes: [0, 0, 0, 0].map((v, i) => axes[i] ?? v), buttons };
}

test("deadzone", () => {
  assert.equal(applyDeadzone(0.05, 0.1), 0);
  assert.equal(applyDeadzone(1, 0.1), 1);
  assert.equal(applyDeadzone(-1, 0.1), -1);
  assert.ok(Math.abs(applyDeadzone(0.55, 0.1) - 0.5) < 1e-9);
  assert.equal(applyDeadzone(NaN, 0.1), 0);
});

test("gamepad parent mapping (stick up = forward)", () => {
  const v = readGamepad(pad([0, -1, 0, 1], [12, 3]), km.gamepad.parent, km.deadzone);
  assert.equal(v.left, 1);
  assert.equal(v.right, -1);
  assert.equal(v.sub_front, 1);
  assert.equal(v.lid, 1);
  assert.equal(v.reel, 0);
});

test("gamepad child mapping", () => {
  const v = readGamepad(pad([0, -0.5, 0, 0], [7]), km.gamepad.child, km.deadzone);
  assert.ok(v.left > 0.4 && v.left < 0.5);
  assert.equal(v.brush, 1);
});

test("keyboard mapping", () => {
  const v = readKeyboard(new Set(["KeyW", "KeyK"]), km.keyboard.parent, km.keyboard.speed);
  assert.equal(v.left, km.keyboard.speed);
  assert.equal(v.right, -km.keyboard.speed);
  assert.equal(v.reel, 0);
});

test("every axis has gamepad and keyboard bindings", () => {
  for (const t of ["parent", "child"]) {
    assert.deepEqual(Object.keys(km.gamepad[t]).sort(), Object.keys(km.keyboard[t]).sort());
  }
});

test("lid close needs hold", () => {
  const l = new LidConfirm(1000);
  assert.equal(l.update(-1, 0), false);
  assert.equal(l.update(-1, 999), false);
  assert.equal(l.update(-1, 1000), true);
  assert.equal(l.update(0, 1100), false); // 離すとやり直し
  assert.equal(l.update(-1, 1200), false);
  assert.equal(l.update(1, 1300), false); // 開く方向は関係ない
});

test("edge detector", () => {
  const e = new EdgeDetector();
  assert.deepEqual([true, true, false, true].map((p) => e.rising(p)), [true, false, false, true]);
});
