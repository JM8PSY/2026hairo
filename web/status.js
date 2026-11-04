// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// センサーと状態のページ。センサーはゲートウェイ（gateway.py）、モーターと通信は操縦サーバー（app.py）から受ける。
import { $, attachControl, connectGateway, renderOuts, setPill } from "./common.js";

const PARENT_NAMES = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"];
const CHILD_NAMES = ["C1", "C2", "C3"];

function fmt(value, digits, unit) {
  return value === null || value === undefined ? "—" : `${value.toFixed(digits)} ${unit}`;
}

let sensors = null;
let online = false;
let busy = false;

function renderSensors() {
  const s = sensors;
  const lidar = s?.lidar;
  $("lidar-on").disabled = busy || !s?.ros || !lidar?.driver || lidar.wanted;
  $("lidar-off").disabled = busy || !s?.ros || !lidar?.driver || !lidar.wanted;
  if (!online) setPill($("lidar-state"), "ゲートウェイ未接続", "bad");
  else if (!s?.ros) setPill($("lidar-state"), "ROS 未接続", "bad");
  else if (!lidar.driver) setPill($("lidar-state"), "ドライバ停止", "bad");
  else if (!lidar.wanted) setPill($("lidar-state"), lidar.scan_hz > 0 ? "停止中…" : "OFF", "warn");
  else if (lidar.scan_hz === 0) setPill($("lidar-state"), "スキャンなし", "bad");
  else setPill($("lidar-state"), `ON / ${lidar.scan_hz.toFixed(0)} Hz`, "ok");
  setPill($("slam-state"), !s?.slam ? "停止" : "動作中", s?.slam ? "ok" : "");
  const sys = s?.system;
  $("temp").textContent = fmt(sys?.temp_c, 1, "℃");
  $("cpu").textContent = fmt(sys?.cpu_pct, 0, "%");
  $("mem").textContent = fmt(sys?.mem_pct, 0, "%");
}

function renderControl(m) {
  const core = m?.core;
  $("core-state").textContent = !core ? "—" : core.estop ? "非常停止" : core.armed ? "動作中（ARM）" : "停止";
  $("stop-reason").textContent = core?.stop_reason || "—";
  const p = m?.parent;
  setPill($("p-conn"), p?.connected ? "接続" : "未接続", p?.connected ? "ok" : "bad");
  $("p-state").textContent = p?.connected
    ? `${p.state}（${p.reason}）${p.fault ? ` fault=0x${p.fault.toString(16)}` : ""}` : (p?.error || "—");
  const lim = p?.limits ?? 0;
  $("p-lid").textContent = p?.connected ? (`${lim & 1 ? "開リミット作動 " : ""}${lim & 2 ? "閉リミット作動" : ""}` || "途中") : "—";
  renderOuts($("p-outs"), PARENT_NAMES, p?.outputs, core?.parent_cmd);
  const c = m?.child;
  setPill($("c-conn"), c?.connected ? "接続" : "未接続", c?.connected ? "ok" : "bad");
  $("c-state").textContent = c?.connected ? (c.esp_connected ? `${c.esp_state}（${c.phase}）` : "ESP32 未接続") : "—";
  $("c-link").textContent = c?.connected
    ? `往復 ${c.rtt_ms?.toFixed(0) ?? "—"} ms / ロス ${c.loss == null ? "—" : (c.loss * 100).toFixed(0) + "%"}` : "—";
  renderOuts($("c-outs"), CHILD_NAMES, c?.outputs, core?.child_cmd);
}

const gateway = connectGateway({
  onOpen: () => { online = true; renderSensors(); },
  onClose: () => { online = false; sensors = null; busy = false; renderSensors(); },
  onMessage: (m) => {
    if (m.t === "sensors") {
      sensors = m;
      renderSensors();
    } else if (m.t === "result" && m.op === "lidar") {
      busy = false;
      $("lidar-error").textContent = m.ok ? "" : `切り替えできません：${m.error}`;
      renderSensors();
    }
  },
});

function setLidar(on) {
  if (gateway.send({ t: "lidar", on })) {
    busy = true;
    $("lidar-error").textContent = "";
    renderSensors();
  }
}
$("lidar-on").onclick = () => setLidar(true);
$("lidar-off").onclick = () => setLidar(false);

attachControl({ button: $("estop"), pill: $("control"), banner: $("estop-banner"), onStatus: renderControl });
renderControl(null);
renderSensors();
