// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// 映像ページ：映像サーバー（video.py）から JPEG を受けて描画する。docs/protocol_video.md
// 操縦はできないが、非常停止だけはどのページからでも送れる（CLAUDE.md §5）。
import { $, attachControl, setPill } from "./common.js";
import { RateMeter, isStale, parseParams, videoUrl } from "./video_core.js";

const params = parseParams(location.search, { cam: "1", fps: 15, port: "8081" });
const canvas = $("view");
const ctx = canvas.getContext("2d");
const meter = new RateMeter();
let videoWs = null;
let lastFrame = null;

// ---- 映像 ----

function fillSelect(el, items, value) {
  el.innerHTML = "";
  for (const { value: v, label } of items) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = label;
    el.append(o);
  }
  el.value = String(value);
}

function onHello(m) {
  params.fps = m.fps;
  document.title = `映像 ${m.label}`;
  fillSelect($("cam"), m.cameras.map((c) => ({ value: c.id, label: c.label })), m.cam);
  fillSelect($("fps"), m.fps_options.map((f) => ({ value: f, label: `${f} fps` })), m.fps);
  saveUrl();
}

function saveUrl() {
  const q = new URLSearchParams(location.search);
  q.set("cam", params.cam);
  q.set("fps", params.fps);
  history.replaceState(null, "", `?${q}`);
}

async function onFrame(ws, blob) {
  try {
    const bitmap = await createImageBitmap(blob);
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    ctx.drawImage(bitmap, 0, 0);
    bitmap.close();
    lastFrame = performance.now();
    meter.add(lastFrame, blob.size);
  } catch (e) {
    console.warn("フレームを描画できません", e);
  } finally {
    // 描画してから次を受ける。遅いときはサーバーが古いフレームを捨てる
    if (ws.readyState === WebSocket.OPEN) ws.send('{"t":"ack"}');
  }
}

function connectVideo() {
  const ws = new WebSocket(videoUrl(location, params));
  ws.binaryType = "blob";
  videoWs = ws;
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") {
      onFrame(ws, ev.data);
      return;
    }
    const m = JSON.parse(ev.data);
    if (m.t === "hello") onHello(m);
    else if (m.t === "fps") { params.fps = m.fps; $("fps").value = String(m.fps); saveUrl(); }
  };
  ws.onclose = () => setTimeout(connectVideo, 1000);
}

function updateVideoState() {
  const now = performance.now();
  const stale = isStale(lastFrame, now);
  $("no-video").hidden = !stale;
  if (stale) {
    setPill($("rate"), "映像なし", "bad");
  } else {
    const r = meter.rate(now);
    setPill($("rate"), `${r.fps.toFixed(0)} fps / ${r.mbps.toFixed(0)} Mbps`, "ok");
  }
}

// ---- 起動 ----

$("fps").onchange = (e) => {
  if (videoWs?.readyState === WebSocket.OPEN) videoWs.send(JSON.stringify({ t: "fps", fps: Number(e.target.value) }));
};
$("cam").onchange = (e) => {
  params.cam = e.target.value;
  saveUrl();
  location.reload();
};
connectVideo();
attachControl({ button: $("estop"), pill: $("control"), banner: $("estop-banner") });
setInterval(updateVideoState, 200);
updateVideoState();
