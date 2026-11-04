// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// マップページ：SLAM の地図・現在位置・LiDAR の点を描く。docs/protocol_gateway.md
import { $, attachControl, connectGateway, setPill } from "./common.js";
import { cellsToRgba, fitView, scanPoints, worldToScreen, zoomAt } from "./map_core.js";

const canvas = $("map");
const ctx = canvas.getContext("2d");
const offscreen = document.createElement("canvas");
const st = { map: null, pose: null, points: [], view: null, sensors: null, online: false, follow: true };

function onMap(m) {
  const cells = Uint8Array.from(atob(m.cells), (c) => c.charCodeAt(0));
  offscreen.width = m.w;
  offscreen.height = m.h;
  const off = offscreen.getContext("2d");
  const image = off.createImageData(m.w, m.h);
  cellsToRgba(cells, image.data);
  off.putImageData(image, 0, 0);
  st.map = m;
  if (st.follow) st.view = fitView(m, canvas.width, canvas.height);
}

function draw() {
  const W = canvas.width;
  const H = canvas.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#15181c";
  ctx.fillRect(0, 0, W, H);
  if (!st.map || !st.view) return;
  const { map: m, view: v } = st;
  // 占有格子は下の行から並ぶので、y を反転して描く
  ctx.imageSmoothingEnabled = false;
  ctx.setTransform(v.scale * m.res, 0, 0, -v.scale * m.res,
    W / 2 + (m.ox - v.cx) * v.scale, H / 2 - (m.oy - v.cy) * v.scale);
  ctx.drawImage(offscreen, 0, 0);
  ctx.setTransform(1, 0, 0, 1, 0, 0);

  const dot = Math.max(2, devicePixelRatio * 1.5);
  ctx.fillStyle = "#e5534b";
  for (const [x, y] of st.points) {
    const [sx, sy] = worldToScreen(v, W, H, x, y);
    ctx.fillRect(sx - dot / 2, sy - dot / 2, dot, dot);
  }

  if (st.pose) {
    const [sx, sy] = worldToScreen(v, W, H, st.pose.x, st.pose.y);
    const size = 14 * devicePixelRatio;
    ctx.translate(sx, sy);
    ctx.rotate(-st.pose.yaw); // 画面の y は下向き
    ctx.beginPath();
    ctx.moveTo(size, 0);
    ctx.lineTo(-size * 0.7, size * 0.6);
    ctx.lineTo(-size * 0.7, -size * 0.6);
    ctx.closePath();
    ctx.fillStyle = "#4c8dd6";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = devicePixelRatio;
    ctx.fill();
    ctx.stroke();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }
}

function resize() {
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(r.width * devicePixelRatio));
  canvas.height = Math.max(1, Math.round(r.height * devicePixelRatio));
  if (st.map && st.follow) st.view = fitView(st.map, canvas.width, canvas.height);
}

function renderState() {
  const s = st.sensors;
  let notice = null;
  let cls = "bad";
  if (!st.online) {
    setPill($("slam"), "ROS 未接続", "bad");
    notice = "ROS 未接続（ゲートウェイに接続できません）";
  } else if (!s?.ros) {
    setPill($("slam"), "ROS 未接続", "bad");
    notice = "ROS 未接続（操縦には影響しません）";
  } else if (!s.slam) {
    setPill($("slam"), "SLAM 停止", "bad");
    notice = "SLAM が動いていません";
  } else if (!s.lidar.wanted) {
    setPill($("slam"), "LiDAR OFF", "warn");
    notice = "LiDAR が OFF です。地図は保持され、ON にすると再開します";
    cls = "warn";
  } else if (s.lidar.scan_hz === 0) {
    setPill($("slam"), "スキャンなし", "bad");
    notice = "LiDAR のスキャンが届いていません";
  } else {
    setPill($("slam"), `SLAM 動作中 / ${s.lidar.scan_hz.toFixed(0)} Hz`, "ok");
  }
  $("notice").hidden = !notice;
  if (notice) {
    $("notice").textContent = notice;
    $("notice").className = `banner ${cls === "bad" ? "bad" : ""}`;
  }
  $("save").disabled = !st.map;
  $("reset").disabled = !s?.slam;
}

let resultTimer = null;
function showResult(text, bad) {
  $("result").textContent = text;
  $("result").className = `result ${bad ? "bad" : ""}`;
  clearTimeout(resultTimer);
  resultTimer = setTimeout(() => { $("result").textContent = ""; }, 8000);
}

const gateway = connectGateway({
  onOpen: () => { st.online = true; renderState(); },
  onClose: () => {
    st.online = false;
    st.sensors = null;
    st.pose = null;
    st.points = [];
    renderState();
  },
  onMessage: (m) => {
    if (m.t === "map") onMap(m);
    else if (m.t === "map_clear") { st.map = null; st.points = []; }
    else if (m.t === "pose") st.pose = m.pose;
    else if (m.t === "scan") st.points = scanPoints(m);
    else if (m.t === "sensors") {
      st.sensors = m;
      if (!m.lidar.wanted || m.lidar.scan_hz === 0) st.points = []; // 古い点を生きているように見せない
      renderState();
    } else if (m.t === "result") {
      if (m.op === "map_save") showResult(m.ok ? `保存しました：${m.path}` : `保存できません：${m.error}`, !m.ok);
      if (m.op === "map_reset") showResult(m.ok ? "地図をリセットしました" : `リセットできません：${m.error}`, !m.ok);
    }
  },
});

$("save").onclick = () => gateway.send({ t: "map_save" });
$("reset").onclick = () => {
  if (window.confirm("地図を消して作り直します。よろしいですか？")) gateway.send({ t: "map_reset" });
};
$("fit").onclick = () => {
  st.follow = true;
  if (st.map) st.view = fitView(st.map, canvas.width, canvas.height);
};

canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  if (!st.view) return;
  st.follow = false;
  const r = canvas.getBoundingClientRect();
  st.view = zoomAt(st.view, canvas.width, canvas.height, (e.clientX - r.left) * devicePixelRatio,
    (e.clientY - r.top) * devicePixelRatio, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener("pointerup", () => { drag = null; });
canvas.addEventListener("pointermove", (e) => {
  if (!drag || !st.view) return;
  st.follow = false;
  st.view = { ...st.view,
    cx: st.view.cx - ((e.clientX - drag[0]) * devicePixelRatio) / st.view.scale,
    cy: st.view.cy + ((e.clientY - drag[1]) * devicePixelRatio) / st.view.scale };
  drag = [e.clientX, e.clientY];
});

attachControl({ button: $("estop"), pill: $("control"), banner: $("estop-banner") });
new ResizeObserver(resize).observe(canvas);
resize();
renderState();
setInterval(renderState, 1000);
(function loop() { draw(); requestAnimationFrame(loop); })();
