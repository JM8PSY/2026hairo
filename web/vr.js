// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// Meta Quest 用の VR ページ（見るだけ）。映像サーバー（video.py）がこのページも HTTPS で配信する。
// 操縦はできない。非常停止はページのボタンから映像サーバー経由で操縦サーバーへ送る。
import { $, setPill } from "./common.js";
import { RateMeter, isStale, parseParams, videoUrl } from "./video_core.js";
import { IDENTITY, makeQuad, makeSphere, perspective, rotationOnly } from "./vr_core.js";

const VERTEX_SHADER = `#version 300 es
in vec3 position;
in vec2 uv;
uniform mat4 projection;
uniform mat4 view;
out vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projection * view * vec4(position, 1.0);
}`;
const FRAGMENT_SHADER = `#version 300 es
precision mediump float;
in vec2 vUv;
uniform sampler2D image;
out vec4 color;
void main() {
  color = texture(image, vUv);
}`;
const NEAR = 0.1;
const FAR = 100;

const params = { ...parseParams(location.search, { cam: "1", fps: 15, port: "" }), port: location.port };
const canvas = $("view");
const gl = canvas.getContext("webgl2", { xrCompatible: true, antialias: false });
const meter = new RateMeter();
let videoWs = null;
let lastFrame = null;
let hasFrame = false;
let xrSession = null;
let xrSpace = null;

// ---- WebGL ----

function compile(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
  return shader;
}

const program = gl.createProgram();
gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX_SHADER));
gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
gl.linkProgram(program);
if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
gl.useProgram(program);
const projectionLoc = gl.getUniformLocation(program, "projection");
const viewLoc = gl.getUniformLocation(program, "view");

function makeMesh({ vertices, indices }) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, "position");
  const uv = gl.getAttribLocation(program, "uv");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 3, gl.FLOAT, false, 20, 0);
  gl.enableVertexAttribArray(uv);
  gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, 20, 12);
  gl.bindVertexArray(null);
  return { vao, count: indices.length };
}

function makeTexture() {
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return texture;
}

function makeNoticeTexture(text) {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 128;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.fillStyle = "#e5534b";
  ctx.font = "bold 72px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, c.width / 2, c.height / 2);
  const texture = makeTexture();
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c);
  return texture;
}

const sphere = makeMesh(makeSphere(10, 64, 32));
const quad = makeMesh(makeQuad(1.2, 0.3, -2));
const videoTexture = makeTexture();
const noticeTexture = makeNoticeTexture("映像なし");

function drawMesh(mesh, texture, projection, view) {
  gl.uniformMatrix4fv(projectionLoc, false, projection);
  gl.uniformMatrix4fv(viewLoc, false, view);
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.bindVertexArray(mesh.vao);
  gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_INT, 0);
}

function drawScene(projection, view) {
  // 止まった映像を生きているように見せない
  if (isStale(lastFrame, performance.now()) || !hasFrame) {
    drawMesh(quad, noticeTexture, projection, IDENTITY);
  } else {
    drawMesh(sphere, videoTexture, projection, view);
  }
}

function drawPreview() {
  if (xrSession) return;
  const dpr = devicePixelRatio;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width * dpr));
  const h = Math.max(1, Math.round(r.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.viewport(0, 0, w, h);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  drawScene(perspective(80, w / h, NEAR, FAR), IDENTITY);
  requestAnimationFrame(drawPreview);
}

// ---- WebXR ----

function onXrFrame(time, frame) {
  const session = frame.session;
  session.requestAnimationFrame(onXrFrame);
  const pose = frame.getViewerPose(xrSpace);
  if (!pose) return;
  const layer = session.renderState.baseLayer;
  gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  for (const view of pose.views) {
    const vp = layer.getViewport(view);
    gl.viewport(vp.x, vp.y, vp.width, vp.height);
    drawScene(view.projectionMatrix, rotationOnly(view.transform.inverse.matrix));
  }
}

async function enterVr() {
  try {
    const session = await navigator.xr.requestSession("immersive-vr");
    await gl.makeXRCompatible();
    session.updateRenderState({ baseLayer: new XRWebGLLayer(session, gl), depthNear: NEAR, depthFar: FAR });
    xrSpace = await session.requestReferenceSpace("local");
    xrSession = session;
    session.addEventListener("end", () => {
      xrSession = null;
      requestAnimationFrame(drawPreview);
    });
    session.requestAnimationFrame(onXrFrame);
  } catch (e) {
    showNotice(`VR を開始できません：${e.message}`);
  }
}

async function setupVrButton() {
  if (!window.isSecureContext) {
    showNotice("VR には HTTPS が必要です");
  } else if (!navigator.xr) {
    showNotice("このブラウザは VR に対応していません（画面には正面だけ表示します）");
  } else if (await navigator.xr.isSessionSupported("immersive-vr")) {
    $("enter").disabled = false;
  } else {
    showNotice("この機器では VR を使えません（画面には正面だけ表示します）");
  }
}

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

function saveUrl() {
  const q = new URLSearchParams(location.search);
  q.set("cam", params.cam);
  q.set("fps", params.fps);
  history.replaceState(null, "", `?${q}`);
}

function onHello(m) {
  params.fps = m.fps;
  document.title = `VR ${m.label}`;
  fillSelect($("cam"), m.cameras.map((c) => ({ value: c.id, label: c.label })), m.cam);
  fillSelect($("fps"), m.fps_options.map((f) => ({ value: f, label: `${f} fps` })), m.fps);
  saveUrl();
}

async function onFrame(ws, blob) {
  try {
    const bitmap = await createImageBitmap(blob);
    gl.bindTexture(gl.TEXTURE_2D, videoTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
    bitmap.close();
    hasFrame = true;
    lastFrame = performance.now();
    meter.add(lastFrame, blob.size);
  } catch (e) {
    console.warn("フレームを描画できません", e);
  } finally {
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

function updateRate() {
  const now = performance.now();
  if (isStale(lastFrame, now)) {
    setPill($("rate"), "映像なし", "bad");
  } else {
    const r = meter.rate(now);
    setPill($("rate"), `${r.fps.toFixed(0)} fps / ${r.mbps.toFixed(0)} Mbps`, "ok");
  }
}

// ---- 操作 ----

function showNotice(text) {
  $("notice").textContent = text;
  $("notice").hidden = false;
}

async function estop() {
  try {
    const response = await fetch("/estop", { method: "POST" });
    showNotice(response.ok ? "非常停止を送りました" : "操縦サーバーに接続できないため、非常停止を送れません");
  } catch {
    showNotice("映像サーバーに接続できないため、非常停止を送れません");
  }
}

$("enter").onclick = enterVr;
$("estop").onclick = estop;
$("fps").onchange = (e) => {
  if (videoWs?.readyState === WebSocket.OPEN) videoWs.send(JSON.stringify({ t: "fps", fps: Number(e.target.value) }));
};
$("cam").onchange = (e) => {
  params.cam = e.target.value;
  saveUrl();
  location.reload();
};
setupVrButton();
connectVideo();
setInterval(updateRate, 200);
updateRate();
requestAnimationFrame(drawPreview);
