/* 小鲸鱼控制台前端（原生 JS，零依赖） */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  status: null,
  personas: [],
  currentPersona: null,
  behavior: {},
  logTarget: "astrbot",
  stickerFilter: "全部",
  logAuto: false,
  logTimer: null,
  statusTimer: null,
};

const BEHAVIOR_FIELDS = [
  { key: "tier_slider", label: "触发档位（0 只回@，100 每条都接）", type: "range", min: 0, max: 100, step: 5 },
  { key: "cooldown_sec", label: "同群冷却（秒）", type: "range", min: 0, max: 300, step: 5 },
  { key: "quote_rate", label: "引用概率（%）", type: "range", min: 0, max: 100, step: 5 },
  { key: "at_rate", label: "@ 发言者概率（%）", type: "range", min: 0, max: 100, step: 5 },
  { key: "skip_probability", label: "潜水概率（%）", type: "range", min: 0, max: 100, step: 5 },
  { key: "burst_window_ms", label: "连发静默窗口（毫秒）", type: "range", min: 300, max: 5000, step: 100 },
  { key: "segment_delay_ms", label: "分句间隔（毫秒）", type: "range", min: 0, max: 5000, step: 100 },
  { key: "burst_enabled", label: "连发合并", type: "bool" },
  { key: "split_enabled", label: "分句发送（用 || 拆条）", type: "bool" },
  { key: "poke_enabled", label: "允许戳一戳", type: "bool" },
  { key: "sanitize", label: "去 AI 味（清 markdown）", type: "bool" },
];

/* ---------------- 基础 ---------------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      const msg = body && (body.error || body.message);
      if (msg) detail = `：${msg}`;
    } catch (e) {
      /* 非 JSON 响应 */
    }
    throw new Error(`HTTP ${res.status}${detail}`);
  }
  return res.json();
}

function toast(msg, ms = 2600) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), ms);
}

function fmtTime(d = new Date()) {
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

/* ---------------- 标签页 ---------------- */
function switchTab(name) {
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "ops" && window.loadOps) window.loadOps();
  if (name === "starmap" && window.loadStarmap) window.loadStarmap();
  if (name === "logs") loadLog();
  if (name === "stickers") loadStickers();
  if (name === "plugins") loadPlugins();
  if (name === "memory") loadMemory();
  if (name === "chatmem") { loadChatMemory(); loadDiary(); }
  if (name === "qzone") loadQzone();
  if (name === "market") setTimeout(() => loadMarket(false), 0);
  if (name === "usage") loadUsage();
  if (name === "turns") loadTurns();
  if (name === "persona") loadPersonas();
  if (name === "behavior") loadBehavior();
  if (name === "links") { refreshLinks(); loadModels(); }
  if (name === "settings") loadSettings();
  if (name === "policy") loadPolicy();
}

$$(".nav-item").forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));

/* ---------------- 状态 ---------------- */
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    state.status = s;
    renderStatus(s);
  } catch (e) {
    toast("控制台后端没连上：" + e.message);
  }
}

function renderStatus(s) {
  const a = s.astrbot, n = s.napcat;
  setPill("#pill-astrbot", "AstrBot", a.up ? "ok" : "bad", a.up ? "运行中" : "未运行");
  const napcatOnline = n.up && s.connection > 0;
  setPill("#pill-napcat", "NapCat", !n.up ? "bad" : napcatOnline ? "ok" : "warn", !n.up ? "未运行" : napcatOnline ? "已登录" : "待扫码");
  setPill("#pill-conn", "QQ 通道", s.connection > 0 ? "ok" : "bad", s.connection > 0 ? "已连接" : "未连接");
  setPill("#pill-model", "模型", s.model.model ? "ok" : "warn", s.model.model || "未知");
  $("#clock").textContent = s.time;
  $("#foot-status").textContent = s.connection > 0 ? "● QQ 通道在线" : "○ QQ 通道离线";

  // 概览卡片
  const cards = [
    {
      label: "AstrBot",
      value: a.up ? "运行中" : "已停止",
      desc: a.webui,
      cls: a.up ? "stat-ok" : "stat-bad",
    },
    {
      label: "NapCat / QQ",
      value: !n.up ? "已停止" : napcatOnline ? "已登录" : "待扫码登录",
      desc: !n.up
        ? "NapCat 进程未运行"
        : napcatOnline
        ? "QQ 通道已连接"
        : "等待手机 QQ 扫码",
      cls: n.up && napcatOnline ? "stat-ok" : "stat-warn",
    },
    {
      label: "OneBot 连接",
      value: s.connection > 0 ? "已连接" : "断开",
      desc: "ws://127.0.0.1:6199/ws",
      cls: s.connection > 0 ? "stat-ok" : "stat-bad",
    },
    {
      label: "当前模型",
      value: s.model.model || "—",
      desc: `${s.model.version ? s.model.version + " · " : ""}${s.model.provider_id || "—"} · ${s.model.key_masked || "无 Key"}`,
      cls: s.model.model ? "stat-ok" : "stat-warn",
    },
  ];
  setHtml(
    $("#overview-cards"),
    cards
      .map(
        (c) => `<div class="card">
        <div class="stat-label">${c.label}</div>
        <div class="stat-big ${c.cls}">${c.value}</div>
        <div class="hint" style="margin-top:6px">${c.desc}</div>
      </div>`
      )
      .join("")
  );

  setHtml($("#bot-info"), `
    <div class="k">模型</div><div class="v">${s.model.model || "—"} @ ${s.model.api_base || "—"}${s.model.version ? `<br/><span class="hint">${esc(s.model.version)}</span>` : ""}</div>
    <div class="k">服务</div><div class="v">${a.up ? "AstrBot 运行中" : "AstrBot 未运行"} · ${n.up ? (napcatOnline ? "QQ 已连接" : "QQ 待登录") : "NapCat 未运行"}</div>
    <div class="k">插件数</div><div class="v">${s.plugins.length} 个</div>
    <div class="k">管理端</div><div class="v">${n.webui_url ? `<a href="${n.webui_url}" target="_blank">NapCat</a> · <a href="${a.webui}" target="_blank">AstrBot</a>` : "—"}</div>`);
  const aboutBot2 = document.getElementById("about-bot");
  if (aboutBot2) aboutBot2.textContent = s.model.model || "—";

  renderRuntime(s.runtime || {}, s.life || {});
  const st = s.stats || {};
  setHtml($("#msg-stats"), `
    <div><span class="stat-label">收到</span><span class="stat-big">${st.received ?? "—"}</span></div>
    <div><span class="stat-label">发出</span><span class="stat-big">${st.sent ?? "—"}</span></div>`);

  const aboutBot = document.getElementById("about-bot");
  if (aboutBot) aboutBot.textContent = n.uin ? "小鲸鱼 · 已登录" : "未登录";

  setHtml(
    $("#plugin-list"),
    s.plugins
      .map((p) => `<span class="chip">${p.dir.replace("astrbot_plugin_", "")} <b>${p.version || "?"}</b></span>`)
      .join("")
  );

  $("#link-astrbot").href = s.astrbot.webui;
  if (n.webui_url) $("#link-napcat").href = n.webui_url;
  if (n.up) {
    $("#qr-image").src = `/api/qr?t=${Date.now()}`;
  const ab = $("#link-astrbot-info");
  if (ab) {
    ab.innerHTML = `
      <div class="k">状态</div><div class="v">${s.astrbot.up ? "运行中" : "未运行"}</div>
      <div class="k">当前模型</div><div class="v">${esc((s.model && s.model.model) || "—")}${s.model && s.model.version ? `<br/><span class="hint">${esc(s.model.version)}</span>` : ""}</div>
      <div class="k">插件</div><div class="v">${(s.plugins || []).length} 个</div>`;
  }
  const nb = $("#link-napcat-info");
  if (nb) {
    const online = Number(s.connection || 0) > 0;
    nb.innerHTML = `
      <div class="k">状态</div><div class="v">${s.napcat.up ? (online ? "已登录" : "待扫码") : "未运行"}</div>
      <div class="k">延迟</div><div class="v">${s.napcat.latency_ms != null ? s.napcat.latency_ms + " ms" : "—"}</div>
      <div class="k">OneBot</div><div class="v">ws://127.0.0.1:6199/ws</div>`;
  }
    $("#qr-image").style.display = "block";
  }
}

function setHtml(el, html) {
  if (el && el.innerHTML !== html) el.innerHTML = html;
}

function setPill(sel, name, cls, text) {
  const el = $(sel);
  el.className = "pill " + cls;
  el.textContent = `${name} · ${text}`;
}

/* ---------------- 服务操作 ---------------- */
$$("[data-service]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const target = btn.dataset.service;
    const action = btn.dataset.action;
    const label = { start: "启动", stop: "停止", restart: "重启" }[action] || action;
    if (action !== "start" && !(await modalConfirm({
      title: `${label}服务`,
      message: `确定要${label} ${target === "all" ? "全部服务" : target} 吗？`,
      okText: label,
      danger: true,
    }))) return;
    btn.disabled = true;
    try {
      const r = await api("/api/service", {
        method: "POST",
        body: JSON.stringify({ target, action }),
      });
      toast(r.ok ? `已触发${label}（几秒后自动刷新）` : r.error || "操作失败");
      setTimeout(refreshStatus, 4000);
      setTimeout(refreshStatus, 12000);
    } catch (e) {
      toast("操作失败：" + e.message);
    } finally {
      setTimeout(() => (btn.disabled = false), 3000);
    }
  })
);

/* ---------------- 人设 ---------------- */
async function loadPersonas() {
  try {
    state.personas = await api("/api/personas");
    renderPersonaList();
  } catch (e) {
    toast("读取人设失败：" + e.message);
  }
}

function renderPersonaList() {
  const box = $("#persona-list");
  if (!state.personas.length) {
    box.innerHTML = `<div class="hint">还没有人设文件</div>`;
    return;
  }
  box.innerHTML = state.personas
    .map(
      (p) => `<div class="list-item ${state.currentPersona === p.name ? "active" : ""}" data-name="${p.name}">
        <span class="persona-name">${esc(p.name)}${p.active ? ' <span class="plugin-badge ok">使用中</span>' : ""}</span>
        <span class="persona-row-actions">
          <small>${esc(p.mtime)}</small>
          ${p.active ? "" : `<button class="btn small persona-use" data-use="${esc(p.name)}">使用</button>`}
          <button class="persona-icon-btn" data-rename="${esc(p.name)}" title="重命名">✎</button>
          <button class="persona-del" data-del="${esc(p.name)}" title="删除人设文件">删除</button>
        </span>
      </div>`
    )
    .join("");
  $$("#persona-list .list-item").forEach((el) =>
    el.addEventListener("click", () => openPersona(el.dataset.name))
  );
  $$("#persona-list [data-use]").forEach((btn) =>
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      activatePersona(btn.dataset.use);
    })
  );
  $$("#persona-list [data-del]").forEach((btn) =>
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deletePersonaFile(btn.dataset.del);
    })
  );
  $$("#persona-list [data-rename]").forEach((btn) =>
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      renamePersona(btn.dataset.rename);
    })
  );
  updatePersonaActivateBtn();
  if (!state.currentPersona) openPersona(state.personas[0].name);
}

function updatePersonaActivateBtn() {
  const btn = $("#btn-activate-persona");
  if (!btn) return;
  const p = state.personas.find((x) => x.name === state.currentPersona);
  const active = !!(p && p.active);
  btn.disabled = !state.currentPersona || active;
  btn.textContent = active ? "当前人设" : "设为当前";
  const del = $("#btn-delete-persona");
  if (del) del.disabled = !state.currentPersona;
  const ren = $("#btn-rename-persona");
  if (ren) ren.disabled = !state.currentPersona;
}

async function renamePersona(oldName) {
  if (!oldName) return;
  if (state.coreDirty) {
    toast("核心设定还有未保存的修改，先保存再重命名", 5000);
    return;
  }
  const res = await modalPrompt({
    title: "重命名人设",
    fields: [
      {
        key: "name",
        label: "新的文件名（不含 .md）",
        value: oldName,
        placeholder: "例如：小鲸鱼",
        hint: "会同步改名核心设定、AI 提议和快照；当前绑定/默认人设会自动跟随",
      },
    ],
    okText: "重命名",
  });
  if (!res) return;
  const newName = String(res.name || "").trim();
  if (!newName || newName === oldName) return;
  if (!/^[\w\-\u4e00-\u9fff]+$/.test(newName)) {
    return toast("只能用中文、字母、数字、下划线和短横线", 5000);
  }
  try {
    const r = await api("/api/persona/rename", {
      method: "POST",
      body: JSON.stringify({ old: oldName, new: newName }),
    });
    if (!r.ok) return toast(r.error || "重命名失败", 5000);
    toast(`已重命名为「${newName}」`, 3000);
    state.currentPersona = newName;
    await loadPersonas();
    openPersona(newName);
  } catch (e) {
    toast("重命名失败：" + e.message, 5000);
  }
}

async function deletePersonaFile(name) {
  if (!name) return;
  if (!(await modalConfirm({ title: "删除人设", message: "是否确认删除", okText: "确认删除" }))) return;
  try {
    const r = await api("/api/persona/delete", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    if (!r.ok) return toast(r.error || "删除失败", 5000);
    const wasCurrent = state.currentPersona === name;
    toast(
      r.new_active ? `已删除，当前人设切换为「${r.new_active}」` : `已删除「${name}」`,
      4000
    );
    if (wasCurrent) {
      state.currentPersona = "";
      $("#persona-editor").value = "";
      $("#persona-title").textContent = "选择左侧人设";
      $("#persona-meta").textContent = "";
      $("#persona-core-editor").value = "";
      $("#persona-core-meta").textContent = "未选择人设";
      renderCorePending([]);
      renderCoreHistory([]);
    }
    await loadPersonas();
  } catch (e) {
    toast("删除失败：" + e.message, 5000);
  }
}

async function activatePersona(name) {
  if (!name) return;
  try {
    const r = await api("/api/persona/activate", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    if (!r.ok) return toast(r.error || "切换失败", 5000);
    toast(`已切换为「${name}」`, 3000);
    state.currentPersona = name;
    await loadPersonas();
  } catch (e) {
    toast("切换失败：" + e.message, 5000);
  }
}


/* ---------------- 核心设定 ---------------- */
let coreHistoryItems = [];

function updateCoreMeta() {
  const el = $("#persona-core-editor");
  const meta = $("#persona-core-meta");
  if (!el || !meta) return;
  const n = el.value.trim().length;
  meta.textContent = state.currentPersona
    ? `${n} 字 · 建议 200–800 字${n === 0 ? " · 未填写时不会注入" : ""}`
    : "未选择人设";
}

function renderCorePending(items) {
  const box = $("#core-pending-list");
  const badge = $("#core-pending-count");
  if (!box) return;
  const list = items || [];
  if (badge) badge.textContent = String(list.length);
  if (!list.length) {
    box.innerHTML = `<p class="hint">暂无提议</p>`;
    return;
  }
  box.innerHTML = list
    .map(
      (it) => `<div class="core-pending-item">
        <div class="core-pending-text">${esc(it.suggestion || "")}</div>
        ${it.reason ? `<div class="core-pending-reason">原因：${esc(it.reason)}</div>` : ""}
        <div class="core-pending-foot">
          <span class="hint">${esc(it.created_at || "")}</span>
          <span class="core-pending-actions">
            <button class="btn small primary" data-core-approve="${esc(it.id)}">通过</button>
            <button class="btn small" data-core-reject="${esc(it.id)}">忽略</button>
          </span>
        </div>
      </div>`
    )
    .join("");
  $$("#core-pending-list [data-core-approve]").forEach((btn) =>
    btn.addEventListener("click", () => approveCoreProposal(btn.dataset.coreApprove))
  );
  $$("#core-pending-list [data-core-reject]").forEach((btn) =>
    btn.addEventListener("click", () => rejectCoreProposal(btn.dataset.coreReject))
  );
}

function renderCoreHistory(items) {
  coreHistoryItems = items || [];
  const box = $("#core-history-list");
  if (!box) return;
  if (!coreHistoryItems.length) {
    box.innerHTML = `<p class="hint">还没有快照</p>`;
    return;
  }
  box.innerHTML = coreHistoryItems
    .map(
      (it) => `<div class="core-history-item">
        <div>
          <b>${esc(it.time || "")}</b> <span class="hint">${it.chars || 0} 字</span>
          <div class="core-history-preview">${esc(it.preview || "")}</div>
        </div>
        <button class="btn small" data-core-restore="${esc(it.file)}">恢复</button>
      </div>`
    )
    .join("");
  $$("#core-history-list [data-core-restore]").forEach((btn) =>
    btn.addEventListener("click", () => restoreCoreSnapshot(btn.dataset.coreRestore))
  );
}

async function loadPersonaCore(name) {
  try {
    const d = await api(`/api/persona/core?name=${encodeURIComponent(name)}`);
    if (!d.ok) {
      $("#persona-core-editor").value = "";
      $("#persona-core-meta").textContent = "读取核心设定失败";
      return;
    }
    $("#persona-core-editor").value = d.core || "";
    state.coreDirty = false;
    updateCoreMeta();
    renderCorePending(d.pending || []);
    renderCoreHistory(d.history || []);
  } catch (e) {
    toast("读取核心设定失败：" + e.message);
  }
}

async function savePersonaCore() {
  if (!state.currentPersona) return toast("先选一个人设");
  const btn = $("#btn-core-save");
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/persona/core/save", {
      method: "POST",
      body: JSON.stringify({
        name: state.currentPersona,
        content: $("#persona-core-editor").value,
      }),
    });
    if (!r.ok) return toast(r.error || "保存失败", 5000);
    toast("核心设定已保存，下一条消息生效", 3000);
    await loadPersonaCore(state.currentPersona);
  } catch (e) {
    toast("保存失败：" + e.message, 5000);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function approveCoreProposal(pid) {
  if (!state.currentPersona) return;
  try {
    const r = await api("/api/persona/core/approve", {
      method: "POST",
      body: JSON.stringify({ name: state.currentPersona, id: pid }),
    });
    if (!r.ok) return toast(r.error || "通过失败", 5000);
    toast("已写入核心设定", 3000);
    await loadPersonaCore(state.currentPersona);
  } catch (e) {
    toast("通过失败：" + e.message, 5000);
  }
}

async function rejectCoreProposal(pid) {
  if (!state.currentPersona) return;
  try {
    const r = await api("/api/persona/core/reject", {
      method: "POST",
      body: JSON.stringify({ name: state.currentPersona, id: pid }),
    });
    if (!r.ok) return toast(r.error || "忽略失败", 5000);
    await loadPersonaCore(state.currentPersona);
  } catch (e) {
    toast("忽略失败：" + e.message, 5000);
  }
}

async function restoreCoreSnapshot(file) {
  if (!state.currentPersona) return;
  const ok = await modalConfirm({
    title: "恢复核心设定",
    message: "是否恢复这个快照？当前内容会先存一份快照。",
    okText: "恢复",
  });
  if (!ok) return;
  try {
    const r = await api("/api/persona/core/rollback", {
      method: "POST",
      body: JSON.stringify({ name: state.currentPersona, file }),
    });
    if (!r.ok) return toast(r.error || "恢复失败", 5000);
    toast("已恢复快照", 3000);
    await loadPersonaCore(state.currentPersona);
  } catch (e) {
    toast("恢复失败：" + e.message, 5000);
  }
}

async function openPersona(name) {
  if (state.coreDirty && state.currentPersona && state.currentPersona !== name) {
    const go = await modalConfirm({
      title: "核心设定未保存",
      message: "当前核心设定还有未保存的修改，是否放弃？",
      okText: "放弃修改",
    });
    if (!go) return;
  }
  try {
    const r = await api(`/api/persona?name=${encodeURIComponent(name)}`);
    if (!r.ok) return toast(r.error);
    state.currentPersona = name;
    $("#persona-title").textContent = `${name}.md`;
    $("#persona-editor").value = r.content;
    $("#persona-meta").textContent = `${r.content.length} 字`;
    await loadPersonaCore(name);
    renderPersonaList();
    updatePersonaActivateBtn();
  } catch (e) {
    toast("读取失败：" + e.message);
  }
}

$("#btn-activate-persona").addEventListener("click", async () => {
  if (state.currentPersona) await activatePersona(state.currentPersona);
});

$("#btn-save-persona").addEventListener("click", async () => {
  if (!state.currentPersona) return toast("先选一个人设");
  try {
    const r = await api("/api/persona/save", {
      method: "POST",
      body: JSON.stringify({
        name: state.currentPersona,
        content: $("#persona-editor").value,
      }),
    });
    toast(r.ok ? `已保存（${r.saved_at}），下一条消息生效` : r.error);
    $("#persona-meta").textContent = `${$("#persona-editor").value.length} 字`;
    loadPersonas();
  } catch (e) {
    toast("保存失败：" + e.message);
  }
});

$("#btn-delete-persona").addEventListener("click", async () => {
  const name = state.currentPersona;
  if (!name) return;
  if (!(await modalConfirm({ title: "删除人设", message: "是否确认删除", okText: "确认删除" }))) return;
  const btn = $("#btn-delete-persona");
  btn.disabled = true;
  try {
    const r = await api("/api/persona/delete", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    if (!r.ok) {
      toast(r.error || "删除失败", 5000);
      btn.disabled = false;
      return;
    }
    toast(r.new_active ? `已删除，当前人设切换为「${r.new_active}」` : "已删除", 4000);
    state.currentPersona = "";
    $("#persona-editor").value = "";
    $("#persona-title").textContent = "选择左侧人设";
    await loadPersonas();
    const delBtn = $("#btn-delete-persona");
    if (delBtn) delBtn.disabled = true;
  } catch (e) {
    toast("删除失败：" + e.message, 5000);
    btn.disabled = false;
  }
});

$("#btn-rename-persona").addEventListener("click", () => {
  if (state.currentPersona) renamePersona(state.currentPersona);
});

$("#btn-core-save").addEventListener("click", savePersonaCore);

$("#persona-core-editor").addEventListener("input", () => {
  state.coreDirty = true;
  updateCoreMeta();
});

$("#btn-core-history").addEventListener("click", () => {
  const wrap = $("#core-history-wrap");
  if (!wrap) return;
  const show = wrap.style.display === "none";
  wrap.style.display = show ? "block" : "none";
  if (show) renderCoreHistory(coreHistoryItems);
});

/* 核心设定：AI 提议/快照侧栏自动刷新（不影响正在编辑的正文） */
async function refreshCoreSide() {
  const panel = document.querySelector("#tab-persona.active");
  if (!panel || !state.currentPersona || state.coreDirty) return;
  try {
    const d = await api(`/api/persona/core?name=${encodeURIComponent(state.currentPersona)}`);
    if (!d.ok) return;
    renderCorePending(d.pending || []);
    renderCoreHistory(d.history || []);
  } catch (e) {}
}
setInterval(refreshCoreSide, 15000);

$("#btn-new-persona").addEventListener("click", async () => {
  const nameRes = await modalPrompt({
    title: "新建人设",
    fields: [{ key: "name", label: "人设文件名（不含 .md）", placeholder: "例如：小鲸鱼、小助理", hint: "创建后会自动打开编辑器，从「你是谁 / 说话方式」开始写即可" }],
    hint: "文件名用于区分不同人设，之后可以在左侧列表随时切换。",
    okText: "创建人设",
  });
  const name = (nameRes && nameRes.name || "").trim();
  if (!name) return;
  try {
    const r = await api("/api/persona/save", {
      method: "POST",
      body: JSON.stringify({ name, content: `# ${name}\n\n## 你是谁\n\n## 说话方式\n` }),
    });
    if (r.ok) {
      toast("已创建");
      await loadPersonas();
      openPersona(name);
    } else toast(r.error);
  } catch (e) {
    toast(e.message);
  }
});


/* ---------------- 通用输入弹窗（Electron 不支持 window.prompt） ---------------- */

function modalConfirm({ title = "确认", message = "是否确认删除", okText = "确认删除", danger = true } = {}) {
  return new Promise((resolve) => {
    const mask = $("#prompt-modal");
    $("#prompt-title").textContent = title;
    $("#prompt-body").innerHTML = `<p class="pm-confirm-text">${esc(message)}</p>`;
    const ok = $("#prompt-ok");
    ok.textContent = okText;
    ok.className = danger ? "btn danger" : "btn primary";
    mask.classList.remove("hidden");
    ok.focus();

    const cleanup = () => {
      mask.classList.add("hidden");
      ok.removeEventListener("click", onOk);
      $("#prompt-cancel").removeEventListener("click", onCancel);
      $("#prompt-close").removeEventListener("click", onCancel);
      mask.removeEventListener("click", onMask);
      document.removeEventListener("keydown", onKey);
    };
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onMask = (e) => { if (e.target === mask) onCancel(); };
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onOk();
    };
    ok.addEventListener("click", onOk);
    $("#prompt-cancel").addEventListener("click", onCancel);
    $("#prompt-close").addEventListener("click", onCancel);
    mask.addEventListener("click", onMask);
    document.addEventListener("keydown", onKey);
  });
}

function modalPrompt({ title = "编辑", fields = [], hint = "", okText = "确定" }) {
  return new Promise((resolve) => {
    const mask = $("#prompt-modal");
    $("#prompt-title").textContent = title;
    $("#prompt-ok").textContent = okText;
    $("#prompt-ok").className = "btn primary";
    $("#prompt-body").innerHTML =
      fields
        .map((f) => {
          const control =
            f.type === "textarea"
              ? `<textarea data-pkey="${esc(f.key)}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(f.value ?? "")}</textarea>`
              : `<input type="text" data-pkey="${esc(f.key)}" placeholder="${esc(f.placeholder || "")}" value="${esc(f.value ?? "")}" />`;
          return `<div class="pm-field">
            ${f.label ? `<div class="pm-label">${esc(f.label)}</div>` : ""}
            ${control}
            ${f.hint ? `<div class="pm-hint">${esc(f.hint)}</div>` : ""}
          </div>`;
        })
        .join("") + (hint ? `<p class="pm-hint pm-hint-global">${esc(hint)}</p>` : "");
    mask.classList.remove("hidden");
    const first = $("#prompt-body input, #prompt-body textarea");
    if (first) first.focus();

    const cleanup = () => {
      mask.classList.add("hidden");
      $("#prompt-ok").removeEventListener("click", onOk);
      $("#prompt-cancel").removeEventListener("click", onCancel);
      $("#prompt-close").removeEventListener("click", onCancel);
      mask.removeEventListener("click", onMask);
      document.removeEventListener("keydown", onKey);
    };
    const onOk = () => {
      const out = {};
      $$("#prompt-body [data-pkey]").forEach((el) => {
        out[el.dataset.pkey] = el.value;
      });
      cleanup();
      resolve(out);
    };
    const onCancel = () => {
      cleanup();
      resolve(null);
    };
    const onMask = (e) => {
      if (e.target === mask) onCancel();
    };
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onOk();
    };
    $("#prompt-ok").addEventListener("click", onOk);
    $("#prompt-cancel").addEventListener("click", onCancel);
    $("#prompt-close").addEventListener("click", onCancel);
    mask.addEventListener("click", onMask);
    document.addEventListener("keydown", onKey);
  });
}

/* ---------------- 聊天设置 ---------------- */
const BEHAVIOR_SECTIONS = [
  {
    id: "trigger",
    icon: "🎯",
    title: "触发：什么时候接话",
    desc: "调控主动插嘴的意愿；被 @ 或命中关键词时不受档位限制。",
    fields: [
      { key: "group_reply_disabled", label: "不回复群聊消息", type: "bool", hint: "打开后群里完全静默（连 @ 也不回），私聊不受影响" },
      { key: "enabled", label: "总开关", type: "bool", hint: "关掉后小鲸鱼不参与群聊行为（被 @ 仍可能触发核心回复）" },
      { key: "tier_slider", label: "触发档位", type: "range", min: 0, max: 100, step: 5, hint: "没被 @ 时按此概率插嘴；0 = 只回 @ 和关键词，100 = 每条都接" },
      { key: "cooldown_sec", label: "同群冷却", type: "range", min: 0, max: 300, step: 5, suffix: " 秒", hint: "同一群两次主动回复的最小间隔" },
      { key: "skip_probability", label: "潜水概率", type: "range", min: 0, max: 100, step: 5, suffix: " %", hint: "已经决定开口，仍有这个概率临时选择沉默" },
      { key: "keywords", label: "强制触发关键词", type: "tags", hint: "消息里出现这些词就直接触发" },
    ],
  },
  {
    id: "gate",
    icon: "🧠",
    title: "是否接话：语境与情绪",
    desc: "触发之后再让小模型看一眼群里的气氛和对方情绪；不合适就保持沉默。",
    fields: [
      { key: "context_gate_enabled", label: "智能判断是否接话", type: "bool", hint: "只影响概率/关键词触发，被 @ 仍会回；每条候选回复多一次小模型调用（少量 token）" },
      { key: "context_gate_max_recent", label: "参考最近消息", type: "range", min: 3, max: 20, step: 1, suffix: " 条", hint: "送给判断模型的上下文条数" },
    ],
  },
  {
    id: "life",
    icon: "🌙",
    title: "作息与状态：她也有生活感",
    desc: "睡觉时间不主动接话；每天随机一个小状态影响语气；错过消息后补一句「刚看到」。",
    fields: [
      { key: "sleep_enabled", label: "启用作息", type: "bool", hint: "睡觉时间内不主动找话题（被 @ 仍会回）" },
      { key: "sleep_start", label: "睡觉时间", type: "text", hint: "如 23:30" },
      { key: "sleep_end", label: "起床时间", type: "text", hint: "如 08:00" },
      { key: "daily_mood_enabled", label: "每日小状态", type: "bool", hint: "每天随机心情/精力，回复语气跟着变" },
      { key: "late_ack_enabled", label: "迟到回应", type: "bool", hint: "很久没理之后回复，先补一句「刚在忙」" },
      { key: "late_ack_gap_sec", label: "多久算迟到", type: "range", min: 60, max: 3600, step: 60, suffix: " 秒" },
      { key: "late_ack_probability", label: "迟到回应概率", type: "range", min: 0, max: 100, step: 5, suffix: " %" },
      { key: "signature_enabled", label: "自动改 QQ 签名", type: "bool", hint: "按每天心情和最近聊天，让 AI 写一句个性签名" },
      { key: "signature_interval_hours", label: "签名更换间隔", type: "range", min: 1, max: 72, step: 1, suffix: " 小时" },
      { key: "state_note_dedupe", label: "状态提示去重", type: "bool", hint: "动态状态/关系提示只在内容变化时注入，省 token" },
      { key: "life_profile", label: "角色日常设定", multiline: true, hint: "身份、工作/学习、作息。只影响每天生成的生活时间线，不改人设；保存后下一条消息会按新设定重新生成", placeholder: "例如：上班族，工作日朝九晚六，周末休息，住在杭州" },
      { key: "life_timeline_enabled", label: "动态生活时间线", type: "bool", hint: "每天生成一张生活时间线，并在对话里注入“现在正在做什么”" },
    ],
  },
  {
    id: "relationship",
    icon: "💗",
    title: "关系与约定：越聊越熟",
    desc: "亲密度分 陌生→熟悉→亲近→黏人 四档，影响称呼和语气；主动聊天时会提起你们之前没做完的事。",
    fields: [
      { key: "relationship_enabled", label: "关系阶段", type: "bool", hint: "亲密度越高，语气越熟、越会撒娇" },
      { key: "promise_enabled", label: "记得约定", type: "bool", hint: "从长期记忆里挑「还没做完的事」，主动消息里自然提起" },
      { key: "relationship_daily_gain_cap", label: "每天最多涨多少亲密", type: "range", min: 5, max: 100, step: 5, suffix: " 点" },
    ],
  },
  {
    id: "actions",
    icon: "🫰",
    title: "小动作：像真人一样的小失误",
    desc: "偶尔发错一条再撤回、回复完戳一下你，增加真实感。频率别调太高。",
    fields: [
      { key: "recall_enabled", label: "发错再撤回", type: "bool", hint: "偶尔先发一条打错的，再撤回" },
      { key: "recall_probability", label: "撤回概率", type: "range", min: 0, max: 30, step: 1, suffix: " %" },
      { key: "recall_delay_sec", label: "撤回延迟", type: "range", min: 1, max: 5, step: 1, suffix: " 秒" },
      { key: "recall_cooldown_sec", label: "撤回冷却", type: "range", min: 60, max: 3600, step: 60, suffix: " 秒" },
      { key: "poke_rate", label: "拍一拍概率", type: "range", min: 0, max: 30, step: 1, suffix: " %" },
      { key: "poke_cooldown_sec", label: "拍一拍冷却", type: "range", min: 60, max: 3600, step: 60, suffix: " 秒" },
    ],
  },
  {
    id: "calendar",
    icon: "🎂",
    title: "纪念日与天气：她记得日子，也会关心你",
    desc: "生日/纪念日主动祝福；天气变化时提醒带伞、多穿点（需要电脑在开机状态）。",
    fields: [
      { key: "anniversary_enabled", label: "纪念日祝福", type: "bool", hint: "当天主动发一句祝福" },
      { key: "anniversaries", label: "纪念日", type: "anniversary", hint: "填「是什么日子」，选日期，加入列表；到那天会自动祝福" },
      { key: "anniversary_hour", label: "几点后祝福", type: "range", min: 0, max: 23, step: 1, suffix: " 点" },
      { key: "weather_enabled", label: "天气变化提醒", type: "bool", hint: "下雨/下雪/突然降温/高温/低温时提醒，不是天天播报" },
      { key: "weather_key", label: "和风 Key", type: "text", hint: "和风天气 API Key（留空则用 wttr.in 城市名）", link: { text: "去和风天气控制台申请 Key", url: "https://console.qweather.com/" } },
      { key: "weather_host", label: "和风 Host", type: "text", hint: "控制台设置里的 API Host，如 xxxx.re.qweatherapi.com" },
      { key: "weather_location", label: "精确地点", type: "text", hint: "精确到区县，如 浙江省杭州市余杭区" },
      { key: "weather_interval_min", label: "检查间隔", type: "range", min: 10, max: 180, step: 10, suffix: " 分钟" },
      { key: "weather_temp_drop", label: "降温提醒阈值", type: "range", min: 2, max: 10, step: 1, suffix: " ℃" },
      { key: "weather_hot_temp", label: "高温提醒", type: "range", min: 25, max: 40, step: 1, suffix: " ℃" },
      { key: "weather_cold_temp", label: "低温提醒", type: "range", min: -10, max: 15, step: 1, suffix: " ℃" },
      { key: "weather_alert_cooldown_sec", label: "同类提醒冷却", type: "range", min: 1800, max: 43200, step: 1800, suffix: " 秒" },
    ],
  },
  {
    id: "images",
    icon: "🖼️",
    title: "发图片：偶尔分享一张",
    desc: "把图片放进插件目录的 images 文件夹，她偶尔会发一张（需要开启）。",
    fields: [
      { key: "image_enabled", label: "发送图片", type: "bool", hint: "开启后按概率发图片" },
      { key: "image_rate", label: "发图概率", type: "range", min: 0, max: 50, step: 5, suffix: " %" },
      { key: "image_cooldown_sec", label: "发图冷却", type: "range", min: 60, max: 7200, step: 60, suffix: " 秒" },
    ],
  },
  {
    id: "qzone_share",
    icon: "🌐",
    title: "QQ空间：偶尔分享",
    desc: "不按死时间发：聊天后 AI 判断值不值得发；另外每周随机挑 3-4 天分享日常。",
    fields: [
      { key: "qzone_post_enabled", label: "启用空间分享", type: "bool", hint: "总开关；下面两项都受它控制" },
      { key: "qzone_chat_post_enabled", label: "聊天后判断", type: "bool", hint: "聊完一段时间后，AI 觉得有值得分享的才发" },
      { key: "qzone_chat_post_delay_min", label: "聊天后延迟", type: "range", min: 3, max: 60, step: 1, suffix: " 分钟" },
      { key: "qzone_chat_post_daily_cap", label: "聊天触发上限", type: "range", min: 1, max: 3, step: 1, suffix: " 条/天" },
      { key: "qzone_weekly_enabled", label: "每周随机分享日常", type: "bool", hint: "每周随机挑几天，随机时间发日常" },
      { key: "qzone_weekly_days_min", label: "每周最少天数", type: "range", min: 1, max: 7, step: 1, suffix: " 天" },
      { key: "qzone_weekly_days_max", label: "每周最多天数", type: "range", min: 1, max: 7, step: 1, suffix: " 天" },
      { key: "qzone_post_image_enabled", label: "说说配图", type: "bool", hint: "从 images/ 目录随机挑一张图一起发" },
      { key: "qzone_post_image_rate", label: "带图概率", type: "range", min: 0, max: 100, step: 5, suffix: " %" },
      { key: "qzone_post_image_source", label: "配图来源", type: "select", options: [
        { value: "auto", label: "聊天图片优先，没有再用本地图" },
        { value: "chat", label: "只用聊天图片" },
        { value: "local", label: "只用本地 images/" },
      ], hint: "聊天图片会先经视觉模型判断适不适合这条说说" },
      { key: "qzone_post_image_chat_enabled", label: "允许用聊天图片", type: "bool", hint: "从最近聊天里收到的图片中挑" },
      { key: "qzone_post_image_chat_hours", label: "聊天图片时效", type: "range", min: 1, max: 72, step: 1, suffix: " 小时" },
      { key: "qzone_post_window_start", label: "分享时段开始", type: "text", hint: "如 12:00" },
      { key: "qzone_post_window_end", label: "分享时段结束", type: "text", hint: "如 22:00" },
    ],
  },
  {
    id: "voice",
    icon: "🎙",
    title: "语音（Breeze TTS 2）",
    desc: "用 BreezeBlue 云端音色发语音。API Key 在 breezeblue.ai 开发者控制台创建。",
    fields: [
      { key: "enabled", label: "启用语音", type: "bool", plugin: "astrbot_plugin_breeze_tts" },
      { key: "api_key", label: "Breeze API Key", type: "password", hint: "在 breezeblue.ai 申请的 API Key；留空保持不变", plugin: "astrbot_plugin_breeze_tts" },
      { key: "breeze_guide", label: "如何获取 Breeze API Key", type: "guide", plugin: "astrbot_plugin_breeze_tts" },
      { key: "voices", label: "音色管理", type: "breeze_voices", plugin: "astrbot_plugin_breeze_tts" },
      { key: "instructions", label: "语音指令", type: "text", hint: "例如：用轻松、自然的语气，像和朋友聊天", plugin: "astrbot_plugin_breeze_tts" },
      { key: "guidance_scale", label: "指令强度", type: "range", min: 1, max: 10, step: 0.5, plugin: "astrbot_plugin_breeze_tts" },
      { key: "voice_rate", label: "语音概率上限", type: "range", min: 0, max: 50, step: 1, suffix: " %", plugin: "astrbot_plugin_breeze_tts" },
      { key: "max_chars", label: "只对不超过多少字发语音", type: "range", min: 5, max: 60, step: 1, suffix: " 字", plugin: "astrbot_plugin_breeze_tts" },
      { key: "cooldown_sec", label: "同会话冷却", type: "range", min: 0, max: 3600, step: 30, suffix: " 秒", plugin: "astrbot_plugin_breeze_tts" },
      { key: "delay_ms", label: "语音延迟", type: "range", min: 0, max: 3000, step: 100, suffix: " ms", plugin: "astrbot_plugin_breeze_tts" },
    ],
  },
  {
    id: "rhythm",
    icon: "🌊",
    title: "节奏：怎么说话",
    desc: "连发合并、分句发送和打字间隔，决定「像不像真人」。",
    fields: [
      { key: "burst_enabled", label: "连发合并", type: "bool", hint: "同一个人连发几条时，等他停手再一起回" },
      { key: "burst_window_ms", label: "连发静默窗口", type: "range", min: 300, max: 5000, step: 100, suffix: " ms" },
      { key: "burst_max_age_ms", label: "合并最大跨度", type: "range", min: 1000, max: 30000, step: 500, suffix: " ms", hint: "超过这个时间的旧消息不参与合并" },
      { key: "split_enabled", label: "分句发送", type: "bool", hint: "模型用 || 分隔的多段会拆成多条依次发" },
      { key: "split_marker", label: "分句标记", type: "text" },
      { key: "max_segments", label: "最多分几条", type: "range", min: 1, max: 8, step: 1 },
      { key: "first_delay_ms", label: "首条延迟", type: "range", min: 0, max: 3000, step: 100, suffix: " ms" },
      { key: "segment_delay_ms", label: "分句间隔", type: "range", min: 0, max: 5000, step: 100, suffix: " ms" },
      { key: "jitter_ms", label: "随机抖动", type: "range", min: 0, max: 1000, step: 50, suffix: " ms", hint: "让间隔有随机浮动，更像手打" },
    ],
  },
  {
    id: "sticker",
    icon: "🧩",
    plugin: "sticker_pack",
    title: "表情包：什么时候发表情",
    desc: "根据语境和情绪判断要不要发表情、发哪张，并控制出现频率。",
    fields: [
      { key: "auto_sticker_enabled", label: "智能发表情", type: "bool", hint: "每条回复额外调用一次小模型判断该不该发表情、挑哪张；严肃话题不会发" },
      { key: "auto_sticker_rate", label: "表情频率上限", type: "range", min: 0, max: 100, step: 5, suffix: " %", hint: "每条回复最多按这个概率尝试发表情；0 = 不自动发" },
      { key: "auto_sticker_cooldown_sec", label: "同会话冷却", type: "range", min: 0, max: 600, step: 10, suffix: " 秒", hint: "同一群/同一人两次自动表情的最小间隔" },
      { key: "auto_sticker_candidates", label: "候选表情数", type: "range", min: 5, max: 60, step: 1, suffix: " 张", hint: "按语境关键词挑多少张给模型选，太多费 token" },
    ],
  },
  {
    id: "proactive",
    icon: "💬",
    plugin: "whale_behavior",
    title: "主动聊天：没消息时也会找你",
    desc: "空闲时主动开启话题：可以接着之前的聊天，也可以分享相关领域的内容。",
    fields: [
      { key: "proactive_enabled", label: "主动找人聊天", type: "bool", hint: "开启后按间隔主动发消息；只在「活跃时段」内发送" },
      { key: "proactive_targets", label: "生效对象", type: "targets", hint: "选择私聊好友或群；建议先只选你自己，观察效果后再加" },
      { key: "proactive_topic_mode", label: "话题来源", type: "select", options: [
        { value: "history", label: "接着旧话题" },
        { value: "share", label: "分享相关领域" },
        { value: "mix", label: "随机混合" },
      ], hint: "历史话题来自机器人记录的聊天内容" },
      { key: "proactive_active_hours", label: "活跃时段", type: "text", hint: "如 09:00-23:30；可用逗号分隔多段" },
      { key: "proactive_min_interval_min", label: "最短间隔", type: "range", min: 10, max: 720, step: 10, suffix: " 分钟" },
      { key: "proactive_max_interval_min", label: "最长间隔", type: "range", min: 10, max: 1440, step: 30, suffix: " 分钟" },
      { key: "proactive_daily_limit", label: "每个对象每天最多", type: "range", min: 1, max: 30, step: 1, suffix: " 条" },
      { key: "proactive_silence_min", label: "沉默触发", type: "range", min: 5, max: 180, step: 5, suffix: " 分钟", hint: "对方多久没说话才允许主动" },
      { key: "proactive_max_unanswered", label: "未回复上限", type: "range", min: 1, max: 10, step: 1, suffix: " 次", hint: "主动后一直没回复达到这个次数就暂停，语气会带点失落" },
      { key: "proactive_split_enabled", label: "分段发送", type: "bool", hint: "按标点拆成几条发，模拟打字间隔" },
      { key: "proactive_split_max", label: "最多分几段", type: "range", min: 1, max: 5, step: 1, suffix: " 段" },
      { key: "proactive_include_bot", label: "参考自己说过的话", type: "bool", hint: "主动消息时把 bot 自己的回复也放进上下文" },
      { key: "proactive_prompt_private", label: "私聊提示词", type: "text", hint: "支持 {{current_time}} {{unanswered_count}} {{silence_minutes}} {{history}}" },
      { key: "proactive_prompt_group", label: "群聊提示词", type: "text", hint: "同上占位符" },
      { key: "proactive_panel", label: "主动消息面板", type: "proactive_panel" },
      { key: "proactive_test", label: "立即试发一条", type: "action", hint: "用第一个生效对象发一条，验证效果（会真实发送并消耗少量 token）" },
    ],
  },
  {
    id: "interaction",
    icon: "💬",
    title: "互动：回复的细节",
    desc: "引用、@、戳一戳、静默标记和去 AI 味。",
    fields: [
      { key: "quote_rate", label: "引用概率", type: "range", min: 0, max: 100, step: 5, suffix: " %" },
      { key: "at_rate", label: "@ 对方概率", type: "range", min: 0, max: 100, step: 5, suffix: " %" },
      { key: "poke_enabled", label: "允许戳一戳", type: "bool", hint: "模型输出 [poke] 时会戳一下对方" },
      { key: "sanitize", label: "去 AI 味", type: "bool", hint: "清掉 markdown 痕迹和列表符号" },
      { key: "silence_token", label: "静默标记", type: "text", hint: "模型输出这个词时，本条消息不发送" },
    ],
  },
];

const BEHAVIOR_PRESETS = [
  { id: "quiet", name: "安静", desc: "偶尔搭话", patch: { tier_slider: 10, cooldown_sec: 120, skip_probability: 35 } },
  { id: "normal", name: "标准", desc: "日常插嘴", patch: { tier_slider: 40, cooldown_sec: 40, skip_probability: 0 } },
  { id: "chatty", name: "活跃", desc: "经常接话", patch: { tier_slider: 75, cooldown_sec: 20, skip_probability: 0 } },
];

let behaviorCfg = null;
let stickerCfg = null;
let breezeCfg = {};
let behaviorDirty = false;
let behaviorMeta = null;

function markBehaviorDirty(dirty) {
  behaviorDirty = dirty;
  const el = $("#behavior-dirty");
  if (!el) return;
  el.textContent = dirty ? "有未保存的修改" : "没有未保存的修改";
  el.classList.toggle("dirty", dirty);
}

async function loadBehavior() {
  try {
    const d = await api("/api/plugins/config?plugin_id=whale_behavior");
    behaviorCfg = Object.assign({}, d.config || {});
    try {
      const st = await api("/api/plugins/config?plugin_id=sticker_pack");
      stickerCfg = Object.assign({}, st.config || {});
    } catch (e) {
      stickerCfg = stickerCfg || {};
    }
    try {
      const bc = await api("/api/plugins/config?plugin_id=astrbot_plugin_breeze_tts");
      breezeCfg = Object.assign({}, bc.config || {});
    } catch (e) {
      breezeCfg = breezeCfg || {};
    }
    try {
      if (!policyCandidates || !(policyCandidates.groups || []).length) {
        policyCandidates = await api("/api/policy/candidates");
      }
    } catch (e) {}
    try {
      const p = await api("/api/policy");
      behaviorMeta = p.status || null;
    } catch (e) {
      behaviorMeta = null;
    }
    markBehaviorDirty(false);
    renderBehaviorPage();
  } catch (e) {
    toast("读取聊天设置失败：" + e.message);
  }
}

function behaviorFieldHtml(f, plugin) {
  const cfg =
    plugin === "sticker_pack"
      ? stickerCfg || {}
      : plugin === "astrbot_plugin_breeze_tts"
      ? breezeCfg || {}
      : behaviorCfg || {};
  const val = cfg[f.key];
  if (f.type === "bool") {
    return `<div class="behavior-field bool">
      <div>
        <div class="bf-label">${esc(f.label)}</div>
        ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
      </div>
      <label class="switch"><input type="checkbox" data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" ${val ? "checked" : ""} /><span></span></label>
    </div>`;
  }
  if (f.type === "range") {
    const v = Number(val ?? f.min ?? 0);
    return `<div class="behavior-field">
      <div class="bf-head">
        <span class="bf-label">${esc(f.label)}</span>
        <span class="bf-value" data-bout="${esc(f.key)}">${v}${esc(f.suffix || "")}</span>
      </div>
      <input type="range" data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" data-suffix="${esc(f.suffix || "")}" min="${f.min}" max="${f.max}" step="${f.step}" value="${v}" />
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "tags") {
    const tags = (val || []).map(String);
    return `<div class="behavior-field">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <div class="tags">${tags
        .map((t) => `<span class="chip tag-chip2">${esc(t)}<span class="tag-del" data-tag-del="${esc(t)}">×</span></span>`)
        .join("")}</div>
      <div class="tag-add">
        <input type="text" data-tag-input="1" placeholder="输入后回车添加" />
        <button class="btn small" data-tag-add="1">添加</button>
      </div>
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "proactive_panel") {
    return `<div class="behavior-field" style="grid-column:1/-1">
      <div class="bf-head">
        <span class="bf-label">${esc(f.label)}</span>
        <button class="btn small" id="btn-proactive-refresh">刷新</button>
      </div>
      <div id="proactive-ops"><p class="hint">加载中…</p></div>
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "breeze_voices") {
    return `<div class="behavior-field breeze-manager" style="grid-column:1/-1">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <div id="breeze-voice-list"><p class="hint">加载中…</p></div>
      <div class="breeze-upload">
        <input type="text" id="breeze-voice-name" placeholder="音色名字，如：小鲸鱼本音" />
        <input type="file" id="breeze-voice-file" accept="audio/*" />
        <button class="btn small primary" id="btn-breeze-clone">创建克隆音色</button>
      </div>
      <div class="bf-hint">上传 3–60 秒干净人声；Breeze 会自动截取并生成克隆音色。</div>
    </div>`;
  }
  if (f.type === "guide") {
    return `<div class="behavior-field" style="grid-column:1/-1">
      <div class="bf-guide">
        <div class="bf-guide-title">${esc(f.label || "新手引导")}</div>
        <ol class="bf-guide-steps">
          <li>打开 <a href="https://breezeblue.ai" target="_blank">BreezeBlue 官网</a>，用邮箱或 Google 注册并登录（免费版每天 400 积分）。</li>
          <li>登录后进入 <a href="https://breezeblue.ai/app/developer/api-keys" target="_blank">开发者控制台 → API Keys</a>。</li>
          <li>点「Create API Key」，复制以 <code>brz_</code> 开头的 Key。</li>
          <li>回到这里粘贴到上面的输入框，点右下角「保存设置」。</li>
        </ol>
        <div class="bf-guide-links">
          <a class="btn small primary" href="https://breezeblue.ai" target="_blank">注册 / 登录 BreezeBlue</a>
          <a class="btn small" href="https://breezeblue.ai/app/developer/api-keys" target="_blank">打开 API Keys 页面</a>
          <a class="btn small" href="https://breezeblue.ai/zh/pricing" target="_blank">查看价格</a>
        </div>
        <div class="bf-guide-note">Key 只保存在本地插件配置里；免费版 5 个音色槽，克隆音色会占用槽位。</div>
      </div>
    </div>`;
  }
  if (f.type === "action") {
    return `<div class="behavior-field">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <button class="btn small" data-proactive-test="1">发一条试试</button>
      ${f.hint ? `<div class="bf-hint" style="margin-top:8px">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "select") {
    const opts = (f.options || [])
      .map((o) => `<option value="${esc(o.value)}" ${String(val) === String(o.value) ? "selected" : ""}>${esc(o.label)}</option>`)
      .join("");
    return `<div class="behavior-field">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <select class="select" data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" data-type="select">${opts}</select>
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "targets") {
    const list = (val || []).map(String);
    const chips = list
      .map((t) => {
        const [kind, id] = t.split(":");
        const name = targetDisplayName(kind, id);
        const label = `${kind === "group" ? "群" : "私聊"} · ${name}`;
        return `<span class="chip tag-chip2">${esc(label)}<span class="tag-del" data-del-target="${esc(t)}">×</span></span>`;
      })
      .join("");
    return `<div class="behavior-field">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <div class="tags">${chips || `<span class="hint">还没有选择对象</span>`}</div>
      <div class="tag-add">
        <button class="btn small" data-target-pick="private">选好友</button>
        <button class="btn small" data-target-pick="group">选群</button>
      </div>
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.type === "anniversary") {
    const lines = annivLines(val);
    return `<div class="behavior-field anniv-editor" style="grid-column:1/-1">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <div class="anniv-add-row">
        <input type="text" class="anniv-desc" placeholder="是什么日子？比如：Pluto 生日" />
        <div class="anniv-date-wrap">
          <button type="button" class="anniv-date-btn" data-anniv-date-toggle="1">
            <span class="anniv-date-text">选择日期</span>
          </button>
          <div class="anniv-picker hidden"></div>
        </div>
        <button class="btn small primary" data-anniv-add="1">添加</button>
      </div>
      <div class="anniv-list">${annivListHtml(lines)}</div>
      <input type="text" data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" value="${esc(lines.join("\n"))}" style="display:none" />
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  if (f.multiline) {
    return `<div class="behavior-field" style="grid-column:1/-1">
      <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
      <textarea data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" rows="4" style="width:100%;resize:vertical;background:var(--input-bg,#141a24);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:10px;font-family:inherit">${esc(val ?? "")}</textarea>
      ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    </div>`;
  }
  return `<div class="behavior-field">
    <div class="bf-label" style="margin-bottom:8px">${esc(f.label)}</div>
    <input type="${f.type === "password" ? "password" : "text"}" data-bkey="${esc(f.key)}" data-bplugin="${esc(plugin || "whale_behavior")}" value="${esc(val ?? "")}" autocomplete="off" />
    ${f.hint ? `<div class="bf-hint">${esc(f.hint)}</div>` : ""}
    ${f.link ? `<div class="bf-hint"><a href="${esc(f.link.url)}" target="_blank">${esc(f.link.text)}</a></div>` : ""}
  </div>`;
}

function targetDisplayName(kind, id) {
  const cand = policyCandidates || {};
  if (kind === "group") {
    const g = (cand.groups || []).find((x) => String(x.id) === String(id));
    return g && g.name ? `${g.name}（${id}）` : id;
  }
  const p = (cand.people || []).find((x) => String(x.id) === String(id));
  return p && p.name ? `${p.name}（${id}）` : id;
}

function renderBehaviorPage() {
  const presetBox = $("#behavior-presets");
  const tier = Number(behaviorCfg.tier_slider ?? 0);
  const activePreset = BEHAVIOR_PRESETS.find((p) => p.patch.tier_slider === tier);
  presetBox.innerHTML = BEHAVIOR_PRESETS.map(
    (p) => `<button class="preset-btn ${activePreset && activePreset.id === p.id ? "active" : ""}" data-preset="${p.id}">
      <b>${p.name}</b>${p.desc}
    </button>`
  ).join("");

  const levelText = behaviorMeta
    ? `当前响应等级 <b>${behaviorMeta.level} 级</b>（${behaviorMeta.in_peak ? "高峰" : "低谷"}时段 ${behaviorMeta.now}）`
    : "";
  $("#behavior-sections").innerHTML =
    (levelText ? `<div class="card" style="padding:12px 16px;margin-bottom:14px"><span class="hint">${levelText} · 由「响应策略」控制</span></div>` : "") +
    BEHAVIOR_SECTIONS.map(
      (sec) => `<div class="card behavior-section">
        <div class="card-head" style="margin-bottom:4px">
          <h3>${sec.icon} ${sec.title}</h3>
        </div>
        <p class="sec-desc" style="margin:0 0 12px;font-size:12px;color:var(--muted)">${sec.desc}</p>
        <div class="behavior-grid">${sec.fields.map((f) => behaviorFieldHtml(f, f.plugin || sec.plugin)).join("")}</div>
      </div>`
    ).join("");

  // 滑条实时数值
  $$("#behavior-sections input[type=range]").forEach((el) =>
    el.addEventListener("input", () => {
      const out = $(`#behavior-sections [data-bout="${el.dataset.bkey}"]`);
      if (out) out.textContent = el.value + (el.dataset.suffix || "");
      markBehaviorDirty(true);
    })
  );
  $$("#behavior-sections input[type=checkbox], #behavior-sections input[type=text]").forEach((el) => {
    if (el.dataset.tagInput) return;
    el.addEventListener("change", () => markBehaviorDirty(true));
    el.addEventListener("input", () => markBehaviorDirty(true));
  });

  // 关键词
  const addTag = () => {
    const input = $("#behavior-sections [data-tag-input]");
    const text = (input && input.value || "").trim();
    if (!text) return;
    const list = (behaviorCfg.keywords || []).map(String);
    if (!list.includes(text)) list.push(text);
    behaviorCfg.keywords = list;
    markBehaviorDirty(true);
    renderBehaviorPage();
  };
  $$("#behavior-sections [data-tag-add]").forEach((btn) => btn.addEventListener("click", addTag));
  $$("#behavior-sections [data-tag-input]").forEach((input) =>
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addTag();
      }
    })
  );
  $$("#behavior-sections [data-tag-del]").forEach((el) =>
    el.addEventListener("click", () => {
      behaviorCfg.keywords = (behaviorCfg.keywords || []).map(String).filter((t) => t !== el.dataset.tagDel);
      markBehaviorDirty(true);
      renderBehaviorPage();
    })
  );

  // 主动聊天对象
  $$("#behavior-sections [data-target-pick]").forEach((btn) =>
    btn.addEventListener("click", () => openTargetPicker(btn.dataset.targetPick))
  );
  $$("#behavior-sections [data-del-target]").forEach((el) =>
    el.addEventListener("click", () => {
      behaviorCfg.proactive_targets = (behaviorCfg.proactive_targets || []).map(String).filter((t) => t !== el.dataset.delTarget);
      markBehaviorDirty(true);
      renderBehaviorPage();
    })
  );

  if (document.getElementById("proactive-ops")) loadProactivePanel();
  if (document.querySelector(".breeze-manager")) loadBreezeVoices();

  // 主动聊天试发
  $$("#behavior-sections [data-proactive-test]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const targets = (behaviorCfg.proactive_targets || []).map(String);
      if (!targets.length) {
        toast("先在「生效对象」里选一个好友或群");
        return;
      }
      btn.disabled = true;
      btn.textContent = "发送中…";
      try {
        const r = await api("/api/proactive/test", {
          method: "POST",
          body: JSON.stringify({ target: targets[0] }),
        });
        toast(r.ok ? `已发送：${r.text}` : r.error || "发送失败", 4000);
      } catch (e) {
        toast("发送失败：" + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "发一条试试";
      }
    })
  );

  // 预设
  $$("#behavior-presets [data-preset]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const preset = BEHAVIOR_PRESETS.find((p) => p.id === btn.dataset.preset);
      if (!preset) return;
      Object.assign(behaviorCfg, preset.patch);
      markBehaviorDirty(true);
      renderBehaviorPage();
    })
  );
}

$("#btn-save-behavior").addEventListener("click", async () => {
  if (!behaviorCfg) return;
  const btn = $("#btn-save-behavior");
  const patches = { whale_behavior: {}, sticker_pack: {} };
  $$("#behavior-sections [data-bkey]").forEach((el) => {
    const key = el.dataset.bkey;
    const plugin = el.dataset.bplugin || "whale_behavior";
    const target = patches[plugin] || (patches[plugin] = {});
    if (el.type === "checkbox") target[key] = el.checked;
    else if (el.type === "range") target[key] = Number(el.value);
    else if (el.tagName === "SELECT") target[key] = el.value;
    else if (el.type === "text" || el.type === "password" || el.tagName === "TEXTAREA") target[key] = el.value;
  });
  if (patches.astrbot_plugin_breeze_tts && !patches.astrbot_plugin_breeze_tts.api_key) {
    patches.astrbot_plugin_breeze_tts.api_key = (breezeCfg || {}).api_key || "";
  }
  patches.whale_behavior.keywords = (behaviorCfg.keywords || []).map(String);
  patches.whale_behavior.proactive_targets = (behaviorCfg.proactive_targets || []).map(String);
  const mergedWhale = Object.assign({}, behaviorCfg, patches.whale_behavior);
  const mergedSticker = Object.assign({}, stickerCfg || {}, patches.sticker_pack);
  const mergedBreeze = Object.assign({}, breezeCfg || {}, patches.astrbot_plugin_breeze_tts || {});
  btn.disabled = true;
  try {
    const r1 = await api("/api/plugins/config/save", {
      method: "POST",
      body: JSON.stringify({ plugin_id: "whale_behavior", config: mergedWhale }),
    });
    const r2 = await api("/api/plugins/config/save", {
      method: "POST",
      body: JSON.stringify({ plugin_id: "sticker_pack", config: mergedSticker }),
    });
    const rb = await api("/api/plugins/config/save", {
      method: "POST",
      body: JSON.stringify({ plugin_id: "astrbot_plugin_breeze_tts", config: mergedBreeze }),
    });
    const ok = r1.ok && r2.ok && rb.ok;
    toast(ok ? "已保存并重载插件" : (r1.error || r2.error || rb.error || "保存失败"));
    if (ok) {
      behaviorCfg = mergedWhale;
      stickerCfg = mergedSticker;
      breezeCfg = mergedBreeze;
      markBehaviorDirty(false);
    }
  } catch (e) {
    toast("保存失败：" + e.message);
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- 表情包 ---------------- */
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const stickerPending = []; // {file, data, auto:{desc,tags}, tagging, error}

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result || ""));
    fr.onerror = () => reject(fr.error || new Error("读取文件失败"));
    fr.readAsDataURL(file);
  });
}

function renderStickerPending() {
  const box = $("#sticker-pending");
  if (!stickerPending.length) {
    box.innerHTML = "";
    $("#btn-confirm-sticker").disabled = true;
    $("#btn-confirm-sticker").textContent = "上传";
    return;
  }
  box.innerHTML = stickerPending
    .map((p, i) => {
      const st = p.tagging
        ? "识别中…"
        : p.auto && (p.auto.desc || (p.auto.tags || []).length)
        ? `${esc(p.auto.desc || "").slice(0, 40)}`
        : p.error
        ? `识别失败`
        : "未识别";
      return `<div class="pending-item" data-idx="${i}" title="点击修改这张的描述/标签">
        <img src="${p.data}" alt="" />
        <div>${esc(p.file.name)}</div>
        <div class="tag">${st}</div>
      </div>`;
    })
    .join("");
  $("#btn-confirm-sticker").disabled = stickerPending.some((p) => p.tagging);
  $("#btn-confirm-sticker").textContent = `上传 ${stickerPending.length} 张`;

  $$("#sticker-pending .pending-item").forEach((el) =>
    el.addEventListener("click", async () => {
      const idx = Number(el.dataset.idx);
      const p = stickerPending[idx];
      if (!p) return;
      const res = await modalPrompt({
        title: "这张表情的描述",
        fields: [
          { key: "desc", label: "描述（模型据此判断何时发它）", type: "textarea", value: (p.auto && p.auto.desc) || "" },
          { key: "tags", label: "标签（逗号分隔，第一个决定分类）", value: ((p.auto && p.auto.tags) || []).join(",") },
        ],
      });
      if (!res) return;
      p.auto = {
        desc: res.desc || "",
        tags: String(res.tags || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean),
      };
      renderStickerPending();
      syncPendingToInputs();
    })
  );
}

function syncPendingToInputs() {
  if (stickerPending.length !== 1) return;
  const p = stickerPending[0];
  if (p && p.auto) {
    $("#sticker-desc").value = p.auto.desc || $("#sticker-desc").value;
    $("#sticker-tags").value = (p.auto.tags || []).join(",") || $("#sticker-tags").value;
  }
}

async function autoTagPending() {
  for (const p of stickerPending) {
    if (!p.tagging) continue;
    try {
      const r = await api("/api/sticker/auto-tag", {
        method: "POST",
        body: JSON.stringify({ filename: p.file.name, data: p.data }),
      });
      if (r.ok) {
        p.auto = { desc: r.desc || "", tags: r.tags || [] };
      } else {
        p.error = r.error || "识别失败";
      }
    } catch (e) {
      p.error = e.message;
    }
    p.tagging = false;
    renderStickerPending();
    syncPendingToInputs();
  }
  const okCount = stickerPending.filter((p) => p.auto).length;
  $("#sticker-status").textContent = okCount
    ? `AI 已识别 ${okCount} 张，可修改描述/标签后上传`
    : "识别失败，可手动填写描述后上传";
}

let stickerCache = [];
let stickerTagQuery = "";

async function loadStickers() {
  try {
    stickerCache = await api("/api/stickers");
    $("#sticker-count").textContent = `共 ${stickerCache.length} 个`;
    const tags = stickerTagCounts(stickerCache);
    if (!tags.some((t) => t.name === state.stickerFilter) && state.stickerFilter !== "全部") {
      state.stickerFilter = "全部";
    }
    if (window.__stickerTagDeep) {
      state.stickerFilter = window.__stickerTagDeep;
      window.__stickerTagDeep = "";
    }
    renderStickerTagList();
    renderStickerGrid();
    bindStickerTagSearch();
  } catch (e) {
    toast("读取表情失败：" + e.message);
  }
}

function stickerTagCounts(list) {
  const map = new Map();
  for (const s of list) {
    const tag = ((s.tags && s.tags[0]) || "未分组").trim() || "未分组";
    map.set(tag, (map.get(tag) || 0) + 1);
  }
  return Array.from(map.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh"));
}

function bindStickerTagSearch() {
  const input = $("#sticker-tag-search");
  if (!input || input._bound) return;
  input._bound = true;
  input.addEventListener("input", () => {
    stickerTagQuery = input.value.trim().toLowerCase();
    renderStickerTagList();
  });
}

function renderStickerTagList() {
  const tags = stickerTagCounts(stickerCache);
  const q = stickerTagQuery;
  const rows = [];
  rows.push(`<div class="tag-item ${state.stickerFilter === "全部" ? "active" : ""}" data-tag="全部">
    <span class="tag-name">全部</span><span class="cnt">${stickerCache.length}</span>
  </div>`);
  for (const t of tags) {
    if (q && !t.name.toLowerCase().includes(q)) continue;
    rows.push(`<div class="tag-item ${state.stickerFilter === t.name ? "active" : ""}" data-tag="${esc(t.name)}">
      <span class="tag-name" title="${esc(t.name)}">${esc(t.name)}</span><span class="cnt">${t.count}</span>
    </div>`);
  }
  if (rows.length === 1 && q) {
    rows.push(`<div class="tag-item" style="cursor:default;color:var(--muted)">没有匹配的标签</div>`);
  }
  $("#sticker-tags-bar").innerHTML = rows.join("");
  $$("#sticker-tags-bar [data-tag]").forEach((el) =>
    el.addEventListener("click", () => {
      state.stickerFilter = el.dataset.tag;
      renderStickerTagList();
      renderStickerGrid();
    })
  );
}

function renderStickerGrid() {
  const filtered =
    state.stickerFilter === "全部"
      ? stickerCache
      : stickerCache.filter(
          (s) => (((s.tags && s.tags[0]) || "未分组").trim() || "未分组") === state.stickerFilter
        );

  const cur = $("#sticker-current");
  if (state.stickerFilter === "全部") {
    cur.innerHTML = `<span>全部表情</span><b>${filtered.length}</b><span>个</span>`;
  } else {
    cur.innerHTML = `<span>分类</span><b>${esc(state.stickerFilter)}</b><span>· ${filtered.length} 个</span>
      <button class="btn small" id="sticker-clear-filter" style="margin-left:auto">返回全部</button>`;
  }
  const clearBtn = $("#sticker-clear-filter");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.stickerFilter = "全部";
      renderStickerTagList();
      renderStickerGrid();
    });
  }

  if (!filtered.length) {
    $("#sticker-grid").innerHTML = `<div class="hint">这个分类下还没有表情</div>`;
    return;
  }

  $("#sticker-grid").innerHTML = filtered
    .map(
      (s) => `<div class="sticker">
        ${s.exists ? `<img src="/api/sticker-image?file=${encodeURIComponent(s.file)}" loading="lazy" alt="${esc(s.id)}" />` : `<div class="hint">图片缺失：${esc(s.file)}</div>`}
        <div class="desc">${esc(s.desc) || "（无描述，模型不好选它）"}</div>
        <div class="id">${esc((s.tags && s.tags[0]) || "未分组")}</div>
        <div class="sticker-ops">
          <button class="btn small" data-edit="${esc(s.id)}">改描述</button>
          <button class="btn small" data-ai="${esc(s.id)}">AI 识别</button>
          <button class="btn small danger" data-del="${esc(s.id)}">删除</button>
        </div>
      </div>`
    )
    .join("");

  bindStickerCardActions();
}

function bindStickerCardActions() {
  $$("#sticker-grid [data-del]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.del;
      if (!(await modalConfirm({
      title: "删除表情",
      message: `删除表情 ${id}？\n会移到 stickers/.trash 目录，可手动找回。`,
      okText: "确认删除",
    }))) return;
      const r = await api("/api/sticker/delete", { method: "POST", body: JSON.stringify({ id }) });
      toast(r.ok ? "已删除" : r.error || "删除失败");
      loadStickers();
    })
  );

  $$("#sticker-grid [data-edit]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.edit;
      const cur = stickerCache.find((x) => x.id === id) || {};
      const res = await modalPrompt({
        title: "修改表情描述",
        fields: [
          { key: "desc", label: "描述（模型据此判断何时发它）", type: "textarea", value: cur.desc || "" },
          { key: "tags", label: "标签（逗号分隔，第一个标签决定分类）", value: (cur.tags || []).join(",") },
        ],
        okText: "保存",
      });
      if (!res) return;
      const desc = res.desc || "";
      const tags = String(res.tags || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean);
      const r = await api("/api/sticker/update", { method: "POST", body: JSON.stringify({ id, desc, tags }) });
      toast(r.ok ? "已更新" : r.error || "更新失败");
      loadStickers();
    })
  );

  $$("#sticker-grid [data-ai]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.ai;
      btn.disabled = true;
      btn.textContent = "识别中…";
      try {
        const r = await api("/api/sticker/auto-tag", { method: "POST", body: JSON.stringify({ id }) });
        if (!r.ok) {
          toast(r.error || "识别失败");
          return;
        }
        const res = await modalPrompt({
          title: "AI 识别结果（可修改）",
          fields: [
            { key: "desc", label: "描述", type: "textarea", value: r.desc || "" },
            { key: "tags", label: "标签（逗号分隔，第一个决定分类）", value: (r.tags || []).join(",") },
          ],
          okText: "保存",
        });
        if (!res) return;
        const desc = res.desc || "";
        const tags = String(res.tags || "");
        const up = await api("/api/sticker/update", {
          method: "POST",
          body: JSON.stringify({ id, desc, tags: tags.split(/[,，]/).map((x) => x.trim()).filter(Boolean) }),
        });
        toast(up.ok ? "已更新为 AI 识别结果" : up.error || "更新失败");
        loadStickers();
      } finally {
        btn.disabled = false;
        btn.textContent = "AI 识别";
      }
    })
  );
}

const IMG_RE = /\.(png|jpe?g|gif|webp)$/i;

async function enqueueFiles(fileList) {
  const files = Array.from(fileList || []).filter((f) => IMG_RE.test(f.name || ""));
  if (!files.length) {
    toast("没有可用的图片文件（png/jpg/gif/webp）");
    return;
  }
  const room = 200 - stickerPending.length;
  if (room <= 0) {
    toast("待上传队列最多 200 张，先上传或刷新页面");
    return;
  }
  const use = files.slice(0, room);
  if (use.length < files.length) toast(`一次最多 200 张，已取前 ${use.length} 张`);
  const auto = $("#sticker-auto-tag").checked;
  const items = use.map((f) => ({ file: f, data: "", auto: null, tagging: auto, error: "" }));
  stickerPending.push(...items);
  renderStickerPending();
  for (const it of items) {
    try {
      it.data = await readAsDataURL(it.file);
    } catch (err) {
      it.error = "读取失败";
      it.tagging = false;
    }
  }
  renderStickerPending();
  if (auto) await autoTagPending();
  else {
    $("#sticker-status").textContent = "已选择 " + stickerPending.length + " 张，填好描述后上传";
    $("#btn-confirm-sticker").disabled = false;
  }
}

async function entriesFromDataTransfer(dt) {
  const out = [];
  const items = Array.from(dt.items || []);
  const entries = items.map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null)).filter(Boolean);
  if (!entries.length) return Array.from(dt.files || []);

  async function walk(entry) {
    if (!entry) return;
    if (entry.isFile) {
      const file = await new Promise((res) => entry.file((f) => res(f), () => res(null)));
      if (file) out.push(file);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const readBatch = () => new Promise((res) => reader.readEntries((r) => res(r), () => res([])));
      let batch = await readBatch();
      while (batch.length) {
        for (const e of batch) await walk(e);
        batch = await readBatch();
      }
    }
  }

  for (const e of entries) await walk(e);
  return out;
}

$("#btn-pick-sticker").addEventListener("click", () => $("#sticker-file").click());
$("#sticker-file").addEventListener("change", async (e) => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  await enqueueFiles(files);
});

$("#btn-import-folder").addEventListener("click", () => $("#sticker-folder").click());
$("#sticker-folder").addEventListener("change", async (e) => {
  const files = Array.from(e.target.files || []);
  e.target.value = "";
  await enqueueFiles(files);
});

/* 拖拽上传（支持整个文件夹，递归子目录） */
(function bindStickerDrop() {
  const panel = document.getElementById("tab-stickers");
  if (!panel) return;
  let depth = 0;
  panel.addEventListener("dragenter", (e) => {
    e.preventDefault();
    depth++;
    panel.classList.add("dragover");
  });
  panel.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  panel.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (depth === 0) panel.classList.remove("dragover");
  });
  panel.addEventListener("drop", async (e) => {
    e.preventDefault();
    depth = 0;
    panel.classList.remove("dragover");
    const files = await entriesFromDataTransfer(e.dataTransfer);
    await enqueueFiles(files);
  });
})();

$("#btn-confirm-sticker").addEventListener("click", async () => {
  if (!stickerPending.length) return;
  const single = stickerPending.length === 1;
  const editedDesc = $("#sticker-desc").value.trim();
  const editedTags = $("#sticker-tags").value.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  let ok = 0;
  let fail = 0;
  for (const p of stickerPending) {
    const desc = single ? editedDesc || (p.auto && p.auto.desc) || "" : (p.auto && p.auto.desc) || "";
    const tags = single ? editedTags : (p.auto && p.auto.tags) || [];
    try {
      const r = await api("/api/sticker/add", {
        method: "POST",
        body: JSON.stringify({ filename: p.file.name, data: p.data, desc, tags }),
      });
      if (r.ok) ok++;
      else {
        fail++;
        toast(`${p.file.name}: ${r.error || "失败"}`);
      }
    } catch (err) {
      fail++;
      toast(`${p.file.name}: ${err.message}`);
    }
  }
  stickerPending.length = 0;
  $("#sticker-desc").value = "";
  $("#sticker-tags").value = "";
  renderStickerPending();
  $("#sticker-status").textContent = `已上传 ${ok} 张${fail ? `，失败 ${fail} 张` : ""}`;
  loadStickers();
});

/* ---------------- 人物档案 ---------------- */
let memGroups = [];
let memPeople = [];

function memAvatar(text) {
  const ch = String(text || "?").trim().slice(0, 1) || "?";
  return esc(ch);
}

function flattenPeople(groups) {
  const map = new Map();
  for (const g of groups || []) {
    for (const m of g.members || []) {
      const key = String(m.uid || `${g.group}:${m.name}`);
      if (!map.has(key)) {
        map.set(key, {
          uid: String(m.uid || ""),
          name: m.name || "未命名",
          notes: [],
          groups: [],
        });
      }
      const p = map.get(key);
      for (const n of m.notes || []) {
        if (!p.notes.includes(n)) p.notes.push(n);
      }
      if (g.group && !p.groups.includes(g.group)) p.groups.push(g.group);
    }
  }
  const collator = new Intl.Collator("zh-Hans-CN", { sensitivity: "base", numeric: true });
  return [...map.values()].sort((a, b) => collator.compare(a.name, b.name));
}

async function loadMemory() {
  const box = $("#memory-list");
  try {
    memGroups = await api("/api/memory");
    memPeople = flattenPeople(memGroups);
    if (!memPeople.length) {
      box.innerHTML = `<div class="empty-state">
        <div class="empty-icon">🧠</div>
        <div class="empty-title">还没有人物档案</div>
        <div class="empty-desc">小鲸鱼记住值得长期保留的信息后，会按人物整理到这里。</div>
      </div>`;
      return;
    }
    box.innerHTML = memPeople
      .map(
        (p) => `<div class="mem-card" data-open-person="${esc(p.uid)}">
          <div class="mem-card-main">
            <div class="mem-avatar">${memAvatar(p.name)}</div>
            <div>
              <div class="mem-card-title">${esc(p.name)}</div>
              <div class="mem-card-sub">${p.notes.length} 条记忆${p.groups.length > 1 ? ` · ${p.groups.length} 个场景` : ""}</div>
            </div>
          </div>
          <div class="mem-card-actions">
            <button class="btn small danger" data-clear-person="${esc(p.uid)}">清空</button>
          </div>
        </div>`
      )
      .join("");

    $$("[data-open-person]").forEach((el) =>
      el.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openPersonDetail(el.dataset.openPerson);
      })
    );
    $$("[data-clear-person]").forEach((btn) =>
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const p = memPeople.find((x) => String(x.uid) === String(btn.dataset.clearPerson));
        if (!p) return;
        if (!(await modalConfirm({ title: "清空人物记忆", message: `清空 ${p.name} 的全部记忆？`, okText: "确认清空" }))) return;
        for (const group of p.groups) {
          await api("/api/memory/clear", { method: "POST", body: JSON.stringify({ group, uid: p.uid }) });
        }
        toast("已清空");
        loadMemory();
      })
    );

    // 深链：#memory/<uid>
    const raw = window.__memDeepLink || (location.hash || "");
    const parts = raw.replace("#", "").split("/");
    if (parts[0] === "memory" && parts[1]) {
      window.__memDeepLink = "";
      openPersonDetail(parts[1]);
    }
  } catch (e) {
    box.innerHTML = `<div class="hint">读取档案失败：${esc(e.message)}</div>`;
  }
}

function closeMemModal() {
  $("#mem-modal").classList.add("hidden");
}

$("#mem-modal-close")?.addEventListener("click", closeMemModal);
$("#mem-modal")?.addEventListener("click", (e) => {
  if (e.target && e.target.id === "mem-modal") closeMemModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const modal = $("#mem-modal");
  if (modal && !modal.classList.contains("hidden")) closeMemModal();
});

function showMemModal(title, bodyHtml) {
  $("#mem-modal-title").textContent = title;
  $("#mem-modal-body").innerHTML = bodyHtml;
  $("#mem-modal").classList.remove("hidden");
}

function openPersonDetail(uid) {
  const p = memPeople.find((x) => String(x.uid) === String(uid));
  if (!p) return;
  const body = `
    <div class="detail-row"><span class="detail-key">昵称</span><span class="detail-val">${esc(p.name)}</span></div>
    <div class="detail-section">
      <h4>记住的事</h4>
      ${p.notes.length
        ? p.notes.map((n) => `<div class="detail-note">· ${esc(n)}</div>`).join("")
        : `<div class="hint">（还没有笔记）</div>`}
    </div>
    <div class="modal-actions">
      <button class="btn small danger" id="mem-clear-person-detail">清空这个人</button>
    </div>`;
  showMemModal(p.name, body);

  $("#mem-clear-person-detail").addEventListener("click", async () => {
    if (!(await modalConfirm({ title: "清空人物记忆", message: `清空 ${p.name} 的全部记忆？`, okText: "确认清空" }))) return;
    for (const group of p.groups) {
      await api("/api/memory/clear", { method: "POST", body: JSON.stringify({ group, uid: p.uid }) });
    }
    toast("已清空");
    closeMemModal();
    loadMemory();
  });
}

/* ---------------- 日志 ---------------- */
async function loadLog() {
  try {
    const r = await api(`/api/logs?target=${state.logTarget}&lines=300`);
    const level = ($("#log-level") && $("#log-level").value) || "all";
    const kw = (($("#log-search") && $("#log-search").value) || "").trim().toLowerCase();
    let lines = r.lines || [];
    if (level === "error") lines = lines.filter((l) => /error|exception|traceback|失败|错误/i.test(l));
    else if (level === "warn") lines = lines.filter((l) => /warn|error|exception|失败|错误/i.test(l));
    if (kw) lines = lines.filter((l) => l.toLowerCase().includes(kw));
    const view = $("#log-view");
    view.textContent = lines.join("\n") || "（没有匹配的日志）";
    view.scrollTop = view.scrollHeight;
  } catch (e) {
    $("#log-view").textContent = "读取日志失败：" + e.message;
  }
}

$("#log-search").addEventListener("input", loadLog);
$("#log-level").addEventListener("change", loadLog);

$$(".tab-btn").forEach((btn) =>
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.logTarget = btn.dataset.log;
    loadLog();
  })
);

$("#btn-refresh-log").addEventListener("click", loadLog);
$("#log-auto").addEventListener("change", (e) => {
  state.logAuto = e.target.checked;
  clearInterval(state.logTimer);
  if (state.logAuto) state.logTimer = setInterval(loadLog, 3000);
});

/* ---------------- 管理端链接 ---------------- */
function refreshLinks() {
  const s = state.status;
  if (!s) return;
  $("#link-astrbot").href = s.astrbot.webui;
  if (s.napcat.webui_url) $("#link-napcat").href = s.napcat.webui_url;
  $("#qr-image").src = `/api/qr?t=${Date.now()}`;
}

/* ---------------- 启动 ---------------- */
$("#btn-refresh").addEventListener("click", refreshStatus);
setInterval(() => ($("#clock").textContent = fmtTime()), 1000);
const initialHash = (location.hash || "").replace("#", "");
window.__memDeepLink = initialHash.startsWith("memory") ? initialHash : "";
window.__pluginUninstallDeep = initialHash.startsWith("plugins/uninstall/") ? initialHash.split("/")[2] : "";
window.__policyPick = initialHash === "policy/pick-group" ? "group" : initialHash === "policy/pick-private" ? "private" : "";
window.__stickerTagDeep = initialHash.startsWith("stickers/") ? decodeURIComponent(initialHash.slice(9)) : "";
window.__pluginDeep = initialHash.startsWith("plugins/") && !window.__pluginUninstallDeep ? initialHash.split("/")[1] : "";
const initialTab = initialHash.split("/")[0];
if (initialTab && document.getElementById(`tab-${initialTab}`)) switchTab(initialTab);
refreshStatus();
state.statusTimer = setInterval(refreshStatus, 5000);

/* ---------------- 首次运行引导 ---------------- */
async function loadReady() {
  const box = $("#firstrun");
  if (!box) return;
  try {
    const r = await api("/api/ready");
    if (r.ready || sessionStorage.getItem("firstrun-dismissed")) {
      box.innerHTML = "";
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    const li = (r.issues || [])
      .map((i) => {
        const go = i.tab ? ` <a href="#${i.tab}" data-goto="${i.tab}">去处理</a>` : "";
        return `<li><b>${i.title}</b> — ${i.hint}${go}</li>`;
      })
      .join("");
    box.innerHTML = `<div class="firstrun-card">
        <div class="firstrun-head">
          <h3>首次运行：还差 ${r.issues.length} 项</h3>
          <button class="btn small" id="firstrun-close">先隐藏</button>
        </div>
        <ul class="firstrun-list">${li}</ul>
        <div class="hint">检查时间 ${r.checked_at}。完成后会自动消失。</div>
      </div>`;
    $("#firstrun-close").onclick = () => {
      sessionStorage.setItem("firstrun-dismissed", "1");
      box.innerHTML = "";
      box.classList.add("hidden");
    };
    box.querySelectorAll("[data-goto]").forEach((a) =>
      a.addEventListener("click", (e) => {
        e.preventDefault();
        switchTab(a.dataset.goto);
      })
    );
  } catch (e) {
    /* 后端不可用时不打扰，状态卡已经会提示 */
  }
}
loadReady();
setInterval(loadReady, 60000);


/* ---------------- 设置页 ---------------- */
async function loadSettings() {
  try {
    const s = await api("/api/settings");
    $("#set-close").value = s.closeAction || "quit";
    $("#set-autostart").checked = !!s.autoStart;
    $("#set-compress").checked = s.autoCompress !== false;
    if (state.status && state.status.napcat) {
      $("#about-bot").textContent = state.status.napcat.uin ? "小鲸鱼 · 已登录" : "未登录";
    }
  } catch (e) {
    toast("读取设置失败：" + e.message);
  }
}

async function saveSettings(patch, desc) {
  try {
    const s = await api("/api/settings/save", { method: "POST", body: JSON.stringify(patch) });
    $("#settings-hint").textContent = desc ? `已保存：${desc}` : "已保存";
    if ("autoStart" in patch) $("#set-autostart").checked = !!s.autoStart;
    if ("autoCompress" in patch) $("#set-compress").checked = s.autoCompress !== false;
    if ("closeAction" in patch) $("#set-close").value = s.closeAction;
    toast(desc ? `已保存：${desc}` : "已保存");
  } catch (e) {
    toast("保存失败：" + e.message);
    // 保存失败时以服务端真实状态为准，别让开关停在错误位置
    try {
      const s = await api("/api/settings");
      $("#set-autostart").checked = !!s.autoStart;
      $("#set-compress").checked = s.autoCompress !== false;
      $("#set-close").value = s.closeAction;
    } catch (e2) {
      /* 读取也失败就保持原样 */
    }
  }
}

$("#set-close").addEventListener("change", (e) =>
  saveSettings({ closeAction: e.target.value }, e.target.value === "tray" ? "关闭窗口时收到托盘" : "关闭窗口时退出软件")
);
$("#set-autostart").addEventListener("change", (e) =>
  saveSettings({ autoStart: e.target.checked }, e.target.checked ? "已开启开机自启" : "已关闭开机自启")
);
$("#set-compress").addEventListener("change", (e) =>
  saveSettings({ autoCompress: e.target.checked }, e.target.checked ? "上传时自动压缩" : "不压缩原图")
);


/* ---------------- 插件管理 ---------------- */
let pluginCache = [];
let pluginConfigState = null;

function pluginStatusBadge(p) {
  return p.activated
    ? '<span class="plugin-badge ok">运行中</span>'
    : '<span class="plugin-badge off">已禁用</span>';
}

function pluginCard(p) {
  const conflicts = (p.conflicts || [])
    .map(
      (c) =>
        `⚠ 与 ${esc(c.display_name || c.plugin)} 功能重叠：${esc(c.reason)}` +
        (c.other_active
          ? ` <button class="btn small" data-disable-other="${esc(c.plugin)}">禁用 ${esc(c.display_name || c.plugin)}</button>`
          : ` <span class="plugin-badge off">对方已禁用</span>`)
    )
    .join("<br>");
  const adv = p.advanced_tab
    ? `<button class="btn small" data-advanced="${esc(p.advanced_tab)}">高级面板</button>`
    : "";
  return `<div class="plugin-card ${p.activated ? "on" : "off"}" data-plugin="${esc(p.name)}">
    <div class="plugin-head">
      <div>
        <div class="plugin-title">${esc(p.display_name)} <small>${esc(p.name)}</small></div>
        <div class="plugin-meta">v${esc(p.version)}${p.author ? " · " + esc(p.author) : ""}${p.reserved ? " · 内置" : ""}
          ${p.local_modified ? `<span class="plugin-badge warn" title="${esc(p.modify_note || "")}">源码已改动，谨慎更新</span>` : ""}
        </div>
      </div>
      <div>${pluginStatusBadge(p)}</div>
    </div>
    <div class="plugin-desc">${esc(p.desc) || "（无描述）"}</div>
    ${conflicts ? `<div class="plugin-conflicts">${conflicts}</div>` : ""}
    <div class="plugin-actions">
      <label class="switch" title="启用 / 禁用">
        <input type="checkbox" data-toggle="${esc(p.name)}" ${p.activated ? "checked" : ""} />
        <span></span>
      </label>
      <span class="spacer"></span>
      <button class="btn small" data-settings="${esc(p.name)}">设置</button>
      <button class="btn small" data-reload="${esc(p.name)}">重载</button>
      ${adv}
      ${p.reserved ? "" : `<button class="btn small danger" data-uninstall="${esc(p.name)}">卸载</button>`}
    </div>
  </div>`;
}

async function loadPlugins() {
  const box = $("#plugins-list");
  try {
    const data = await api("/api/plugins");
    pluginCache = data.plugins || [];
    const mine = pluginCache.filter((p) => p.advanced_tab);
    const builtin = pluginCache.filter((p) => !p.advanced_tab && p.reserved);
    const third = pluginCache.filter((p) => !p.advanced_tab && !p.reserved);
    const active = pluginCache.filter((p) => p.activated).length;
    $("#plugins-summary").textContent = `${pluginCache.length} 个插件 · ${active} 个运行中`;

    const section = (title, list) =>
      list.length
        ? `<div class="plugin-section"><h4>${title} <span>${list.length} 个</span></h4>${list.map(pluginCard).join("")}</div>`
        : "";

    box.innerHTML =
      section("我的插件", mine) +
        section("内置插件", builtin) +
        section("第三方插件", third) || `<div class="hint">没有插件</div>`;

    bindPluginActions();

    if (window.__pluginUninstallDeep) {
      const target = window.__pluginUninstallDeep;
      window.__pluginUninstallDeep = "";
      openUninstallModal(target);
    }
    if (window.__pluginDeep) {
      const target = window.__pluginDeep;
      window.__pluginDeep = "";
      openPluginSettings(target);
    }
  } catch (e) {
    box.innerHTML = `<div class="hint">读取插件失败：${esc(e.message)}</div>`;
  }
}

function bindPluginActions() {
  $$("#plugins-list [data-toggle]").forEach((el) =>
    el.addEventListener("change", async () => {
      const name = el.dataset.toggle;
      el.disabled = true;
      try {
        const r = await api("/api/plugins/toggle", {
          method: "POST",
          body: JSON.stringify({ plugin_id: name, enabled: el.checked }),
        });
        toast(r.ok ? `${el.checked ? "已启用" : "已禁用"} ${name}` : r.error || "操作失败");
      } catch (e) {
        toast("操作失败：" + e.message);
        el.checked = !el.checked;
      } finally {
        el.disabled = false;
        loadPlugins();
      }
    })
  );

  $$("#plugins-list [data-settings]").forEach((el) =>
    el.addEventListener("click", () => openPluginSettings(el.dataset.settings))
  );

  $$("#plugins-list [data-reload]").forEach((el) =>
    el.addEventListener("click", async () => {
      el.disabled = true;
      try {
        const r = await api("/api/plugins/reload", {
          method: "POST",
          body: JSON.stringify({ plugin_id: el.dataset.reload }),
        });
        toast(r.ok ? "已重载" : r.error || "重载失败");
      } catch (e) {
        toast("重载失败：" + e.message);
      } finally {
        el.disabled = false;
      }
    })
  );

  $$("#plugins-list [data-advanced]").forEach((el) =>
    el.addEventListener("click", () => switchTab(el.dataset.advanced))
  );

  $$("#plugins-list [data-uninstall]").forEach((el) =>
    el.addEventListener("click", () => openUninstallModal(el.dataset.uninstall))
  );

  $$("#plugins-list [data-disable-other]").forEach((el) =>
    el.addEventListener("click", async () => {
      const other = el.dataset.disableOther;
      if (!(await modalConfirm({ title: "禁用插件", message: `禁用 ${other} 以消除功能重叠？`, okText: "确认禁用" }))) return;
      try {
        const r = await api("/api/plugins/toggle", {
          method: "POST",
          body: JSON.stringify({ plugin_id: other, enabled: false }),
        });
        toast(r.ok ? `已禁用 ${other}` : r.error || "操作失败");
      } catch (e) {
        toast("操作失败：" + e.message);
      } finally {
        loadPlugins();
      }
    })
  );
}

/* ---- 插件设置弹窗 ---- */
function pluginFieldHtml(key, spec, value) {
  const type = spec.type || (typeof value === "boolean" ? "bool" : Array.isArray(value) ? "list" : typeof value === "number" ? "int" : "string");
  const label = spec.description || key;
  const hint = spec.hint ? `<div class="field-hint">${esc(spec.hint)}</div>` : "";
  const dv = value !== undefined ? value : spec.default;

  if (type === "bool") {
    return `<div class="plugin-field bool"><label><input type="checkbox" data-key="${esc(key)}" ${dv ? "checked" : ""} /> ${esc(label)}</label>${hint}</div>`;
  }
  if (type === "int" || type === "float") {
    if (spec.slider) {
      const min = spec.slider.min ?? 0;
      const max = spec.slider.max ?? 100;
      const step = spec.slider.step ?? 1;
      return `<div class="plugin-field">
        <label>${esc(label)} <b data-out="${esc(key)}">${dv}</b></label>
        <div class="range-row"><input type="range" data-key="${esc(key)}" data-type="number" min="${min}" max="${max}" step="${step}" value="${dv}" /></div>
        ${hint}</div>`;
    }
    return `<div class="plugin-field"><label>${esc(label)}</label><input type="number" data-key="${esc(key)}" data-type="number" step="any" value="${dv}" />${hint}</div>`;
  }
  if (type === "list") {
    return `<div class="plugin-field"><label>${esc(label)}</label><input type="text" data-key="${esc(key)}" data-type="list" value="${esc((dv || []).join(", "))}" placeholder="逗号分隔" />${hint}</div>`;
  }
  if (type === "text") {
    return `<div class="plugin-field"><label>${esc(label)}</label><textarea data-key="${esc(key)}" data-type="text">${esc(dv || "")}</textarea>${hint}</div>`;
  }
  if (type === "object" || type === "dict") {
    return `<div class="plugin-field"><label>${esc(label)}</label><textarea data-key="${esc(key)}" data-type="json">${esc(JSON.stringify(dv ?? {}, null, 2))}</textarea>${hint}</div>`;
  }
  return `<div class="plugin-field"><label>${esc(label)}</label><input type="text" data-key="${esc(key)}" data-type="string" value="${esc(dv ?? "")}" />${hint}</div>`;
}

async function openPluginSettings(name) {
  try {
    const d = await api("/api/plugins/config?plugin_id=" + encodeURIComponent(name));
    const meta = (d.metadata && d.metadata[name] && d.metadata[name].items) || {};
    const cfg = d.config || {};
    const keys = Array.from(new Set([...Object.keys(meta), ...Object.keys(cfg)]));
    const html = keys.map((k) => pluginFieldHtml(k, meta[k] || {}, cfg[k])).join("") || `<div class="hint">这个插件没有可调参数</div>`;
    $("#plugin-modal-title").textContent = `${name} · 设置`;
    $("#plugin-modal-body").innerHTML = html;
    const own = pluginCache.find((p) => p.name === name) || {};
    const related = (own.related || []).map((r) => r.plugin);
    $("#plugin-modal-hint").textContent =
      "保存后写入 AstrBot 配置并自动重载插件" +
      (related.length ? ` · 同类方案（未安装）：${related.join("、")}` : "");

    $$("#plugin-modal-body input[type=range]").forEach((el) =>
      el.addEventListener("input", () => {
        const out = $(`#plugin-modal-body [data-out="${el.dataset.key}"]`);
        if (out) out.textContent = el.value;
      })
    );

    pluginConfigState = { pluginId: name };
    $("#plugin-modal").classList.remove("hidden");
  } catch (e) {
    toast("读取配置失败：" + e.message);
  }
}

function collectPluginForm() {
  const out = {};
  $$("#plugin-modal-body [data-key]").forEach((el) => {
    const key = el.dataset.key;
    const t = el.dataset.type;
    if (el.type === "checkbox") out[key] = el.checked;
    else if (t === "number") out[key] = Number(el.value);
    else if (t === "list") out[key] = el.value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean);
    else if (t === "json") {
      try {
        out[key] = JSON.parse(el.value);
      } catch (e) {
        out[key] = el.value;
      }
    } else out[key] = el.value;
  });
  return out;
}

function closePluginModal() {
  $("#plugin-modal").classList.add("hidden");
  pluginConfigState = null;
}

$("#plugin-modal-close").addEventListener("click", closePluginModal);
$("#plugin-modal-cancel").addEventListener("click", closePluginModal);
$("#plugin-modal").addEventListener("click", (e) => {
  if (e.target.id === "plugin-modal") closePluginModal();
});
$("#plugin-modal-save").addEventListener("click", async () => {
  if (!pluginConfigState) return;
  const btn = $("#plugin-modal-save");
  btn.disabled = true;
  try {
    const r = await api("/api/plugins/config/save", {
      method: "POST",
      body: JSON.stringify({ plugin_id: pluginConfigState.pluginId, config: collectPluginForm() }),
    });
    toast(r.ok ? `已保存并重载${r.reloaded === false ? "（重载失败，请手动重载）" : ""}` : r.error || "保存失败");
    if (r.ok) closePluginModal();
  } catch (e) {
    toast("保存失败：" + e.message);
  } finally {
    btn.disabled = false;
  }
});
$("#btn-refresh-plugins").addEventListener("click", loadPlugins);


/* ---------------- 插件卸载 ---------------- */
let uninstallTarget = null;

function closeUninstallModal() {
  $("#uninstall-modal").classList.add("hidden");
  uninstallTarget = null;
}

function openUninstallModal(name) {
  uninstallTarget = name;
  $("#uninstall-name").textContent = name;
  $("#uninstall-config").checked = false;
  $("#uninstall-data").checked = false;
  $("#uninstall-hint").textContent = "";
  $("#uninstall-modal").classList.remove("hidden");
}

$("#uninstall-close").addEventListener("click", closeUninstallModal);
$("#uninstall-cancel").addEventListener("click", closeUninstallModal);
$("#uninstall-modal").addEventListener("click", (e) => {
  if (e.target.id === "uninstall-modal") closeUninstallModal();
});
$("#uninstall-confirm").addEventListener("click", async () => {
  if (!uninstallTarget) return;
  const name = uninstallTarget;
  const btn = $("#uninstall-confirm");
  btn.disabled = true;
  $("#uninstall-hint").textContent = "卸载中…";
  try {
    const r = await api("/api/plugins/uninstall", {
      method: "POST",
      body: JSON.stringify({
        plugin_id: name,
        delete_config: $("#uninstall-config").checked,
        delete_data: $("#uninstall-data").checked,
      }),
    });
    if (!r.ok) {
      $("#uninstall-hint").textContent = r.error || "卸载失败";
      toast(r.error || "卸载失败");
      return;
    }
    toast(`已卸载 ${name}`);
    closeUninstallModal();
    loadPlugins();
  } catch (e) {
    $("#uninstall-hint").textContent = e.message;
    toast("卸载失败：" + e.message);
  } finally {
    btn.disabled = false;
  }
});


/* ---------------- 响应策略 ---------------- */
let policyData = null;
let policyCandidates = { groups: [], people: [], private_ids: [] };

async function loadPolicy() {
  try {
    policyData = await api("/api/policy");
    try {
      policyCandidates = await api("/api/policy/candidates");
    } catch (e) {
      policyCandidates = policyCandidates || { groups: [], people: [], private_ids: [] };
    }
    renderPolicy();
    if (window.__policyPick) {
      const kind = window.__policyPick;
      window.__policyPick = "";
      openPicker(kind);
    }
  } catch (e) {
    toast("读取响应策略失败：" + e.message);
  }
}

function policyLevelOptions(current) {
  const levels = (policyData && policyData.levels) || [];
  return levels
    .map(
      (l) =>
        `<option value="${l.level}" ${Number(current) === l.level ? "selected" : ""}>${esc(l.name)} · ${esc(
          l.desc.split("。")[0]
        )}</option>`
    )
    .join("");
}

function renderPolicy() {
  if (!policyData) return;
  const p = policyData.policy;
  $("#policy-whitelist").checked = !!p.whitelist_enabled;

  $("#policy-groups").innerHTML =
    (policyData.groups || [])
      .map((g) => {
        const label = g.name ? `${esc(g.name)} <small>${esc(g.id)}</small>` : esc(g.id);
        return `<span class="chip">${label}<span class="chip-del" data-del-group="${esc(g.id)}">×</span></span>`;
      })
      .join("") || `<span class="hint">（还没有白名单群）</span>`;

  const peopleNames = {};
  (policyCandidates.people || []).forEach((x) => (peopleNames[String(x.id)] = x.name));
  (policyCandidates.private_ids || []).forEach((x) => (peopleNames[String(x.id)] = peopleNames[String(x.id)] || x.name));
  $("#policy-privates").innerHTML =
    (p.allowed_private_users || [])
      .map((uid) => {
        const name = peopleNames[String(uid)];
        const label = name ? `${esc(name)} <small>${esc(uid)}</small>` : esc(uid);
        return `<span class="chip">${label}<span class="chip-del" data-del-private="${esc(uid)}">×</span></span>`;
      })
      .join("") || `<span class="hint">（还没有白名单私聊）</span>`;

  $("#policy-ranges").innerHTML =
    (p.peak_ranges || [])
      .map((r) => `<span class="chip">${esc(r)}<span class="chip-del" data-del-range="${esc(r)}">×</span></span>`)
      .join("") || `<span class="hint">（没有高峰时段，全部按低谷处理）</span>`;

  $("#policy-weekday-only").checked = p.peak_weekdays_only !== false;
  $("#policy-peak-level").innerHTML = policyLevelOptions(p.peak_level);
  $("#policy-offpeak-level").innerHTML = policyLevelOptions(p.offpeak_level);
  $("#policy-fixed-level").innerHTML = policyLevelOptions(p.fixed_level ?? 3);
  const pvEnabled = p.peak_valley_enabled !== false;
  $("#policy-pv-enabled").checked = pvEnabled;
  togglePolicyPv(pvEnabled);

  const st = policyData.status || {};
  const inPeak = st.in_peak;
  $("#policy-status").textContent = pvEnabled
    ? `现在 ${st.now || ""} · ${inPeak ? "高峰时段" : "低谷时段"} → ${st.level || "-"} 级`
    : `峰谷时段分级响应已关闭 · 固定 ${st.level || "-"} 级`;

  $("#policy-levels").innerHTML = (policyData.levels || [])
    .map(
      (l) => `<div class="policy-level-row">
        <div class="policy-level-name">${esc(l.name)}</div>
        <div class="policy-level-desc">${esc(l.desc)}${Number(st.level) === l.level ? ' <span class="plugin-badge ok">当前</span>' : ""}</div>
      </div>`
    )
    .join("");

  $$("#policy-groups [data-del-group]").forEach((el) =>
    el.addEventListener("click", () => {
      p.allowed_groups = (p.allowed_groups || []).filter((x) => String(x) !== el.dataset.delGroup);
      policyData.groups = (policyData.groups || []).filter((g) => String(g.id) !== el.dataset.delGroup);
      renderPolicy();
    })
  );
  $$("#policy-privates [data-del-private]").forEach((el) =>
    el.addEventListener("click", () => {
      p.allowed_private_users = (p.allowed_private_users || []).filter((x) => String(x) !== el.dataset.delPrivate);
      renderPolicy();
    })
  );
  $$("#policy-ranges [data-del-range]").forEach((el) =>
    el.addEventListener("click", () => {
      p.peak_ranges = (p.peak_ranges || []).filter((x) => String(x) !== el.dataset.delRange);
      renderPolicy();
    })
  );
}

function addPolicyIds(target, raw, isGroup) {
  const ids = String(raw || "")
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter((x) => /^\d{5,20}$/.test(x));
  if (!ids.length) {
    toast("请输入 5-20 位数字");
    return;
  }
  const list = (policyData.policy[target] || []).map(String);
  let added = 0;
  for (const id of ids) {
    if (!list.includes(id)) {
      list.push(id);
      added++;
    }
    if (isGroup && !(policyData.groups || []).some((g) => String(g.id) === id)) {
      policyData.groups = policyData.groups || [];
      policyData.groups.push({ id, name: "" });
    }
  }
  policyData.policy[target] = list;
  if (added) toast(`已添加 ${added} 个`);
  renderPolicy();
}

$("#policy-add-group").addEventListener("click", () => {
  addPolicyIds("allowed_groups", $("#policy-group-input").value, true);
  $("#policy-group-input").value = "";
});

$("#policy-add-private").addEventListener("click", () => {
  addPolicyIds("allowed_private_users", $("#policy-private-input").value, false);
  $("#policy-private-input").value = "";
});

$("#policy-add-range").addEventListener("click", () => {
  const start = $("#policy-range-start").value.trim();
  const end = $("#policy-range-end").value.trim();
  const re = /^([01]?\d|2[0-4]):([0-5]\d)$/;
  if (!re.test(start) || !re.test(end)) {
    toast("时间格式应为 HH:MM，例如 08:30 / 24:00");
    return;
  }
  const text = `${start.padStart(5, "0")}-${end.padStart(5, "0")}`;
  policyData.policy.peak_ranges = policyData.policy.peak_ranges || [];
  if (!policyData.policy.peak_ranges.includes(text)) policyData.policy.peak_ranges.push(text);
  $("#policy-range-start").value = "";
  $("#policy-range-end").value = "";
  renderPolicy();
});

function togglePolicyPv(enabled) {
  const peak = document.getElementById("policy-peak-field");
  const off = document.getElementById("policy-offpeak-field");
  const fixed = document.getElementById("policy-fixed-field");
  const hint = document.getElementById("policy-pv-hint");
  if (peak) peak.style.display = enabled ? "" : "none";
  if (off) off.style.display = enabled ? "" : "none";
  if (fixed) fixed.style.display = enabled ? "none" : "";
  if (hint) hint.style.display = enabled ? "none" : "";
}

$("#policy-pv-enabled").addEventListener("change", (e) => togglePolicyPv(e.target.checked));

$("#policy-save").addEventListener("click", async () => {
  if (!policyData) return;
  const p = policyData.policy;
  const payload = {
    whitelist_enabled: $("#policy-whitelist").checked,
    allowed_groups: (p.allowed_groups || []).map(String),
    allowed_private_users: (p.allowed_private_users || []).map(String),
    peak_ranges: p.peak_ranges || [],
    peak_weekdays_only: $("#policy-weekday-only").checked,
    peak_level: Number($("#policy-peak-level").value),
    offpeak_level: Number($("#policy-offpeak-level").value),
    peak_valley_enabled: $("#policy-pv-enabled").checked,
    fixed_level: Number($("#policy-fixed-level").value),
  };
  const btn = $("#policy-save");
  btn.disabled = true;
  try {
    const r = await api("/api/policy/save", { method: "POST", body: JSON.stringify(payload) });
    toast(r.ok ? "策略已保存，下条消息生效" : r.error || "保存失败");
    $("#policy-save-hint").textContent = "已保存 · " + new Date().toLocaleTimeString();
    await loadPolicy();
  } catch (e) {
    toast("保存失败：" + e.message);
  } finally {
    btn.disabled = false;
  }
});


/* ---------------- 界面自动刷新（控制台更新后不用手动重开） ---------------- */
let __buildStamp = null;

async function checkBuild() {
  try {
    const r = await api("/api/version");
    if (!__buildStamp) {
      __buildStamp = r.build;
      return;
    }
    if (r.build === __buildStamp) return;
    if (document.querySelector(".modal-mask:not(.hidden)")) return;
    const ae = document.activeElement;
    if (ae && (ae.tagName === "TEXTAREA" || (ae.tagName === "INPUT" && ae.type !== "checkbox"))) {
      toast("控制台已更新，离开输入框后自动刷新");
      return;
    }
    __buildStamp = r.build;
    toast("控制台已更新，正在刷新…");
    setTimeout(() => location.reload(), 600);
  } catch (e) {
    /* 后端重启中，忽略 */
  }
}

$("#btn-reload-ui").addEventListener("click", () => location.reload());
setTimeout(checkBuild, 1500);
setInterval(() => {
  if (document.visibilityState === "visible") checkBuild();
}, 15000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") checkBuild();
});
window.addEventListener("focus", checkBuild);


/* ---------------- 白名单选择器 ---------------- */
let pickerKind = "group";
let pickerMode = "whitelist";

function closePicker() {
  $("#picker-modal").classList.add("hidden");
}

function renderPickerList(keyword) {
  const kw = String(keyword || "").trim().toLowerCase();
  let items;
  if (pickerKind === "group") {
    items = (policyCandidates.groups || []).map((g) => ({ id: g.id, name: g.name }));
  } else {
    const merged = new Map();
    (policyCandidates.people || []).forEach((p) => merged.set(String(p.id), p.name));
    (policyCandidates.private_ids || []).forEach((p) => merged.set(String(p.id), merged.get(String(p.id)) || p.name || ""));
    items = Array.from(merged.entries()).map(([id, name]) => ({ id, name }));
  }
  const selected =
    pickerMode === "target"
      ? (behaviorCfg && behaviorCfg.proactive_targets ? behaviorCfg.proactive_targets : []).map((t) => String(t).split(":")[1])
      : pickerKind === "group"
      ? (policyData.policy.allowed_groups || []).map(String)
      : (policyData.policy.allowed_private_users || []).map(String);
  const filtered = items
    .filter((x) => !kw || String(x.name).toLowerCase().includes(kw) || String(x.id).includes(kw))
    .sort((a, b) => String(a.name).localeCompare(String(b.name), "zh"));
  $("#picker-list").innerHTML = filtered.length
    ? filtered
        .map(
          (x) => `<div class="picker-item" data-pick-id="${esc(x.id)}">
            <span>${esc(x.name) || "（未记录昵称）"}${selected.includes(String(x.id)) ? ' <span class="plugin-badge ok">已选</span>' : ""}</span>
            <span class="pid">${esc(x.id)}</span>
          </div>`
        )
        .join("")
    : `<div class="picker-empty">没有可选项（机器人还没在这个群/和这个人聊过，可以手动输入号码）</div>`;
  $$("#picker-list [data-pick-id]").forEach((el) =>
    el.addEventListener("click", () => {
      const id = el.dataset.pickId;
      if (pickerMode === "target") {
        const target = `${pickerKind === "group" ? "group" : "private"}:${id}`;
        const list = (behaviorCfg.proactive_targets || []).map(String);
        if (!list.includes(target)) list.push(target);
        behaviorCfg.proactive_targets = list;
        closePicker();
        markBehaviorDirty(true);
        renderBehaviorPage();
        toast("已加入主动聊天对象，记得保存");
        return;
      }
      if (pickerKind === "group") {
        const list = (policyData.policy.allowed_groups || []).map(String);
        if (!list.includes(id)) list.push(id);
        policyData.policy.allowed_groups = list;
        const cand = (policyCandidates.groups || []).find((g) => String(g.id) === id);
        policyData.groups = policyData.groups || [];
        if (!policyData.groups.some((g) => String(g.id) === id)) {
          policyData.groups.push({ id, name: (cand && cand.name) || "" });
        }
      } else {
        const list = (policyData.policy.allowed_private_users || []).map(String);
        if (!list.includes(id)) list.push(id);
        policyData.policy.allowed_private_users = list;
      }
      closePicker();
      renderPolicy();
      toast("已加入白名单，记得点保存");
    })
  );
}

function openTargetPicker(kind) {
  openPicker(kind, "target");
}

function openPicker(kind, mode = "whitelist") {
  pickerKind = kind;
  pickerMode = mode;
  $("#picker-title").textContent = kind === "group" ? "选择 QQ 群聊" : "选择 QQ 好友";
  const src = policyCandidates.source === "qq" ? "" : "（QQ 未连接，当前为日志记录，登录后显示真实列表）";
  $("#picker-search").placeholder = "搜索名字或号码… " + src;
  $("#picker-search").value = "";
  renderPickerList("");
  $("#picker-modal").classList.remove("hidden");
}

$("#policy-pick-group").addEventListener("click", () => openPicker("group"));
$("#policy-pick-private").addEventListener("click", () => openPicker("private"));
$("#picker-close").addEventListener("click", closePicker);
$("#picker-modal").addEventListener("click", (e) => {
  if (e.target.id === "picker-modal") closePicker();
});
$("#picker-search").addEventListener("input", (e) => renderPickerList(e.target.value));


/* ---------------- 运行状态 ---------------- */
function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return "—";
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h} 小时 ${mm} 分` : `${h} 小时`;
}

function fmtAgo(ts) {
  if (!ts) return "暂无消息";
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return "刚刚";
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function renderRuntime(rt, life = {}) {
  const box = $("#runtime-info");
  if (!box) return;
  const policy = (rt && rt.policy) || {};
  const levelText = policy.whitelist ? "白名单开启" : "白名单关闭";
  const pvEnabled = policy.peak_valley_enabled !== false;
  const phase = pvEnabled ? (policy.in_peak ? "高峰" : "低谷") : "固定";
  const sleep = (rt && rt.memory_sleep) || {};
  let sleepText = "尚未整理";
  if (sleep.last_ts) {
    sleepText = `${fmtDuration((sleep.hours_ago || 0) * 3600)}前（${fmtTs(sleep.last_ts)}）`;
  }
  setHtml(box, `
    <div class="k">在线时长</div><div class="v">${fmtDuration(rt && rt.uptime_sec)}</div>
    <div class="k">最后活跃</div><div class="v">${fmtAgo(rt && rt.last_active_ts)}</div>
    <div class="k">响应策略</div><div class="v">${levelText} · ${phase} L${policy.level != null ? policy.level : "—"}</div>
    <div class="k">上次记忆整理</div><div class="v ${sleep.overdue ? "warn" : ""}">${sleepText}${sleep.overdue ? " · ⚠️ 超过 48 小时" : ""}</div>
    <div class="k">今日生活</div><div class="v">${life.activity ? esc(life.activity) + (life.next ? ` <span class="hint">→ ${esc(life.next)}</span>` : "") : "生成中…"}</div>`);
  const banner = $("#mem-sleep-banner");
  if (banner) banner.classList.toggle("hidden", !sleep.overdue);
}


/* ---------------- 批量 AI 打标 ---------------- */
let batchTagTimer = null;

function renderBatchTagStatus(st) {
  const el = $("#batch-tag-status");
  if (!el) return;
  if (!st || !st.total) {
    el.textContent = "";
    return;
  }
  if (st.running) {
    el.textContent = `打标中 ${st.done}/${st.total}（成功 ${st.ok}，失败 ${st.fail}）`;
  } else {
    el.textContent = `已完成：成功 ${st.ok}，失败 ${st.fail}`;
  }
}

async function pollBatchTag() {
  try {
    const st = await api("/api/stickers/auto-tag-batch/status");
    renderBatchTagStatus(st);
    if (st.running) {
      clearTimeout(batchTagTimer);
      batchTagTimer = setTimeout(pollBatchTag, 2000);
    } else {
      loadStickers();
    }
  } catch (e) {
    clearTimeout(batchTagTimer);
  }
}

$("#btn-batch-tag").addEventListener("click", async () => {
  if (!(await modalConfirm({ title: "批量 AI 打标", message: "给所有描述还不是中文的表情批量 AI 打标？\n会消耗 token，可中途关闭页面，不影响后台运行。", okText: "开始打标", danger: false }))) return;
  try {
    const r = await api("/api/stickers/auto-tag-batch/start", { method: "POST", body: JSON.stringify({}) });
    toast(r.ok ? `已开始，共 ${r.total} 张` : r.error || "启动失败");
    if (r.ok) pollBatchTag();
  } catch (e) {
    toast("启动失败：" + e.message);
  }
});
pollBatchTag();


/* ---------------- 模型管理 ---------------- */
async function loadModels() {
  const box = $("#model-list");
  if (!box) return;
  try {
    const d = await api("/api/models");
    const providers = d.providers || [];
    box.innerHTML = providers.length
      ? providers
          .map(
            (p) => `<div class="conv-item">
              <div class="conv-main">
                <div class="conv-name">${esc(p.id)}${p.current ? ' <span class="plugin-badge ok">当前</span>' : ""}</div>
                <div class="conv-sub">${esc(p.model)}${p.version ? " · " + esc(p.version) : ""} · ${esc(p.api_base)} · ${esc(p.key_masked)}</div>
              </div>
              <button class="btn small danger" data-model-del="${esc(p.id)}" ${p.current ? "disabled title=\"正在使用\"" : ""}>删除</button>
            </div>`
          )
          .join("")
      : `<p class="hint">还没有配置模型</p>`;
    $$("#model-list [data-model-del]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.modelDel;
        if (!(await modalConfirm({ title: "删除模型", message: `删除模型 ${pid}？\n会从配置里移除，然后重启 AstrBot。`, okText: "确认删除" }))) return;
        btn.disabled = true;
        const r = await api("/api/models/delete", {
          method: "POST",
          body: JSON.stringify({ provider_id: pid }),
        });
        toast(r.ok ? "已删除，正在重启 AstrBot…" : r.error || "删除失败", 4000);
        if (r.ok) setTimeout(() => loadModels(), 12000);
        else btn.disabled = false;
      })
    );
    $("#model-select").innerHTML = providers
      .map((p) => `<option value="${esc(p.id)}" ${p.current ? "selected" : ""}>${esc(p.id)} · ${esc(p.model)}</option>`)
      .join("");
  } catch (e) {
    toast("读取模型失败：" + e.message);
  }
}

$("#btn-switch-model").addEventListener("click", async () => {
  const pid = $("#model-select").value;
  if (!pid) return;
  if (!(await modalConfirm({ title: "切换模型", message: `切换到模型 ${pid} 并重启 AstrBot？`, okText: "确认切换" }))) return;
  const r = await api("/api/models/switch", { method: "POST", body: JSON.stringify({ provider_id: pid }) });
  toast(r.ok ? "已切换，正在重启 AstrBot…" : r.error || "切换失败", 4000);
  setTimeout(() => refreshStatus(), 8000);
});

$("#btn-add-model").addEventListener("click", async () => {
  const payload = {
    id: $("#new-model-id").value.trim(),
    model: $("#new-model-name").value.trim(),
    api_base: $("#new-model-base").value.trim(),
    api_key: $("#new-model-key").value.trim(),
  };
  if (!payload.id || !payload.model || !payload.api_base) {
    toast("ID / 模型名 / API Base 要填");
    return;
  }
  const r = await api("/api/models/add", { method: "POST", body: JSON.stringify(payload) });
  toast(r.ok ? "已添加，正在重启 AstrBot…" : r.error || "添加失败", 4000);
  if (r.ok) {
    $("#new-model-id").value = "";
    $("#new-model-name").value = "";
    $("#new-model-base").value = "";
    $("#new-model-key").value = "";
    setTimeout(() => refreshStatus(), 8000);
  }
});


/* ---------------- 聊天记忆 ---------------- */
const convState = { conversations: [], current: null, history: [], removed: new Set() };

function parseHistory(raw) {
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw);
    } catch (e) {
      return [];
    }
  }
  return [];
}

function contentText(content) {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (!part) return "";
        if (typeof part === "string") return part;
        if (part.type === "text") return part.text || "";
        if (part.type === "image") return "[图片]";
        if (part.type === "record" || part.type === "voice") return "[语音]";
        return "";
      })
      .join("")
      .replace(/<system_reminder>[\s\S]*?<\/system_reminder>/g, "")
      .replace(/【可用表情包】[\s\S]*$/g, "")
      .trim();
  }
  return String(content);
}

function fmtTs(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function loadChatMemory() {
  try {
    const r = await api("/api/memory/chat", { method: "POST", body: "{}" });
    convState.conversations = r.conversations || [];
    renderConvList();
  } catch (e) {
    $("#conv-list").innerHTML = `<p class="hint">读取失败：${esc(e.message)}</p>`;
  }
  try {
    const e = await api("/api/memory/extra");
    const items = Object.entries(e.proactive || {});
    $("#proactive-history").innerHTML = items.length
      ? items
          .map(
            ([target, count]) =>
              `<div class="k">${esc(target)}</div><div class="v">${count} 条 <button class="btn small" data-clear-proactive="${esc(target)}">清空</button></div>`
          )
          .join("")
      : `<div class="k">暂无</div><div class="v">还没有主动聊天历史</div>
         <div class="k">群友记忆</div><div class="v">${e.member_groups} 个群 / ${e.member_count} 位成员</div>`;
    $$("#proactive-history [data-clear-proactive]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const target = btn.dataset.clearProactive;
        if (!(await modalConfirm({ title: "清空主动聊天历史", message: `清空 ${target} 的主动聊天历史？`, okText: "确认清空" }))) return;
        await api("/api/memory/proactive/clear", { method: "POST", body: JSON.stringify({ target }) });
        toast("已清空");
        loadChatMemory();
      })
    );
  } catch (e) {
    $("#proactive-history").innerHTML = `<p class="hint">读取失败：${esc(e.message)}</p>`;
  }
}

function renderConvList() {
  const box = $("#conv-list");
  if (!convState.conversations.length) {
    box.innerHTML = `<p class="hint">暂无会话记忆（还没人跟机器人聊过）</p>`;
    return;
  }
  box.innerHTML = convState.conversations
    .map((conv, idx) => {
      const name = conv.umo_info?.display_name || conv.umo_info?.auto_name || conv.user_id || "未知会话";
      const cid = conv.cid || "";
      return `<div class="conv-item">
        <div class="conv-main">
          <div class="conv-name">${esc(name)}</div>
          <div class="conv-sub">${esc(conv.user_id || "")} · 会话 ${esc(cid.slice(0, 8))}</div>
        </div>
        <div class="conv-meta">${conv.token_usage || 0} tokens<br/>${fmtTs(conv.updated_at)}</div>
        <button class="btn small" data-conv-view="${idx}">查看</button>
      </div>`;
    })
    .join("");
  $$("#conv-list [data-conv-view]").forEach((btn) =>
    btn.addEventListener("click", () => openConv(Number(btn.dataset.convView)))
  );
}

async function openConv(idx) {
  const conv = convState.conversations[idx];
  if (!conv) return;
  convState.current = conv;
  convState.removed = new Set();
  const r = await api("/api/memory/chat/detail", {
    method: "POST",
    body: JSON.stringify({ user_id: conv.user_id, cid: conv.cid }),
  });
  if (!r.ok) {
    toast(r.error || "读取失败");
    return;
  }
  convState.history = parseHistory(r.history);
  const name = conv.umo_info?.display_name || conv.umo_info?.auto_name || conv.user_id;
  $("#conv-title").textContent = `会话记忆 · ${name}`;
  $("#conv-meta").textContent = `${conv.user_id} · ${convState.history.length} 条消息 · ${fmtTs(conv.updated_at)}`;
  renderConvMessages();
  $("#conv-modal").classList.remove("hidden");
}

function renderConvMessages() {
  const box = $("#conv-messages");
  if (!convState.history.length) {
    box.innerHTML = `<p class="hint">这个会话是空的</p>`;
    return;
  }
  box.innerHTML = convState.history
    .map((msg, idx) => {
      const role = msg.role === "assistant" ? "机器人" : msg.role === "user" ? "对方" : msg.role || "?";
      const text = contentText(msg.content) || "[非文本内容]";
      const removed = convState.removed.has(idx) ? " removed" : "";
      return `<div class="conv-msg ${msg.role}${removed}" data-idx="${idx}">
        <span class="role">${esc(role)}</span>
        <div class="body">${esc(text.slice(0, 600))}${text.length > 600 ? "…" : ""}</div>
        <button class="del" data-del-msg="${idx}">${convState.removed.has(idx) ? "恢复" : "删除"}</button>
      </div>`;
    })
    .join("");
  $$("#conv-messages [data-del-msg]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const i = Number(btn.dataset.delMsg);
      if (convState.removed.has(i)) convState.removed.delete(i);
      else convState.removed.add(i);
      renderConvMessages();
    })
  );
}

$("#btn-refresh-chatmem").addEventListener("click", loadChatMemory);
$("#btn-goto-members").addEventListener("click", () => switchTab("memory"));
$("#conv-close").addEventListener("click", () => $("#conv-modal").classList.add("hidden"));
$("#conv-modal").addEventListener("click", (e) => {
  if (e.target.id === "conv-modal") $("#conv-modal").classList.add("hidden");
});

$("#btn-conv-save").addEventListener("click", async () => {
  const conv = convState.current;
  if (!conv) return;
  const kept = convState.history.filter((_, i) => !convState.removed.has(i));
  const r = await api("/api/memory/chat/save", {
    method: "POST",
    body: JSON.stringify({ user_id: conv.user_id, cid: conv.cid, history: kept }),
  });
  toast(r.ok ? `已保存，剩 ${kept.length} 条` : r.error || "保存失败");
  if (r.ok) {
    $("#conv-modal").classList.add("hidden");
    loadChatMemory();
  }
});

$("#btn-conv-clear").addEventListener("click", async () => {
  const conv = convState.current;
  if (!conv) return;
  if (!(await modalConfirm({ title: "清空会话", message: "清空这个会话的所有消息？\n会保留会话本身。", okText: "确认清空" }))) return;
  const r = await api("/api/memory/chat/save", {
    method: "POST",
    body: JSON.stringify({ user_id: conv.user_id, cid: conv.cid, history: [] }),
  });
  toast(r.ok ? "已清空" : r.error || "清空失败");
  if (r.ok) {
    $("#conv-modal").classList.add("hidden");
    loadChatMemory();
  }
});

$("#btn-conv-delete").addEventListener("click", async () => {
  const conv = convState.current;
  if (!conv) return;
  if (!(await modalConfirm({ title: "删除会话", message: "删除整个会话？\n下次聊天会开新会话。", okText: "确认删除" }))) return;
  const r = await api("/api/memory/chat/delete", {
    method: "POST",
    body: JSON.stringify({ user_id: conv.user_id, cid: conv.cid }),
  });
  toast(r.ok ? "已删除" : r.error || "删除失败");
  if (r.ok) {
    $("#conv-modal").classList.add("hidden");
    loadChatMemory();
  }
});

$("#btn-clear-proactive-all").addEventListener("click", async () => {
  if (!(await modalConfirm({ title: "清空主动聊天历史", message: "清空所有对象的主动聊天历史？", okText: "确认清空" }))) return;
  await api("/api/memory/proactive/clear", { method: "POST", body: JSON.stringify({}) });
  toast("已清空");
  loadChatMemory();
});


/* ---------------- 纪念日编辑器 ---------------- */
function annivLines(val) {
  return String(val || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function annivParts(line) {
  const i = line.indexOf(":");
  if (i < 0) return { date: "", desc: line };
  return { date: line.slice(0, i).trim(), desc: line.slice(i + 1).trim() };
}

function annivListHtml(lines) {
  if (!lines.length) return `<div class="hint" style="padding:6px 0">还没有纪念日</div>`;
  return lines
    .map((line, i) => {
      const { date, desc } = annivParts(line);
      return `<div class="anniv-item">
        <span class="anniv-date-label">${esc(date)}</span>
        <span class="anniv-desc-label">${esc(desc)}</span>
        <button class="btn tiny" data-anniv-del="${i}">删除</button>
      </div>`;
    })
    .join("");
}

function annivApply(wrap, lines) {
  const hidden = wrap.querySelector('input[data-bkey="anniversaries"]');
  if (hidden) hidden.value = lines.join("\n");
  const list = wrap.querySelector(".anniv-list");
  if (list) list.innerHTML = annivListHtml(lines);
}

document.addEventListener("click", (e) => {
  const add = e.target.closest("[data-anniv-add]");
  if (add) {
    const wrap = add.closest(".anniv-editor");
    const descEl = wrap.querySelector(".anniv-desc");
    const desc = (descEl.value || "").trim();
    const date = wrap.dataset.annivDate || "";
    if (!desc || !date) {
      toast("先写是什么日子，再选日期");
      return;
    }
    const hidden = wrap.querySelector('input[data-bkey="anniversaries"]');
    const lines = annivLines(hidden.value);
    lines.push(`${date}:${desc}`);
    hidden.value = lines.join("\n");
    annivApply(wrap, lines);
    descEl.value = "";
    return;
  }
  const del = e.target.closest("[data-anniv-del]");
  if (del) {
    const wrap = del.closest(".anniv-editor");
    const hidden = wrap.querySelector('input[data-bkey="anniversaries"]');
    const lines = annivLines(hidden.value);
    lines.splice(Number(del.dataset.annivDel), 1);
    annivApply(wrap, lines);
  }
});

/* 默认日期为今天 */
document.addEventListener("DOMContentLoaded", () => {
  const d = new Date();
  const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  document.querySelectorAll(".anniv-date").forEach((el) => {
    if (!el.value) el.value = iso;
  });
});


/* ---------------- 二维码刷新 ---------------- */
async function refreshQr(btn) {
  const status = $("#qr-refresh-status");
  const oldText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "刷新中…";
  }
  if (status) status.textContent = "正在重启 NapCat 生成新二维码，约 15–30 秒…";
  try {
    const r = await api("/api/qr/refresh", { method: "POST", body: "{}" });
    if (r.ok) {
      toast(r.note || "二维码已刷新");
      $("#qr-image").src = `/api/qr?t=${Date.now()}`;
      $("#qr-image").style.display = "block";
      if (status) status.textContent = "已刷新，请用手机 QQ 扫码";
    } else {
      toast(r.error || "刷新失败", 5000);
      if (status) status.textContent = r.error || "刷新失败";
    }
  } catch (e) {
    toast("刷新失败：" + e.message, 5000);
    if (status) status.textContent = "刷新失败：" + e.message;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText || "刷新二维码";
    }
  }
}

const qrBtn = $("#btn-refresh-qr");
if (qrBtn) qrBtn.addEventListener("click", () => refreshQr(qrBtn));
const qrBtn2 = $("#btn-refresh-qr2");
if (qrBtn2) qrBtn2.addEventListener("click", () => refreshQr(qrBtn2));


/* ---------------- QQ空间 ---------------- */
function fmtFeedTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function loadQzone() {
  try {
    const s = await api("/api/qzone/status");
    const st = s.status || {};
    if (!s.ok) {
      $("#qzone-status").innerHTML = `<div class="k">状态</div><div class="v warn">${esc(s.error || "未连接")}</div>`;
    } else {
      $("#qzone-status").innerHTML = `
        <div class="k">登录 QQ</div><div class="v">${st.login_uin || "—"}</div>
        <div class="k">daemon</div><div class="v">${st.daemon_state || "—"} · 端口 ${st.daemon_port || "—"}</div>
        <div class="k">Cookie</div><div class="v">${st.cookie_count || 0} 个 · ${st.needs_rebind ? "需要重新绑定" : "正常"}</div>
        <div class="k">最后成功</div><div class="v">${st.last_ok_at ? fmtFeedTime(Date.parse(st.last_ok_at) / 1000) : "—"}</div>
        <div class="k">空间</div><div class="v"><a href="https://user.qzone.qq.com/${st.login_uin || ""}" target="_blank">打开 QQ空间</a></div>`;
    }
  } catch (e) {
    $("#qzone-status").innerHTML = `<div class="k">状态</div><div class="v warn">${esc(e.message)}</div>`;
  }

  try {
    const f = await api("/api/qzone/feeds?limit=8");
    const items = (f.feeds && f.feeds.items) || [];
    $("#qzone-feeds").innerHTML = items.length
      ? items
          .map(
            (it) => `<div class="conv-item">
              <div class="conv-main">
                <div class="conv-sub">${esc(fmtFeedTime(it.created_at))} · ❤️ ${it.like_count || 0} · 💬 ${it.comment_count || 0}</div>
                <div style="margin-top:4px;font-size:13px;line-height:1.6">${esc((it.summary || "").slice(0, 160))}</div>
              </div>
              ${it.curkey ? `<a class="btn small" href="${esc(it.curkey)}" target="_blank">查看</a>` : ""}
            </div>`
          )
          .join("")
      : `<p class="hint">还没有说说</p>`;
  } catch (e) {
    $("#qzone-feeds").innerHTML = `<p class="hint">读取动态失败：${esc(e.message)}</p>`;
  }
}

$("#btn-qzone-refresh").addEventListener("click", loadQzone);
$("#btn-qzone-feeds").addEventListener("click", loadQzone);



/* ---------------- 纪念日日期选择器（自定义日历） ---------------- */
function annivIso(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function annivSetDate(wrap, iso) {
  wrap.dataset.annivDate = iso;
  const label = wrap.querySelector(".anniv-date-text");
  if (label) {
    if (!iso) {
      label.textContent = "选择日期";
    } else {
      const [y, m, d] = iso.split("-");
      label.textContent = `${y} 年 ${Number(m)} 月 ${Number(d)} 日`;
    }
  }
}

function renderAnnivCalendar(wrap, viewYear, viewMonth) {
  const picker = wrap.querySelector(".anniv-picker");
  if (!picker) return;
  wrap.dataset.viewYear = viewYear;
  wrap.dataset.viewMonth = viewMonth;
  const selected = wrap.dataset.annivDate || "";
  const first = new Date(viewYear, viewMonth - 1, 1);
  const startWeek = first.getDay();
  const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
  const todayIso = annivIso(new Date());

  let cells = "";
  for (let i = 0; i < startWeek; i++) cells += `<span class="anniv-cell empty"></span>`;
  for (let day = 1; day <= daysInMonth; day++) {
    const iso = `${viewYear}-${String(viewMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cls = [
      "anniv-cell",
      iso === todayIso ? "today" : "",
      iso === selected ? "selected" : "",
    ]
      .filter(Boolean)
      .join(" ");
    cells += `<button type="button" class="${cls}" data-anniv-day="${iso}">${day}</button>`;
  }

  const nowYear = new Date().getFullYear();
  const yearOptions = [];
  for (let y = nowYear + 1; y >= 1950; y--) {
    yearOptions.push(`<option value="${y}" ${y === viewYear ? "selected" : ""}>${y} 年</option>`);
  }
  const monthOptions = [];
  for (let m = 1; m <= 12; m++) {
    monthOptions.push(`<option value="${m}" ${m === viewMonth ? "selected" : ""}>${m} 月</option>`);
  }
  picker.innerHTML = `
    <div class="anniv-picker-head">
      <button type="button" class="anniv-nav" data-anniv-nav="-1">‹</button>
      <div class="anniv-picker-title">
        <select class="anniv-sel anniv-sel-year">${yearOptions.join("")}</select>
        <select class="anniv-sel anniv-sel-month">${monthOptions.join("")}</select>
      </div>
      <button type="button" class="anniv-nav" data-anniv-nav="1">›</button>
    </div>
    <div class="anniv-weekdays">
      ${["日", "一", "二", "三", "四", "五", "六"].map((w) => `<span>${w}</span>`).join("")}
    </div>
    <div class="anniv-grid">${cells}</div>
    <div class="anniv-picker-foot">
      <button type="button" class="btn tiny" data-anniv-today="1">今天</button>
      <button type="button" class="btn tiny" data-anniv-close="1">取消</button>
    </div>`;
}

function annivTogglePicker(wrap) {
  const picker = wrap.querySelector(".anniv-picker");
  if (!picker) return;
  const willOpen = picker.classList.contains("hidden");
  document.querySelectorAll(".anniv-picker").forEach((p) => p.classList.add("hidden"));
  if (!willOpen) return;
  picker.classList.remove("hidden");
  let year, month;
  const current = wrap.dataset.annivDate;
  if (current) {
    const parts = current.split("-").map(Number);
    year = parts[0];
    month = parts[1];
  } else {
    const now = new Date();
    year = now.getFullYear();
    month = now.getMonth() + 1;
  }
  renderAnnivCalendar(wrap, year, month);
}

document.addEventListener("click", (e) => {
  const toggle = e.target.closest("[data-anniv-date-toggle]");
  if (toggle) {
    const wrap = toggle.closest(".anniv-date-wrap");
    const editor = toggle.closest(".anniv-editor");
    if (wrap && editor) annivTogglePicker(editor);
    return;
  }
  const nav = e.target.closest("[data-anniv-nav]");
  if (nav) {
    const editor = nav.closest(".anniv-editor");
    let year = Number(editor.dataset.viewYear);
    let month = Number(editor.dataset.viewMonth) + Number(nav.dataset.annivNav);
    if (month < 1) {
      month = 12;
      year -= 1;
    } else if (month > 12) {
      month = 1;
      year += 1;
    }
    renderAnnivCalendar(editor, year, month);
    return;
  }
  const day = e.target.closest("[data-anniv-day]");
  if (day) {
    const editor = day.closest(".anniv-editor");
    annivSetDate(editor, day.dataset.annivDay);
    editor.querySelector(".anniv-picker").classList.add("hidden");
    return;
  }
  const today = e.target.closest("[data-anniv-today]");
  if (today) {
    const editor = today.closest(".anniv-editor");
    annivSetDate(editor, annivIso(new Date()));
    editor.querySelector(".anniv-picker").classList.add("hidden");
    return;
  }
  const close = e.target.closest("[data-anniv-close]");
  if (close) {
    const editor = close.closest(".anniv-editor");
    editor.querySelector(".anniv-picker").classList.add("hidden");
    return;
  }
  // 点日历面板内部（如下拉框）不要关闭或重建
  if (e.target.closest(".anniv-picker")) return;

  // 点击空白关闭
  if (!e.target.closest(".anniv-date-wrap")) {
    document.querySelectorAll(".anniv-picker").forEach((p) => p.classList.add("hidden"));
  }
});

document.addEventListener("change", (e) => {
  const sel = e.target.closest(".anniv-sel");
  if (!sel) return;
  const editor = sel.closest(".anniv-editor");
  if (!editor) return;
  const year = Number(editor.querySelector(".anniv-sel-year").value);
  const month = Number(editor.querySelector(".anniv-sel-month").value);
  renderAnnivCalendar(editor, year, month);
});

/* 默认选中今天 */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".anniv-editor").forEach((wrap) => {
    if (!wrap.dataset.annivDate) annivSetDate(wrap, annivIso(new Date()));
  });
});




/* ---------------- 用量统计 ---------------- */
function fmtMoney(v) {
  const n = Number(v || 0);
  if (n === 0) return "0";
  if (n < 0.001) return n.toFixed(6);
  if (n < 0.01) return n.toFixed(4);
  return n.toFixed(2);
}

function usageKv(el, data) {
  const box = $(el);
  if (!box) return;
  box.innerHTML = `
    <div class="k">Tokens</div><div class="v">${(data.tokens || 0).toLocaleString()}</div>
    <div class="k">输入（缓存命中）</div><div class="v">${(data.cached || 0).toLocaleString()}</div>
    <div class="k">输出</div><div class="v">${(data.output || 0).toLocaleString()}</div>
    <div class="k">缓存命中率</div><div class="v">${data.hit_rate || 0}%</div>
    <div class="k">估算花费</div><div class="v">¥${fmtMoney(data.cost_cny)}<span class="hint" style="margin-left:6px">$${fmtMoney(data.cost_usd)}</span></div>`;
}

async function loadUsage() {
  try {
    const d = await api("/api/usage?days=30");
    usageKv("#usage-today", d.today || {});
    usageKv("#usage-week", d.week || {});
    usageKv("#usage-month", d.month || {});
    const byDate = {};
    (d.days || []).forEach((x) => (byDate[x.date] = x));
    const days = [];
    for (let i = 13; i >= 0; i--) {
      const dt = new Date();
      dt.setDate(dt.getDate() - i);
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
      days.push(byDate[key] || { date: key, cost_cny: 0, tokens: 0, hit_rate: 0 });
    }
    const maxCost = Math.max(0.0001, ...days.map((x) => x.cost_cny || 0));
    $("#usage-chart").innerHTML = days.length
      ? days
          .map((x) => {
            const h = Math.max(2, Math.round(((x.cost_cny || 0) / maxCost) * 120));
            return `<div class="usage-bar" data-date="${x.date}" data-tokens="${x.tokens}" data-cached="${x.cached || 0}" data-out="${x.output || 0}" data-cost="${x.cost_cny}" data-usd="${x.cost_usd || 0}" data-hit="${x.hit_rate}">
              <div class="usage-bar-fill" style="height:${h}px"></div>
              <span>${x.date.slice(5)}</span>
            </div>`;
          })
          .join("")
      : `<p class="hint">还没有数据（聊几句话后就会出现）</p>`;
    const models = d.model_list || [];
    $("#usage-models").innerHTML = models.length
      ? models
          .map(
            (m) => `<div class="conv-item">
              <div class="conv-main">
                <div class="conv-name">${esc(m.model)}</div>
                <div class="conv-sub">${m.tokens.toLocaleString()} tokens · 缓存命中率 ${m.hit_rate}%</div>
              </div>
              <div class="conv-meta">¥${m.cost_cny}<br/>$${m.cost_usd}</div>
            </div>`
          )
          .join("")
      : `<p class="hint">暂无模型数据</p>`;
    $("#usage-note").textContent = d.note || "";
    bindUsageTips();
  } catch (e) {
    $("#usage-note").textContent = "读取失败：" + e.message;
  }
}

$("#btn-usage-refresh").addEventListener("click", loadUsage);


/* ---------------- 对话记录 ---------------- */
function fmtTurnTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function loadTurns() {
  try {
    const d = await api("/api/turns?limit=60");
    const items = d.items || [];
    const box = $("#turn-list");
    box.innerHTML = items.length
      ? items
          .map(
            (it) => `<div class="turn-item" data-turn-idx="${it.idx}">
              <div class="turn-top">
                <span>${fmtTurnTime(it.ts)}</span>
                <span class="turn-tokens">${it.tokens} tok</span>
              </div>
              <div class="turn-preview">${esc(it.prompt_preview || "（无用户消息）")}</div>
              <div class="turn-reply">${esc(it.reply_preview || "（无回复）")}</div>
            </div>`
          )
          .join("")
      : `<p class="hint" style="padding:16px">还没有对话记录，聊一句就会出现</p>`;
    $$("#turn-list [data-turn-idx]").forEach((el) =>
      el.addEventListener("click", () => openTurn(Number(el.dataset.turnIdx), el))
    );
  } catch (e) {
    $("#turn-list").innerHTML = `<p class="hint" style="padding:16px">读取失败：${esc(e.message)}</p>`;
  }
}

async function openTurn(idx, el) {
  $$("#turn-list .turn-item").forEach((x) => x.classList.remove("active"));
  if (el) el.classList.add("active");
  try {
    const d = await api(`/api/turns/detail?idx=${idx}`);
    if (!d.ok) {
      $("#turn-detail").innerHTML = `<p class="hint" style="padding:20px">${esc(d.error || "读取失败")}</p>`;
      return;
    }
    const t = d.turn;
    const u = t.usage || {};
    const ctx = (t.contexts || "").trim();
    $("#turn-detail").innerHTML = `
      <div class="turn-detail-head">
        <span class="chip">${fmtTurnTime(t.ts)}</span>
        <span class="chip">${esc(t.model || "model")}</span>
        <span class="chip">${u.total || 0} tokens</span>
        <span class="chip">命中 ${u.cached || 0} · 未命中 ${u.miss || 0} · 输出 ${u.out || 0}</span>
        <span class="chip">命中率 ${u.hit_rate || 0}%</span>
        <span class="chip">¥${(t.cost_cny || 0)} / $${(t.cost_usd || 0)}</span>
      </div>
      ${t.truncated ? `<p class="hint" style="padding:0 18px">内容过长，部分字段已截断</p>` : ""}
      <div class="turn-section">
        <div class="turn-label">💬 回复</div>
        <pre class="turn-pre">${esc(t.reply || "（无）")}</pre>
      </div>
      <div class="turn-section">
        <div class="turn-label">📝 用户消息（prompt）</div>
        <pre class="turn-pre">${esc(t.prompt || "（无）")}</pre>
      </div>
      <div class="turn-section">
        <div class="turn-label">⚙️ AI 实际收到的系统提示词（含所有插件注入）</div>
        <pre class="turn-pre">${esc(t.system_prompt || "（无）")}</pre>
      </div>
      <div class="turn-section">
        <div class="turn-label">🧠 上下文（历史消息）</div>
        <pre class="turn-pre">${esc(ctx || "（无）")}</pre>
      </div>
      ${
        (t.tools || []).length
          ? `<div class="turn-section"><div class="turn-label">🔧 可用工具</div><pre class="turn-pre">${esc((t.tools || []).join("\n"))}</pre></div>`
          : ""
      }`;
  } catch (e) {
    $("#turn-detail").innerHTML = `<p class="hint" style="padding:20px">读取失败：${esc(e.message)}</p>`;
  }
}

$("#btn-turns-refresh").addEventListener("click", loadTurns);




/* ---------------- 用量柱状图 tooltip ---------------- */
function bindUsageTips() {
  const tip = $("#usage-tip");
  const chart = $("#usage-chart");
  if (!tip || !chart) return;
  chart.querySelectorAll(".usage-bar").forEach((bar) => {
    bar.addEventListener("mouseenter", () => {
      const tokens = Number(bar.dataset.tokens || 0);
      const cached = Number(bar.dataset.cached || 0);
      const out = Number(bar.dataset.out || 0);
      const cost = Number(bar.dataset.cost || 0);
      const usd = Number(bar.dataset.usd || 0);
      const hit = bar.dataset.hit || "0";
      tip.innerHTML = `
        <div class="tip-date">${bar.dataset.date}</div>
        <div class="tip-row"><span>Tokens</span><b>${tokens.toLocaleString()}</b></div>
        <div class="tip-row"><span>缓存命中</span><b>${cached.toLocaleString()}</b></div>
        <div class="tip-row"><span>输出</span><b>${out.toLocaleString()}</b></div>
        <div class="tip-row"><span>命中率</span><b>${hit}%</b></div>
        <div class="tip-row"><span>花费</span><b>¥${fmtMoney(cost)}</b></div>
        <div class="tip-row"><span>折合</span><b>$${fmtMoney(usd)}</b></div>`;
      tip.classList.remove("hidden");
    });
    bar.addEventListener("mousemove", (e) => {
      const parent = tip.offsetParent || chart.parentElement;
      const rect = parent.getBoundingClientRect();
      let left = e.clientX - rect.left + 14;
      let top = e.clientY - rect.top - 10;
      if (left + 190 > rect.width) left = rect.width - 200;
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    });
    bar.addEventListener("mouseleave", () => tip.classList.add("hidden"));
  });
}






/* ---------------- 插件市场 ---------------- */
let marketItems = [];
let marketCategory = "全部";
let marketQuery = "";
let marketLoading = false;

let marketUpload = null;

function marketMatches(it) {
  if (marketCategory !== "全部" && String(it.category || "其他") !== marketCategory) return false;
  const q = marketQuery.trim().toLowerCase();
  if (!q) return true;
  return [it.display_name, it.name, it.author, it.desc].some((x) => String(x || "").toLowerCase().includes(q));
}

function renderMarket() {
  const grid = $("#market-grid");
  if (!grid) return;
  const filtered = marketItems.filter(marketMatches);
  const shown = filtered.slice(0, 60);
  grid.innerHTML = shown.length
    ? shown
        .map(
          (it) => `<div class="market-card" data-plugin="${esc(it.id)}">
            <div class="market-cover">
              ${it.logo ? `<img src="${esc(it.logo)}" loading="lazy" alt="" onerror="this.remove()" />` : `<div class="market-cover-fallback">🧩</div>`}
            </div>
            <div class="market-body">
              <div class="market-title">${esc(it.display_name)}</div>
              <div class="market-sub">${esc(it.name)} · v${esc(it.version || "?")} · ${esc(it.author || "?")}</div>
              ${it.local_modified ? `<div class="market-flag" title="${esc(it.modify_note || "")}">⚠ 源码已改动，谨慎更新</div>` : ""}
              <div class="market-desc">${esc((it.desc || "").slice(0, 120))}</div>
              <div class="market-meta">
                <span>★ ${it.stars || 0}</span>
                <span>下载 ${it.downloads || 0}</span>
                <span>${esc(it.category || "其他")}</span>
              </div>
              <div class="market-actions">
                ${
                  it.installed
                    ? `<button class="btn small" disabled>已安装${it.installed_version ? " v" + esc(it.installed_version) : ""}</button>
                       ${
                         it.installed_version && it.version && it.installed_version !== it.version
                           ? `<button class="btn primary small" data-market-update="${esc(it.id)}">更新 v${esc(it.version)}</button>`
                           : ""
                       }
                       <button class="btn small danger" data-market-uninstall="${esc(it.id)}">卸载</button>`
                    : `<button class="btn primary small" data-market-install="${esc(it.id)}">安装</button>`
                }
                ${it.repo ? `<a class="btn small" href="${esc(it.repo)}" target="_blank">仓库</a>` : ""}
              </div>
            </div>
          </div>`
        )
        .join("")
    : `<p class="hint">没有匹配的插件</p>`;
  $$("#market-grid [data-market-update]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.marketUpdate;
      const it = marketItems.find((x) => x.id === id) || {};
      const warn = it.local_modified ? "\n\n⚠ 这个插件源码被本地改动过，更新会用市场版覆盖，确定继续？" : "";
      if (!(await modalConfirm({ title: "更新插件", message: `更新插件 ${it.name || id} 到 v${it.version || "?"}？${warn}`, okText: "确认更新" }))) return;
      btn.disabled = true;
      btn.textContent = "更新中…";
      try {
        const r = await api("/api/market/update", { method: "POST", body: JSON.stringify({ id }) });
        toast(r.ok ? "更新请求成功，正在重载…" : r.error || "更新失败", 6000);
        setTimeout(() => loadMarket(true), 2500);
        setTimeout(() => loadPlugins && loadPlugins(), 4000);
      } catch (e) {
        toast("更新失败：" + e.message, 6000);
        btn.disabled = false;
      }
    })
  );

  $$("#market-grid [data-market-uninstall]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.marketUninstall;
      const it = marketItems.find((x) => x.id === id) || {};
      const name = it.name || id;
      if (!(await modalConfirm({ title: "卸载插件", message: `卸载插件 ${name}？\n会同时删除它的配置和数据。`, okText: "确认卸载" }))) return;
      btn.disabled = true;
      btn.textContent = "卸载中…";
      try {
        const r = await api("/api/plugins/uninstall", {
          method: "POST",
          body: JSON.stringify({ plugin_id: name, delete_config: true, delete_data: true }),
        });
        toast(r.ok ? "已卸载" : r.error || "卸载失败", 6000);
        setTimeout(() => loadMarket(true), 1500);
        setTimeout(() => loadPlugins && loadPlugins(), 2500);
      } catch (e) {
        toast("卸载失败：" + e.message, 6000);
        btn.disabled = false;
        btn.textContent = "卸载";
      }
    })
  );

  $$("#market-grid [data-market-install]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const id = btn.dataset.marketInstall;
      if (!(await modalConfirm({ title: "安装插件", message: `安装插件 ${id}？`, okText: "确认安装", danger: false }))) return;
      btn.disabled = true;
      btn.textContent = "安装中…";
      try {
        const r = await api("/api/market/install", {
          method: "POST",
          body: JSON.stringify({ id }),
        });
        toast(r.ok ? "安装请求成功，正在重载…" : r.error || "安装失败", 6000);
        setTimeout(() => loadMarket(true), 2500);
        setTimeout(() => loadPlugins && loadPlugins(), 4000);
      } catch (e) {
        toast("安装失败：" + e.message, 6000);
        btn.disabled = false;
        btn.textContent = "安装";
      }
    })
  );
}

function renderMarketCats() {
  const box = $("#market-cats");
  if (!box) return;
  const counts = new Map();
  for (const it of marketItems) {
    const c = String(it.category || "其他");
    counts.set(c, (counts.get(c) || 0) + 1);
  }
  const cats = ["全部", ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map((x) => x[0])];
  box.innerHTML = cats
    .map(
      (c) =>
        `<span class="chip market-cat ${c === marketCategory ? "active" : ""}" data-cat="${esc(c)}">${esc(c)}${counts.get(c) ? ` ${counts.get(c)}` : ""}</span>`
    )
    .join("");
  $$("#market-cats [data-cat]").forEach((el) =>
    el.addEventListener("click", () => {
      marketCategory = el.dataset.cat;
      renderMarketCats();
      renderMarket();
    })
  );
}

async function loadMarket(force = false) {
  if (marketLoading) return;
  marketLoading = true;
  const box = $("#market-grid");
  const status = $("#market-status");
  if (status) status.textContent = "加载中…";
  if (box) box.innerHTML = `<p class="hint">正在从官方市场拉取…</p>`;
  try {
    const d = await api(`/api/market${force ? "?force=1" : ""}`);
    if (!d.ok) throw new Error(d.error || "加载失败");
    marketItems = d.items || [];
    if (status) status.textContent = `共 ${marketItems.length} 个插件${d.cached ? "（缓存）" : ""}`;
    renderMarketCats();
    renderMarket();
  } catch (e) {
    if (status) status.textContent = "加载失败";
    if (box) box.innerHTML = `<p class="hint">${esc(e.message)}</p>`;
  } finally {
    marketLoading = false;
  }
}

const marketSearchEl = $("#market-search");
if (marketSearchEl) {
  marketSearchEl.addEventListener("input", () => {
    marketQuery = marketSearchEl.value;
    renderMarket();
  });
}
const marketRefreshBtn = $("#btn-market-refresh");
if (marketRefreshBtn) marketRefreshBtn.addEventListener("click", () => loadMarket(true));


/* ---------------- 主动消息面板 ---------------- */
function fmtProactiveTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function proactiveCountdown(ts) {
  if (!ts) return "—";
  const sec = Math.round(ts - Date.now() / 1000);
  if (sec <= 0) return "可触发";
  return `${Math.ceil(sec / 60)} 分钟后`;
}

async function loadProactivePanel() {
  const box = document.getElementById("proactive-ops");
  if (!box) return;
  try {
    const d = await api("/api/proactive/status");
    const rows = d.targets || [];
    box.innerHTML = rows.length
      ? rows
          .map((t) => {
            const badge = {
              paused: "已暂停",
              limit: "今日已达上限",
              silence: "未回复达上限",
              waiting: "等待中",
              ready: "可触发",
            }[t.status] || t.status;
            const cls = t.status === "ready" ? "ok" : t.status === "waiting" ? "" : "warn";
            return `<div class="proactive-row" data-target="${esc(t.target)}">
              <div class="proactive-main">
                <div class="proactive-title">${esc(t.target)} <span class="plugin-badge ${cls}">${esc(badge)}</span>${t.has_override ? ' <span class="plugin-badge">独立策略</span>' : ""}</div>
                <div class="proactive-sub">上次 ${fmtProactiveTime(t.last_sent)} · 下次 ${proactiveCountdown(t.next_at)} · 未回复 ${t.unanswered}/${t.max_unanswered} · 今日 ${t.count}/${t.daily_limit} · 沉默 ${t.silence_min} 分钟</div>
              </div>
              <div class="proactive-actions">
                <button class="btn small" data-pa="send">立即发</button>
                <button class="btn small" data-pa="edit">策略</button>
                <button class="btn small" data-pa="${t.paused ? "resume" : "pause"}">${t.paused ? "恢复" : "暂停"}</button>
                <button class="btn small danger" data-pa="reset">重置</button>
              </div>
            </div>`;
          })
          .join("")
      : `<p class="hint">还没有配置主动消息对象（在「生效对象」里添加）</p>`;

    document.querySelectorAll("#proactive-ops .proactive-row").forEach((row) => {
      const target = row.dataset.target;
      row.querySelectorAll("[data-pa]").forEach((btn) =>
        btn.addEventListener("click", async () => {
          const action = btn.dataset.pa;
          if (action === "edit") {
            openProactiveOverride(target);
            return;
          }
          if (action === "reset" && !(await modalConfirm({ title: "重置主动消息", message: `重置 ${target} 的主动消息状态？`, okText: "确认重置" }))) return;
          btn.disabled = true;
          try {
            const r = await api("/api/proactive/action", {
              method: "POST",
              body: JSON.stringify({ action, target }),
            });
            toast(r.ok ? "已执行" : r.error || "操作失败");
            setTimeout(loadProactivePanel, 1200);
          } catch (e) {
            toast("操作失败：" + e.message);
          } finally {
            btn.disabled = false;
          }
        })
      );
    });
  } catch (e) {
    box.innerHTML = `<p class="hint">读取失败：${esc(e.message)}</p>`;
  }
}

async function openProactiveOverride(target) {
  const st = await api("/api/proactive/status");
  const row = (st.targets || []).find((x) => x.target === target) || {};
  const res = await modalPrompt({
    title: `主动消息策略：${target}`,
    fields: [
      { key: "proactive_min_interval_min", label: "最小间隔（分钟）", value: row.min_interval_min ?? "" },
      { key: "proactive_max_interval_min", label: "最大间隔（分钟）", value: row.max_interval_min ?? "" },
      { key: "proactive_daily_limit", label: "每日上限（条）", value: row.daily_limit ?? "" },
      { key: "proactive_silence_min", label: "沉默触发（分钟）", value: row.silence_min ?? "" },
      { key: "proactive_max_unanswered", label: "未回复上限（次）", value: row.max_unanswered ?? "" },
      { key: "prompt", label: "专属提示词（留空用全局）", type: "textarea", value: "" },
    ],
    hint: "留空表示沿用全局配置；清空提示词会恢复全局提示词。",
    okText: "保存",
  });
  if (!res) return;
  const r = await api("/api/proactive/override", {
    method: "POST",
    body: JSON.stringify({ target, ...res }),
  });
  toast(r.ok ? "已保存策略" : r.error || "保存失败");
  loadProactivePanel();
}

const proactiveRefreshBtn = document.getElementById("btn-proactive-refresh");
if (proactiveRefreshBtn) proactiveRefreshBtn.addEventListener("click", loadProactivePanel);


/* ---------------- 聊天日记 ---------------- */
async function loadDiary() {
  const box = $("#diary-list");
  if (!box) return;
  try {
    const d = await api("/api/diary?limit=30");
    const items = d.items || [];
    box.innerHTML = items.length
      ? items
          .map(
            (it) => `<details class="diary-item">
              <summary>
                <span class="diary-date">${esc(it.date)}</span>
                <span class="diary-scope">${esc(it.scope)}</span>
                <span class="diary-count">${it.msg_count} 条消息</span>
              </summary>
              <div class="diary-page">${esc(it.page)}</div>
            </details>`
          )
          .join("")
      : `<p class="hint">还没有日记，今晚 23:30 会自动写第一页</p>`;
  } catch (e) {
    box.innerHTML = `<p class="hint">读取日记失败：${esc(e.message)}</p>`;
  }
}

const diaryRefreshBtn = $("#btn-refresh-diary");
if (diaryRefreshBtn) diaryRefreshBtn.addEventListener("click", loadDiary);


/* ---------------- Breeze 音色管理 ---------------- */
let breezeVoiceFile = null;

async function loadBreezeVoices() {
  const box = document.getElementById("breeze-voice-list");
  if (!box) return;
  try {
    const d = await api("/api/breeze/voices");
    if (!d.ok) {
      box.innerHTML = `<p class="hint">${esc(d.error || "读取音色失败")}</p>`;
      return;
    }
    const voices = d.voices || [];
    box.innerHTML = voices.length
      ? `<div class="breeze-voice-items">${voices
          .map(
            (v) => `<div class="breeze-voice-item">
              <div class="breeze-voice-main">
                <div class="breeze-voice-name">${esc(v.name)}${v.id === d.active ? ' <span class="plugin-badge ok">使用中</span>' : ""}</div>
                <div class="breeze-voice-sub">${esc(v.id)}${v.category ? " · " + esc(v.category) : ""}</div>
              </div>
              <audio controls preload="none" src="/api/breeze/preview?voice_id=${encodeURIComponent(v.id)}&text=${encodeURIComponent("你好呀，我是小鲸鱼，今天过得怎么样？")}" style="height:28px;max-width:200px"></audio>
              <button class="btn small" data-breeze-use="${esc(v.id)}" ${v.id === d.active ? "disabled" : ""}>使用</button>
              <button class="btn small danger" data-breeze-del="${esc(v.id)}">删除</button>
            </div>`
          )
          .join("")}</div>`
      : `<p class="hint">还没有音色：配置 API Key 后可以上传音频创建克隆音色</p>`;
    document.querySelectorAll("#breeze-voice-list [data-breeze-use]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const r = await api("/api/breeze/switch", {
          method: "POST",
          body: JSON.stringify({ voice_id: btn.dataset.breezeUse }),
        });
        toast(r.ok ? "已切换音色" : r.error || "切换失败");
        loadBreezeVoices();
      })
    );
    document.querySelectorAll("#breeze-voice-list [data-breeze-del]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        if (!(await modalConfirm({ title: "删除音色", message: "删除这个 Breeze 音色？", okText: "确认删除" }))) return;
        const r = await api("/api/breeze/delete", {
          method: "POST",
          body: JSON.stringify({ voice_id: btn.dataset.breezeDel }),
        });
        toast(r.ok ? "已删除" : r.error || "删除失败");
        loadBreezeVoices();
      })
    );
  } catch (e) {
    box.innerHTML = `<p class="hint">读取音色失败：${esc(e.message)}</p>`;
  }
}

const breezeFileEl = document.getElementById("breeze-voice-file");
if (breezeFileEl && !breezeFileEl._bound) {
  breezeFileEl._bound = true;
  breezeFileEl.addEventListener("change", () => {
    breezeVoiceFile = (breezeFileEl.files || [])[0] || null;
  });
}

const breezeCloneBtn = document.getElementById("btn-breeze-clone");
if (breezeCloneBtn && !breezeCloneBtn._bound) {
  breezeCloneBtn._bound = true;
  breezeCloneBtn.addEventListener("click", async () => {
    const name = (document.getElementById("breeze-voice-name").value || "").trim();
    if (!name) return toast("先给音色起个名字");
    if (!breezeVoiceFile) return toast("先选择一段音频");
    breezeCloneBtn.disabled = true;
    breezeCloneBtn.textContent = "克隆中…";
    try {
      const dataUrl = await readAsDataURL(breezeVoiceFile);
      const r = await api("/api/breeze/clone", {
        method: "POST",
        body: JSON.stringify({ name, audio: String(dataUrl).split(",")[1] || "" }),
      });
      if (r.ok) {
        toast("音色已创建");
        document.getElementById("breeze-voice-name").value = "";
        document.getElementById("breeze-voice-file").value = "";
        breezeVoiceFile = null;
        loadBreezeVoices();
      } else {
        toast(r.error || "创建失败", 6000);
      }
    } catch (e) {
      toast("创建失败：" + e.message, 6000);
    } finally {
      breezeCloneBtn.disabled = false;
      breezeCloneBtn.textContent = "创建克隆音色";
    }
  });
}

/* 载入 Breeze 配置 */
async function loadBreezeConfig() {
  try {
    const b = await api("/api/plugins/config?plugin_id=astrbot_plugin_breeze_tts");
    breezeCfg = Object.assign({}, b.config || {});
  } catch (e) {
    breezeCfg = breezeCfg || {};
  }
}
/* ---------- UI：鼠标跟随光斑 ---------- */
(() => {
  if (window.__uiSpotlight) return;
  window.__uiSpotlight = true;
  let raf = 0;
  let pending = null;
  const apply = () => {
    raf = 0;
    if (!pending) return;
    const { el, x, y } = pending;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${Math.round(x - r.left)}px`);
    el.style.setProperty("--my", `${Math.round(y - r.top)}px`);
  };
  document.addEventListener(
    "mousemove",
    (e) => {
      const el = e.target && e.target.closest
        ? e.target.closest(".card, .market-card, .plugin-card, .behavior-head")
        : null;
      if (!el) return;
      pending = { el, x: e.clientX, y: e.clientY };
      if (!raf) raf = requestAnimationFrame(apply);
    },
    { passive: true }
  );
})();
