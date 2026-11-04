// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// 操縦 Web UI。docs/protocol_web.md の WebSocket プロトコルで親機と話す。
// 安全（CLAUDE.md §5）：操縦者は 50Hz で cmd を送り続ける。タブ非表示・フォーカス喪失・
// ゲームパッド切断のときは ok=false を送り、サーバーが全機停止する。再開は ARM ボタンから。
import { $, renderOuts, setPill } from "./common.js";
import {
  CHILD_AXES, EdgeDetector, LidConfirm, PARENT_AXES, readGamepad, readKeyboard, zeros,
} from "./input.js";

const SEND_MS = 20;
const PARENT_NAMES = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"];
const CHILD_NAMES = ["C1", "C2", "C3"];
const AXIS_LABELS = {
  left: "左クローラー", right: "右クローラー", sub_front: "サブクローラー前", sub_rear: "サブクローラー後",
  lid: "ふた", reel: "リール", brush: "ブラシ",
};
const STOP_REASONS = {
  startup: "起動直後", heartbeat_timeout: "通信途絶（ハートビート）", operator_disconnected: "操縦者が切断",
  released: "操縦権を返した", operator_disarm: "停止ボタン", estop: "非常停止", cleared: "非常停止を解除",
  hidden: "タブが非表示", blur: "ウィンドウのフォーカス喪失", gamepad_disconnected: "ゲームパッド切断",
};

const st = {
  ws: null,
  role: "viewer",
  target: "parent",
  keymap: null,
  keys: new Set(),
  gamepadIndex: null,
  gamepadLost: false,
  focused: document.hasFocus(),
  status: null,
  lid: null,
  edges: { estop: new EdgeDetector(), toggle: new EdgeDetector() },
};

// ---- 接続 ----

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  st.ws = ws;
  ws.onopen = () => setPill($("conn"), "接続中", "ok");
  ws.onclose = () => {
    setPill($("conn"), "未接続", "bad");
    st.role = "viewer";
    st.status = null;
    render();
    setTimeout(connect, 1000);
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.t === "hello" || m.t === "role") st.role = m.role;
    else if (m.t === "status") { st.status = m; st.role = m.role; }
    else if (m.t === "error") flash(`エラー: ${m.error}`);
    render();
  };
}

function send(msg) {
  if (st.ws && st.ws.readyState === WebSocket.OPEN) st.ws.send(JSON.stringify(msg));
}

function estop() {
  send({ t: "estop" });
}

// ---- 入力 ----

function currentPad() {
  if (st.gamepadIndex === null) return null;
  return navigator.getGamepads()[st.gamepadIndex] || null;
}

function okState() {
  if (document.hidden) return [false, "hidden"];
  if (!st.focused) return [false, "blur"];
  if (st.gamepadLost) return [false, "gamepad_disconnected"];
  return [true, null];
}

function readAxes(now) {
  const km = st.keymap;
  const pad = currentPad();
  let parent = zeros(PARENT_AXES);
  let child = zeros(CHILD_AXES);
  if (pad) {
    const g = km.gamepad;
    if (st.edges.estop.rising(!!pad.buttons[g.estop]?.pressed)) estop();
    if (st.edges.toggle.rising(!!pad.buttons[g.toggle_target]?.pressed)) toggleTarget();
    if (st.target === "parent") parent = readGamepad(pad, g.parent, km.deadzone);
    else child = readGamepad(pad, g.child, km.deadzone);
  } else {
    const k = km.keyboard;
    if (st.target === "parent") parent = readKeyboard(st.keys, k.parent, k.speed);
    else child = readKeyboard(st.keys, k.child, k.speed);
  }
  const lidConfirm = st.target === "parent" && st.lid.update(parent.lid, now);
  return { parent, child, lidConfirm };
}

function tick() {
  if (!st.keymap) return;
  const now = performance.now();
  const { parent, child, lidConfirm } = readAxes(now);
  const holding = st.target === "parent" && parent.lid < 0;
  $("lid-hold").hidden = !holding;
  $("lid-hold-bar").style.width = `${st.lid.progress(now) * 100}%`;
  if (st.role !== "operator") return;
  const [ok, why] = okState();
  send({ t: "cmd", ok, why, target: st.target, parent, child, lid_confirm: lidConfirm });
}

function toggleTarget() {
  st.target = st.target === "parent" ? "child" : "parent";
  render();
  renderKeymap();
}

// ---- 表示 ----

let flashText = null;
let flashUntil = 0;
function flash(text) {
  flashText = text;
  flashUntil = performance.now() + 3000;
}

function render() {
  const s = st.status;
  const op = st.role === "operator";
  setPill($("role"), op ? "操縦者" : "閲覧", op ? "ok" : "");
  setPill($("input"), currentPad() ? `入力：ゲームパッド` : "入力：キーボード", st.gamepadLost ? "bad" : "");
  $("t-parent").classList.toggle("on", st.target === "parent");
  $("t-child").classList.toggle("on", st.target === "child");

  const core = s?.core;
  for (const id of ["release", "arm", "disarm", "clear"]) $(id).disabled = !op;
  $("take").disabled = op || !!core?.operator;
  $("arm").disabled = !op || !!core?.estop;

  let banner = null;
  let bannerCls = "banner";
  const [ok, why] = okState();
  if (core?.estop) { banner = "非常停止中 — 「非常停止の解除」→「ARM」で再開"; bannerCls += " bad"; }
  else if (op && !ok) { banner = `停止中：${STOP_REASONS[why]}。戻ったら ARM で再開`; bannerCls += " bad"; }
  else if (core?.armed && core.need_neutral) banner = "入力をニュートラルに戻してください（戻すまで動きません）";
  else if (op && core && !core.armed) banner = "停止中 — ARM で動作開始";
  if (performance.now() < flashUntil) {
    banner = flashText;
    bannerCls = "banner bad";
  }
  $("banner").hidden = !banner;
  if (banner) {
    $("banner").textContent = banner;
    $("banner").className = bannerCls;
  }

  $("core-state").textContent = !core ? "—" : core.estop ? "非常停止" : core.armed ? "動作中（ARM）" : "停止";
  $("stop-reason").textContent = core?.stop_reason ? (STOP_REASONS[core.stop_reason] || core.stop_reason) : "—";

  const p = s?.parent;
  setPill($("p-conn"), p?.connected ? "接続" : "未接続", p?.connected ? "ok" : "bad");
  $("p-state").textContent = p?.connected ? `${p.state}（${p.reason}）${p.fault ? ` fault=0x${p.fault.toString(16)}` : ""}` : (p?.error || "—");
  const lim = p?.limits ?? 0;
  $("p-lid").textContent = p?.connected ? `${lim & 1 ? "開リミット作動 " : ""}${lim & 2 ? "閉リミット作動" : ""}` || "途中" : "—";
  renderOuts($("p-outs"), PARENT_NAMES, p?.outputs, core?.parent_cmd);

  const c = s?.child;
  setPill($("c-conn"), c?.connected ? "接続" : "未接続", c?.connected ? "ok" : "bad");
  $("c-state").textContent = c?.connected ? (c.esp_connected ? `${c.esp_state}（${c.phase}）` : "ESP32 未接続") : "—";
  $("c-link").textContent = c?.connected ? `往復 ${c.rtt_ms?.toFixed(0) ?? "—"} ms / ロス ${c.loss == null ? "—" : (c.loss * 100).toFixed(0) + "%"}` : "—";
  renderOuts($("c-outs"), CHILD_NAMES, c?.outputs, core?.child_cmd);
}

function renderKeymap() {
  const km = st.keymap;
  if (!km) return;
  const t = st.target;
  $("km-target").textContent = t === "parent" ? "親機" : "子機";
  const rows = Object.keys(km.gamepad[t]).map((k) =>
    `<tr><td>${AXIS_LABELS[k] || k}</td><td>${km.gamepad[t][k].label}</td><td>${km.keyboard[t][k]?.label ?? ""}</td></tr>`);
  rows.unshift(`<tr><td>非常停止</td><td>Back（ボタン ${km.gamepad.estop}）</td><td>${km.keyboard.estop}</td></tr>`);
  rows.push(`<tr><td>操作対象の切替</td><td>Start（ボタン ${km.gamepad.toggle_target}）</td><td>${km.keyboard.toggle_target}</td></tr>`);
  $("km").querySelector("tbody").innerHTML = rows.join("");
}

// ---- イベント ----

function bind() {
  $("estop").onclick = estop;
  $("take").onclick = () => send({ t: "take_control" });
  $("release").onclick = () => send({ t: "release_control" });
  $("arm").onclick = () => {
    st.gamepadLost = false; // 操作者が明示的に再開した
    send({ t: "arm" });
  };
  $("disarm").onclick = () => send({ t: "disarm" });
  $("clear").onclick = () => send({ t: "clear" });
  const openWindow = (path, name) => window.open(path, `hairo-${name}`, "popup,width=1280,height=720");
  $("open-cam1").onclick = () => openWindow("/video?cam=1", "cam1");
  $("open-cam2").onclick = () => openWindow("/video?cam=2", "cam2");
  $("open-map").onclick = () => openWindow("/map", "map");
  $("open-status").onclick = () => openWindow("/status", "status");
  $("t-parent").onclick = () => { if (st.target !== "parent") toggleTarget(); };
  $("t-child").onclick = () => { if (st.target !== "child") toggleTarget(); };

  window.addEventListener("keydown", (e) => {
    if (e.code === st.keymap?.keyboard.estop) { e.preventDefault(); estop(); return; }
    if (e.code === st.keymap?.keyboard.toggle_target) { e.preventDefault(); toggleTarget(); return; }
    st.keys.add(e.code);
  });
  window.addEventListener("keyup", (e) => st.keys.delete(e.code));
  window.addEventListener("blur", () => { st.focused = false; st.keys.clear(); render(); });
  window.addEventListener("focus", () => { st.focused = true; render(); });
  document.addEventListener("visibilitychange", () => { st.keys.clear(); render(); });
  window.addEventListener("gamepadconnected", (e) => {
    if (st.gamepadIndex === null) st.gamepadIndex = e.gamepad.index;
    render();
  });
  window.addEventListener("gamepaddisconnected", (e) => {
    if (e.gamepad.index === st.gamepadIndex) {
      st.gamepadIndex = null;
      st.gamepadLost = true; // ARM し直すまで ok=false
      send({ t: "cmd", ok: false, why: "gamepad_disconnected", target: st.target,
             parent: zeros(PARENT_AXES), child: zeros(CHILD_AXES) });
    }
    render();
  });
}

async function main() {
  const res = await fetch("/static/keymap.json");
  st.keymap = await res.json();
  st.lid = new LidConfirm(st.keymap.lid_confirm_ms);
  bind();
  renderKeymap();
  render();
  connect();
  setInterval(tick, SEND_MS);
}

main();
