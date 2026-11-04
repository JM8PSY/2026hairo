// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

import assert from "node:assert/strict";
import test from "node:test";
import { videoUrl } from "../video_core.js";
import { makeQuad, makeSphere, perspective, rotationOnly } from "../vr_core.js";

const near = (a, b, eps = 1e-5) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

function vertexAt(sphere, lonSegments, i, j) {
  const k = (j * (lonSegments + 1) + i) * 5;
  return [...sphere.vertices.slice(k, k + 5)];
}

test("image center is straight ahead, right of the image is +X, top is up", () => {
  const s = makeSphere(10, 4, 2);
  const [fx, fy, fz, fu, fv] = vertexAt(s, 4, 2, 1); // u=0.5, v=0.5
  near(fx, 0);
  near(fy, 0);
  near(fz, -10);
  assert.deepEqual([fu, fv], [0.5, 0.5]);
  const right = vertexAt(s, 4, 3, 1); // u=0.75
  near(right[0], 10);
  near(right[2], 0);
  near(vertexAt(s, 4, 0, 0)[1], 10); // v=0 が真上
});

test("sphere has the expected number of vertices and valid indices", () => {
  const s = makeSphere(10, 8, 4);
  assert.equal(s.vertices.length, 9 * 5 * 5);
  assert.equal(s.indices.length, 8 * 4 * 6);
  assert.ok(Math.max(...s.indices) < 45);
});

test("quad faces the viewer with the text upright", () => {
  const q = makeQuad(2, 1, -3);
  assert.deepEqual([...q.vertices.slice(0, 5)], [-1, 0.5, -3, 0, 0]); // 左上が画像の左上
});

test("rotationOnly removes head movement", () => {
  const m = Float32Array.of(1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 1);
  const r = rotationOnly(m);
  assert.deepEqual([...r.slice(12)], [0, 0, 0, 1]);
  assert.deepEqual([...r.slice(0, 12)], [...m.slice(0, 12)]);
});

test("perspective maps a point ahead to the center of the screen", () => {
  const p = perspective(90, 2, 0.1, 100);
  near(p[0], 0.5);
  near(p[5], 1);
  assert.equal(p[11], -1);
});

test("videoUrl works with the page's own port and with no port", () => {
  const loc = { protocol: "https:", hostname: "10.0.0.1" };
  assert.equal(videoUrl(loc, { cam: "1", fps: 15, port: "8443" }), "wss://10.0.0.1:8443/ws?cam=1&fps=15");
  assert.equal(videoUrl(loc, { cam: "1", fps: 15, port: "" }), "wss://10.0.0.1/ws?cam=1&fps=15");
});
