/* ============================================================
   fn-cocks — 前端逻辑（原生 JS，无依赖）
   ============================================================ */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const VIEWS = {
  overview: ["概览", "OVERVIEW"],
  subs: ["节点订阅", "SUBSCRIPTIONS"],
  nodes: ["节点列表", "NODES"],
  socks: ["SOCKS 配置", "SOCKS"],
  logs: ["运行日志", "LOGS"],
};

const state = {
  status: null,
  subs: [],
  nodes: [],
  groupFilter: "",
  search: "",
  view: "overview",
  logTimer: null,
  statusTimer: null,
};

/* ---------------- 基础工具 ---------------- */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function humanSize(v) {
  if (v == null || v === "" || isNaN(Number(v))) return "-";
  let n = Number(v);
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${Math.round(n)} ${units[i]}` : `${n.toFixed(2)} ${units[i]}`;
}

/* ---------------- API ---------------- */
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opt);
  let data = null;
  try { data = await resp.json(); } catch (e) { /* ignore */ }
  if (!resp.ok) {
    throw new Error((data && data.error) || `HTTP ${resp.status}`);
  }
  if (data && data.ok === false) {
    throw new Error(data.error || "操作失败");
  }
  return data || {};
}

/* ---------------- Toast ---------------- */
function toast(msg, type = "info", ms = 3200) {
  const wrap = $("#toast-wrap");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icons = { info: "ℹ", success: "✓", error: "✕" };
  el.innerHTML = `<span class="t-icon">${icons[type] || "ℹ"}</span><span>${esc(msg)}</span>`;
  wrap.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, ms);
}

/* ---------------- 视图切换 ---------------- */
function switchView(view) {
  state.view = view;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  const [zh, en] = VIEWS[view];
  $("#view-title").innerHTML = `${zh}<span class="en">${en}</span>`;
  if (view === "overview") loadStatus();
  if (view === "subs") loadSubs();
  if (view === "nodes") loadNodes();
  if (view === "socks") loadProxies();
  if (view === "logs") refreshLogs();
}

/* ---------------- 状态轮询 ---------------- */
async function loadStatus() {
  try {
    const d = await api("GET", "/api/status");
    state.status = d;
    renderStatus();
  } catch (e) { /* 静默 */ }
}

function renderStatus() {
  const d = state.status;
  if (!d) return;
  const pill = $("#core-pill");
  const coreRunning = !!(d.core && d.core.running);
  pill.classList.toggle("running", coreRunning);
  pill.classList.toggle("stopped", !coreRunning);
  $("#core-state").textContent = coreRunning
    ? `核心运行中 · PID ${d.core.pid}`
    : (d.core && d.core.last_error ? "核心异常" : "核心未运行");

  $("#ov-core").textContent = d.core && d.core.version ? d.core.version.split(" ")[0] : "—";
  $("#ov-core-ver").textContent = d.core && d.core.binary ? d.core.binary.split(/[\\/]/).pop() : "未找到 sing-box 核心";
  $("#ov-port").textContent = d.socks.enabled ? d.socks.port : "—";
  $("#ov-socks-state").textContent = d.socks.enabled ? `监听 ${d.socks.listen}` : "未启用";
  $("#ov-nodes").textContent = d.counts.nodes;
  $("#ov-subs").textContent = d.counts.subscriptions;
  $("#ov-active-node").textContent = d.active_node && d.active_node.name
    ? `当前节点：${d.active_node.name}`
    : "未选择当前节点";
  renderActiveNodePanel(d);
}

function renderActiveNodePanel(d) {
  const box = $("#ov-node-panel");
  const hint = $("#ov-node-hint");
  if (!d.active_node || !d.active_node.name) {
    box.innerHTML = `<div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.3 7.3l7.4 2.4M8.3 16.7l7.4-2.4"/></svg>
      <p>尚未选择节点</p>
      <div class="hint">前往「节点列表」选择一个节点作为当前节点，然后在 SOCKS 配置中启用代理</div>
    </div>`;
    hint.textContent = "";
    return;
  }
  hint.textContent = d.socks.enabled ? "SOCKS 已启用" : "SOCKS 未启用";
  const node = state.nodes.find((n) => n.id === d.active_node.id) || {};
  box.innerHTML = `
    <table style="max-width:640px;">
      <tbody>
        <tr><td style="width:120px;color:var(--muted);">节点名称</td><td class="cell-name">${esc(d.active_node.name)}</td></tr>
        <tr><td style="color:var(--muted);">类型</td><td><span class="badge ${esc(node.type || "other")}">${esc((node.type || "").toUpperCase())}</span></td></tr>
        <tr><td style="color:var(--muted);">服务器</td><td class="cell-mono">${esc(node.server || "")}${node.port ? ":" + node.port : ""}</td></tr>
        <tr><td style="color:var(--muted);">分组</td><td><span class="tag">${esc(node.group || "—")}</span></td></tr>
        <tr><td style="color:var(--muted);">代理出口</td><td class="cell-mono">${d.socks.enabled ? esc(d.socks.listen) + ":" + d.socks.port + (d.socks.username ? " （带认证）" : " （免认证）") : "未启用"}</td></tr>
      </tbody>
    </table>`;
}

/* ---------------- 订阅 ---------------- */
async function loadSubs() {
  try {
    const d = await api("GET", "/api/subscriptions");
    state.subs = d.subscriptions || [];
  } catch (e) { toast(e.message, "error"); }
  renderSubs();
}

function renderSubs() {
  const tb = $("#sub-tbody");
  $("#sub-count-hint").textContent = `共 ${state.subs.length} 个订阅`;
  if (!state.subs.length) {
    tb.innerHTML = `<tr><td colspan="7">
      <div class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="15" r="3"/><path d="M18 9V5"/></svg>
        <p>还没有订阅</p>
        <div class="hint">点击右上角「添加订阅」粘贴机场订阅链接</div>
      </div></td></tr>`;
    return;
  }
  tb.innerHTML = state.subs.map((s) => {
    const info = s.info || {};
    const infoTxt = info.total || info.expire
      ? `总流量 ${humanSize(info.total)} · 到期 ${info.expire ? new Date(Number(info.expire) * 1000).toLocaleDateString() : "—"}`
      : (info.title ? esc(info.title) : "—");
    const statusTag = s.error
      ? `<span class="tag err">失败</span>`
      : (s.last_update ? `<span class="tag ok">正常</span>` : `<span class="tag">未更新</span>`);
    return `<tr>
      <td class="cell-name">${esc(s.remark || s.url)}${s.interval_min ? `<br><span class="cell-sub">每 ${s.interval_min} 分钟自动更新</span>` : ""}</td>
      <td class="cell-mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(s.url)}">${esc(s.url)}</td>
      <td class="cell-mono">${s.node_count ?? "—"}</td>
      <td>${statusTag}</td>
      <td style="font-size:12px;color:var(--text-2);">${infoTxt}</td>
      <td class="cell-sub">${fmtTime(s.last_update)}</td>
      <td>
        <button class="btn sm" onclick="updateSub('${s.id}')">更新</button>
        <button class="btn sm" onclick="deleteSub('${s.id}')" style="color:var(--red);">删除</button>
      </td>
    </tr>`;
  }).join("");
}

async function updateSub(id, silent = false) {
  try {
    await api("POST", `/api/subscriptions/${id}/update`);
    if (!silent) toast("订阅更新成功", "success");
    await loadSubs();
    await loadNodes();
    await loadStatus();
  } catch (e) {
    toast("更新失败：" + e.message, "error");
    await loadSubs();
  }
}

async function deleteSub(id) {
  if (!confirm("确定删除该订阅及其所有节点？")) return;
  try {
    await api("DELETE", `/api/subscriptions/${id}`);
    toast("已删除订阅", "success");
    await loadSubs();
    await loadNodes();
    await loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

async function updateAllSubs() {
  const btn = $("#sub-update-all-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> 更新中…';
  try {
    const d = await api("POST", "/api/subscriptions/update_all");
    toast(`更新完成：成功 ${d.updated} / ${d.total}`, d.updated === d.total ? "success" : "error");
    await loadSubs();
    await loadNodes();
    await loadStatus();
  } catch (e) { toast(e.message, "error"); }
  btn.disabled = false;
  btn.textContent = "全部更新";
}

/* ---------------- 节点 ---------------- */
async function loadNodes() {
  try {
    let url = "/api/nodes";
    const params = [];
    if (state.search) params.push("q=" + encodeURIComponent(state.search));
    if (state.groupFilter) params.push("group=" + encodeURIComponent(state.groupFilter));
    if (params.length) url += "?" + params.join("&");
    const d = await api("GET", url);
    state.nodes = d.nodes || [];
  } catch (e) { toast(e.message, "error"); }
  renderNodes();
}

function renderNodes() {
  const tb = $("#node-tbody");
  const activeId = state.status && state.status.active_node ? state.status.active_node.id : null;
  $("#node-count-hint").textContent = `共 ${state.nodes.length} 个节点`;

  // 分组过滤选项
  const groups = Array.from(new Set(state.nodes.map((n) => n.group).filter(Boolean)));
  const sel = $("#node-group-filter");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部分组</option>` + groups.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
  sel.value = cur;

  if (!state.nodes.length) {
    tb.innerHTML = `<tr><td colspan="6">
      <div class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.3 7.3l7.4 2.4M8.3 16.7l7.4-2.4"/></svg>
        <p>暂无节点</p>
        <div class="hint">添加订阅并更新，或直接「导入链接」</div>
      </div></td></tr>`;
    return;
  }

  tb.innerHTML = state.nodes.map((n) => {
    const isActive = n.id === activeId;
    const latency = n.latency
      ? `<span class="cell-mono" style="color:var(--green);">${n.latency} ms</span>`
      : `<span class="cell-sub">未测</span>`;
    const display = n.custom_name || n.name;
    const customTag = n.custom_name ? ' <span class="tag" title="自定义名称">✎</span>' : "";
    return `<tr class="${isActive ? "active-node" : ""}">
      <td class="cell-name">${esc(display)}${customTag}${isActive ? ' <span class="tag ok">当前</span>' : ""}</td>
      <td><span class="badge ${esc(n.type || "other")}">${esc((n.type || "?").toUpperCase())}</span></td>
      <td class="cell-mono">${esc(n.server)}:${n.port || "—"}</td>
      <td><span class="tag">${esc(n.group || "—")}</span></td>
      <td>${latency}</td>
      <td>
        <button class="btn sm" onclick="renameNode('${n.id}')">重命名</button>
        <button class="btn sm primary" onclick="selectNode('${n.id}')">设为当前</button>
        <button class="btn sm" onclick="testNode('${n.id}')">测速</button>
        <button class="btn sm" onclick="deleteNode('${n.id}')" style="color:var(--red);">删除</button>
      </td>
    </tr>`;
  }).join("");
}

async function selectNode(id) {
  try {
    await api("POST", `/api/nodes/${id}/select`);
    toast("已设为当前节点", "success");
    await loadStatus();
    await loadNodes();
    await loadProxies();
  } catch (e) { toast(e.message, "error"); }
}

async function testNode(id) {
  try {
    await api("POST", `/api/nodes/${id}/test`);
    await loadNodes();
  } catch (e) { toast(e.message, "error"); }
}

async function renameNode(id) {
  const node = state.nodes.find((n) => n.id === id);
  if (!node) return;
  const cur = node.custom_name || node.name || "";
  const name = prompt("自定义节点名称（留空或取消则恢复为订阅原始名称）：", cur);
  if (name === null) return;
  try {
    await api("PUT", `/api/nodes/${id}`, { name: name.trim() });
    toast(name.trim() ? "节点已重命名" : "已恢复原始名称", "success");
    await loadNodes();
    await loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteNode(id) {
  if (!confirm("确定删除该节点？")) return;
  try {
    await api("DELETE", `/api/nodes/${id}`);
    toast("已删除节点", "success");
    await loadNodes();
    await loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- 代理配置（多条目） ---------------- */
let proxyEditId = null;

async function loadProxies() {
  try {
    const d = await api("GET", "/api/config/proxies");
    renderProxyList(d.proxies || []);
    $("#proxy-status-text").textContent = d.proxies.length
      ? `共 ${d.proxies.length} 条（启用 ${d.proxies.filter((p) => p.enabled).length} 条）`
      : "尚未配置代理，点击「添加代理」开始";
    updateExample(d.proxies || []);
  } catch (e) { toast(e.message, "error"); }
}

function renderProxyList(list) {
  const tb = $("#proxy-list");
  if (!list.length) {
    tb.innerHTML = `<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:18px;">暂无代理配置</td></tr>`;
    return;
  }
  tb.innerHTML = list.map((p) => {
    const nodeName = p.node_name || (p.node_id ? "(节点已删除)" : "跟随全局当前节点");
    return `
    <tr>
      <td>
        <label class="switch" style="gap:6px;">
          <input type="checkbox" ${p.enabled ? "checked" : ""} onchange="toggleProxy('${p.id}', this.checked)">
          <span class="track"></span>
        </label>
      </td>
      <td class="cell-mono">${esc(p.listen)}</td>
      <td class="cell-mono">${p.port}</td>
      <td>${p.has_password ? `<span class="tag">${esc(p.username || "user")}</span>` : `<span class="tag">免认证</span>`}</td>
      <td><span class="cell-sub">${esc(nodeName)}</span></td>
      <td style="text-align:right;white-space:nowrap;">
        <button class="btn sm" onclick="editProxy('${p.id}')">编辑</button>
        <button class="btn sm danger" onclick="deleteProxy('${p.id}')">删除</button>
      </td>
    </tr>`;
  }).join("");
}

function fillNodeSelect(selectedId) {
  const sel = $("#pm-node");
  const nodes = state.nodes || [];
  sel.innerHTML = `<option value="">（跟随全局当前节点）</option>` +
    nodes.map((n) => `<option value="${n.id}" ${n.id === selectedId ? "selected" : ""}>${esc(n.custom_name || n.name)} (${esc(n.type)})</option>`).join("");
}

function openProxyModal(title) {
  proxyEditId = null;
  $("#proxy-modal-title").textContent = title;
  $("#pm-listen").value = "0.0.0.0";
  $("#pm-port").value = "";
  fillNodeSelect("");
  $("#pm-user").value = "";
  $("#pm-pass").value = "";
  $("#proxy-modal").classList.add("open");
  $("#pm-port").focus();
}

function closeProxyModal() {
  $("#proxy-modal").classList.remove("open");
}

async function editProxy(id) {
  try {
    const d = await api("GET", "/api/config/proxies");
    const p = (d.proxies || []).find((x) => x.id === id);
    if (!p) return;
    proxyEditId = id;
    $("#proxy-modal-title").textContent = "编辑代理";
    $("#pm-listen").value = p.listen;
    $("#pm-port").value = p.port;
    fillNodeSelect(p.node_id || "");
    $("#pm-user").value = p.username || "";
    $("#pm-pass").value = "";
    $("#proxy-modal").classList.add("open");
  } catch (e) { toast(e.message, "error"); }
}

async function saveProxy() {
  const body = {
    listen: $("#pm-listen").value,
    port: parseInt($("#pm-port").value || "0", 10),
    username: $("#pm-user").value.trim(),
    password: $("#pm-pass").value,
    enabled: true,
    node_id: $("#pm-node").value || "",
  };
  if (!(body.username || "").trim() && (body.password || "")) body.password = "";
  try {
    if (proxyEditId) {
      await api("PUT", `/api/config/proxies/${proxyEditId}`, body);
      toast("代理已更新", "success");
    } else {
      await api("POST", "/api/config/proxies", body);
      toast("代理已添加", "success");
    }
    closeProxyModal();
    await loadProxies();
    loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

async function toggleProxy(id, enabled) {
  try {
    await api("PUT", `/api/config/proxies/${id}`, { enabled });
    await loadProxies();
    loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

async function deleteProxy(id) {
  if (!confirm("确定删除该代理条目？")) return;
  try {
    await api("DELETE", `/api/config/proxies/${id}`);
    toast("已删除", "success");
    await loadProxies();
    loadStatus();
  } catch (e) { toast(e.message, "error"); }
}

async function applyProxies() {
  try {
    const d = await api("POST", "/api/config/proxies/apply", {});
    if (d.success) {
      toast(d.message || "配置已应用", "success");
    } else {
      toast(d.message || "应用失败", "error");
    }
    await loadStatus();
    await loadProxies();
  } catch (e) {
    toast(e.message, "error");
    // 如果是节点相关错误，引导用户前往节点列表
    if (e.message.includes("节点")) {
      setTimeout(() => {
        if (confirm("需要先选择节点才能启用代理，是否前往节点列表？")) {
          switchView("nodes");
        }
      }, 500);
    }
  }
}

function updateExample(list) {
  const enabled = (list || []).filter((p) => p.enabled);
  const p = enabled[0] || (list || [])[0] || { port: 1080, listen: "127.0.0.1" };
  const port = p.port || 1080;
  const host = p.listen === "127.0.0.1" || p.listen === "::1" ? "127.0.0.1" : "<NAS-IP>";
  $("#socks-example").textContent =
    "# HTTP 代理（curl）\n" +
    `curl -x http://${host}:${port} https://example.com\n\n` +
    "# SOCKS5 代理（curl）\n" +
    `curl -x socks5://${host}:${port} https://example.com\n\n` +
    "# 浏览器 / 系统代理\n" +
    `协议: HTTP 或 SOCKS5   地址: ${host}   端口: ${port}`;
}

/* ---------------- 日志 ---------------- */
async function refreshLogs() {
  if (state.view !== "logs") return;
  const source = $("#log-source").value;
  try {
    const d = await api("GET", `/api/logs?source=${source}&lines=400`);
    const box = $("#log-box");
    const lines = (d.lines || []).map((l) => {
      const cls = l.includes("[ERROR]") ? "t-error" : l.includes("[WARN]") ? "t-warn" : "t-info";
      return `<span class="${cls}">${esc(l)}</span>`;
    }).join("\n");
    box.innerHTML = lines || "（暂无日志）";
    box.scrollTop = box.scrollHeight;
  } catch (e) { /* 静默 */ }
}

/* ---------------- 弹窗 ---------------- */
function openModal(id) { $("#" + id).classList.add("open"); }
function closeModal(id) { $("#" + id).classList.remove("open"); }

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  $("#nav").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-view]");
    if (btn) switchView(btn.dataset.view);
  });

  // 弹窗开关
  $$(".modal-close, [data-close]").forEach((el) => {
    el.addEventListener("click", () => closeModal(el.dataset.close));
  });
  $$(".modal-mask").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m) m.classList.remove("open"); });
  });

  // 订阅
  $("#sub-add-btn").addEventListener("click", () => { openModal("modal-sub"); });
  $("#sub-update-all-btn").addEventListener("click", updateAllSubs);
  $("#sub-save-btn").addEventListener("click", async () => {
    const url = $("#sub-url").value.trim();
    if (!url) { toast("请填写订阅地址", "error"); return; }
    const btn = $("#sub-save-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span> 保存中…';
    try {
      const d = await api("POST", "/api/subscriptions", {
        url,
        remark: $("#sub-remark").value.trim(),
        user_agent: $("#sub-ua").value.trim(),
        interval_min: parseInt($("#sub-interval").value || "0", 10),
      });
      toast("订阅已添加，正在更新…", "success");
      closeModal("modal-sub");
      $("#sub-url").value = ""; $("#sub-remark").value = "";
      await loadSubs();
      await updateSub(d.subscription.id, true);
      loadStatus();
    } catch (e) {
      toast("添加失败：" + e.message, "error");
    }
    btn.disabled = false;
    btn.textContent = "保存并更新";
  });

  // 节点
  $("#node-import-btn").addEventListener("click", () => { openModal("modal-import"); });
  $("#import-save-btn").addEventListener("click", async () => {
    const text = $("#import-text").value;
    if (!text.trim()) { toast("请粘贴节点链接", "error"); return; }
    const btn = $("#import-save-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span> 导入中…';
    try {
      const d = await api("POST", "/api/nodes/import", {
        text,
        group: $("#import-group").value.trim() || "手动导入",
      });
      toast(`成功导入 ${d.added} 个节点`, "success");
      closeModal("modal-import");
      $("#import-text").value = "";
      await loadNodes();
      loadStatus();
    } catch (e) {
      toast("导入失败：" + e.message, "error");
    }
    btn.disabled = false;
    btn.textContent = "导入";
  });
  $("#node-search").addEventListener("input", (e) => {
    clearTimeout(state._st);
    state._st = setTimeout(() => { state.search = e.target.value.trim(); loadNodes(); }, 300);
  });
  $("#node-group-filter").addEventListener("change", (e) => {
    state.groupFilter = e.target.value;
    loadNodes();
  });

  // 代理配置（多条目）
  $("#proxy-add").addEventListener("click", () => openProxyModal("添加代理"));
  $("#proxy-apply-btn").addEventListener("click", applyProxies);
  $("#pm-save").addEventListener("click", saveProxy);
  $("#pm-cancel").addEventListener("click", closeProxyModal);
  $("#pm-cancel2").addEventListener("click", closeProxyModal);

  // 日志
  $("#log-source").addEventListener("change", refreshLogs);
  $("#log-refresh").addEventListener("click", refreshLogs);

  // 概览快捷操作
  $("#quick-update").addEventListener("click", updateAllSubs);
  $("#quick-import").addEventListener("click", () => openModal("modal-import"));
  $("#quick-apply").addEventListener("click", async () => {
    try {
      const d = await api("POST", "/api/config/proxies/apply", {});
      if (d.success) {
        toast(d.message || "配置已应用", "success");
      } else {
        toast(d.message || "应用失败", "error");
      }
      await loadStatus();
    } catch (e) {
      toast(e.message, "error");
      if (e.message.includes("节点")) {
        setTimeout(() => {
          if (confirm("需要先选择节点才能启用代理，是否前往节点列表？")) {
            switchView("nodes");
          }
        }, 500);
      }
    }
  });

  // 键盘：Esc 关闭弹窗
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $$(".modal-mask.open").forEach((m) => m.classList.remove("open"));
  });
}

/* ---------------- 初始化 ---------------- */
async function init() {
  bindEvents();
  // 状态轮询
  state.statusTimer = setInterval(loadStatus, 5000);
  loadStatus();
  loadSubs();
  loadNodes();
  setInterval(() => {
    if ($("#log-auto").checked) refreshLogs();
  }, 5000);
}

document.addEventListener("DOMContentLoaded", init);
