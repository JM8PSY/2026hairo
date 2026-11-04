// SPDX-FileCopyrightText: 2026 旭川工業高等専門学校 最先端テクノロジー同好会
// SPDX-License-Identifier: GPL-3.0-or-later

// 各ページで共通の表示と、操縦サーバーへの接続（非常停止はどのページからでも送れる。CLAUDE.md §5）。

export const $ = (id) => document.getElementById(id);

export function setPill(el, text, cls) {
  el.textContent = text;
  el.className = `pill ${cls || ""}`;
}

export function renderOuts(el, names, outs, cmds) {
  if (el.children.length !== names.length) {
    el.innerHTML = names.map((n) =>
      `<div class="out"><span>${n}</span><span class="track"><span class="fill"></span></span><span class="val"></span></div>`).join("");
  }
  names.forEach((_, i) => {
    const v = outs?.[i] ?? 0;
    const row = el.children[i];
    const fill = row.querySelector(".fill");
    const pct = Math.min(50, Math.abs(v) / 20);
    fill.style.left = v >= 0 ? "50%" : `${50 - pct}%`;
    fill.style.width = `${pct}%`;
    row.querySelector(".val").textContent = `${(v / 10).toFixed(0)}%` + (cmds && cmds[i] !== v ? "*" : "");
  });
}

// 非常停止ボタンと操縦サーバーの接続状態。onStatus には status メッセージをそのまま渡す
export function attachControl({ button, pill, banner, onStatus }) {
  let ws = null;
  let flashUntil = 0;
  let estopActive = false;

  function updateBanner() {
    const flashing = performance.now() < flashUntil;
    banner.hidden = !estopActive && !flashing;
    if (!flashing) banner.textContent = "非常停止中";
  }

  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => setPill(pill, "操縦サーバー接続中", "ok");
    ws.onclose = () => {
      setPill(pill, "操縦サーバー未接続", "bad");
      estopActive = false;
      updateBanner();
      onStatus?.(null);
      setTimeout(connect, 1000);
    };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.t !== "status") return;
      estopActive = !!m.core?.estop;
      updateBanner();
      onStatus?.(m);
    };
  }

  button.onclick = () => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send('{"t":"estop"}');
      return;
    }
    flashUntil = performance.now() + 3000;
    banner.textContent = "操縦サーバーに未接続のため、非常停止を送れません";
    banner.hidden = false;
    setTimeout(updateBanner, 3100);
  };
  connect();
}

// ゲートウェイ（gateway.py）に接続し続ける
export function connectGateway({ onMessage, onOpen, onClose, port }) {
  const gatewayPort = new URLSearchParams(location.search).get("gport") || port || "8082";
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const handle = { ws: null };
  function connect() {
    const ws = new WebSocket(`${scheme}://${location.hostname}:${gatewayPort}/ws`);
    handle.ws = ws;
    ws.onopen = () => onOpen?.();
    ws.onclose = () => {
      onClose?.();
      setTimeout(connect, 1000);
    };
    ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
  }
  connect();
  handle.send = (msg) => {
    if (handle.ws?.readyState !== WebSocket.OPEN) return false;
    handle.ws.send(JSON.stringify(msg));
    return true;
  };
  return handle;
}
