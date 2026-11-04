// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

import assert from "node:assert/strict";
import test from "node:test";
import { RateMeter, isStale, parseParams, videoUrl } from "../video_core.js";

const defaults = { cam: "1", fps: 15, port: "8081" };

test("parseParams uses defaults and query", () => {
  assert.deepEqual(parseParams("", defaults), defaults);
  assert.deepEqual(parseParams("?cam=2&fps=5&vport=9000", defaults), { cam: "2", fps: 5, port: "9000" });
  assert.equal(parseParams("?fps=abc", defaults).fps, 15);
});

test("videoUrl targets the video port on the same host", () => {
  const url = videoUrl({ protocol: "http:", hostname: "192.168.0.1" }, { cam: "2", fps: 10, port: "8081" });
  assert.equal(url, "ws://192.168.0.1:8081/ws?cam=2&fps=10");
});

test("no frame yet or old frame is stale", () => {
  assert.equal(isStale(null, 1000), true);
  assert.equal(isStale(1000, 2000), false);
  assert.equal(isStale(1000, 2600), true);
});

test("RateMeter reports fps and Mbps over its window", () => {
  const m = new RateMeter(1000);
  for (let t = 0; t < 1000; t += 100) m.add(t, 125000);
  assert.deepEqual(m.rate(999), { fps: 10, mbps: 10 });
  assert.equal(m.rate(5000).fps, 0);
});
