/* 运营台：她今天 / 健康自检 / 备份恢复 / 预算 / AI 味复盘 / 隐私与引导 */
(function () {
  if (window.__opsLoaded) return;
  window.__opsLoaded = true;

  const OPS = {
    loaded: false,
    today: null,
    health: null,
    backups: [],
    budget: null,
    taste: null,
    settings: null,
    privacyTimer: null,
  };

  function fmt(n) {
    return Number(n || 0).toLocaleString("zh-CN");
  }

  function badge(ok, text) {
    return `<span class="ops-dot ${ok ? "ok" : "bad"}"></span>${esc(text)}`;
  }

  async function loadOps() {
    const root = document.getElementById("ops-root");
    if (!root) return;
    root.innerHTML = `<div class="card"><p class="hint">正在读取运营数据…</p></div>`;
    try {
      const [today, health, backups, budget, taste, settings, memory] = await Promise.all([
        api("/api/ops/today"),
        api("/api/ops/health"),
        api("/api/ops/backups"),
        api("/api/ops/budget"),
        api("/api/ops/taste?limit=12"),
        api("/api/ops/settings"),
        api("/api/ops/memory"),
      ]);
      OPS.today = today;
      OPS.health = health;
      OPS.backups = backups.backups || [];
      OPS.budget = budget;
      OPS.taste = taste;
      OPS.settings = settings;
      OPS.memory = memory;
      renderOps();
      applyPrivacyMask();
    } catch (e) {
      root.innerHTML = `<div class="card"><p class="hint">读取失败：${esc(e.message)}</p></div>`;
    }
  }

  function renderOps() {
    const root = document.getElementById("ops-root");
    if (!root) return;
    const t = OPS.today || {};
    const h = OPS.health || { checks: [] };
    const b = OPS.budget || {};
    const taste = OPS.taste || { flagged: [], total: 0, ratio: 0 };

    root.innerHTML = `
      <div class="ops-hero card">
        <div class="ops-hero-main">
          <div class="ops-kicker">她今天 · ${esc(t.date || "")} ${esc(t.time || "")}</div>
          <div class="ops-title">${esc(t.current || "还没有今天的时间线")}</div>
          <div class="ops-tags">
            <span class="ops-tag">心情 ${esc(t.mood || "未知")}</span>
            ${t.energy != null ? `<span class="ops-tag">精力 ${esc(String(t.energy))}/5</span>` : ""}
            ${t.hint ? `<span class="ops-tag">${esc(t.hint)}</span>` : ""}
          </div>
          <div class="ops-meta">核心设定 ${fmt(t.core_chars)} 字 · 更新于 ${esc(t.core_updated || "—")} ${t.core_pending ? `· ${t.core_pending} 条 AI 提议待确认` : ""}</div>
        </div>
        <div class="ops-hero-side">
          <div class="ops-mini-label">最近日记</div>
          <div class="ops-diary">${t.diary ? esc(t.diary) : "还没有生成日记"}</div>
        </div>
      </div>

      <div class="ops-grid">
        <div class="card ops-card">
          <div class="card-head"><h3>健康自检</h3><span class="ops-pill ${h.all_ok ? "ok" : "warn"}">${esc(h.summary || "")}</span></div>
          <div class="ops-checks">
            ${(h.checks || []).map((c) => `<div class="ops-check"><div class="ops-check-name">${badge(c.ok, c.name)}</div><div class="ops-check-detail">${esc(c.detail || "")}</div></div>`).join("")}
          </div>
          <div class="ops-actions">
            <button class="btn small" id="ops-health-refresh">重新体检</button>
          </div>
        </div>

        <div class="card ops-card">
          <div class="card-head"><h3>备份与恢复</h3><button class="btn small primary" id="ops-backup-now">立即备份</button></div>
          <p class="hint">包含人设、核心设定、配置、插件数据、日记、主数据库；自动保留最近 7 份。</p>
          <div class="ops-backups">
            ${OPS.backups.length ? OPS.backups.map((x) => `<div class="ops-backup-row">
              <div><b>${esc(x.time)}</b><span class="hint"> ${x.size_mb} MB</span><div class="ops-mono">${esc(x.name)}</div></div>
              <div class="ops-actions"><button class="btn small" data-restore="${esc(x.name)}">恢复</button></div>
            </div>`).join("") : `<p class="hint">还没有备份</p>`}
          </div>
        </div>

        <div class="card ops-card">
          <div class="card-head"><h3>成本与预算</h3><span class="ops-pill ${b.alert ? "warn" : "ok"}">${b.alert ? "接近上限" : "正常"}</span></div>
          <div class="ops-budget-row"><span>今日 Token</span><b>${fmt(b.tokens && b.tokens.total)} / ${fmt(b.budget && b.budget.daily_tokens)}</b></div>
          <div class="ops-progress"><i style="width:${Math.min(100, (b.token_ratio || 0) * 100)}%"></i></div>
          <div class="ops-budget-row"><span>今日语音字符</span><b>${fmt(b.voice_used)} / ${fmt(b.budget && b.budget.daily_voice_chars)}</b></div>
          <div class="ops-progress"><i style="width:${Math.min(100, (b.voice_ratio || 0) * 100)}%"></i></div>
          <div class="ops-budget-row"><span>估算成本</span><b>¥${b.cost_cny || 0}</b></div>
          <div class="ops-budget-form">
            <label>每日 Token 上限<input type="text" inputmode="numeric" id="ops-budget-tokens" value="${fmt(b.budget ? b.budget.daily_tokens : 200000)}" /></label>
            <label>每日语音字符<input type="text" inputmode="numeric" id="ops-budget-voice" value="${fmt(b.budget ? b.budget.daily_voice_chars : 5000)}" /></label>
            <label>提醒比例<input type="number" step="0.05" id="ops-budget-ratio" value="${b.budget ? b.budget.alert_ratio : 0.8}" /></label>
            <button class="btn small primary" id="ops-budget-save">保存预算</button>
          </div>
        </div>

        <div class="card ops-card">
          <div class="card-head"><h3>AI 味复盘</h3><span class="ops-pill ${taste.ratio > 0.25 ? "warn" : "ok"}">${Math.round((taste.ratio || 0) * 100)}% 命中</span></div>
          <p class="hint">扫描最近 ${taste.total || 0} 条对外回复，标出官腔、模板句和过长回复。</p>
          <div class="ops-taste">
            ${(taste.flagged || []).length ? taste.flagged.map((x) => `<div class="ops-taste-row">
              <div class="ops-taste-time">${esc(x.ts)}</div>
              <div class="ops-taste-text">${esc(x.reply)}</div>
              <div class="ops-taste-hits">${(x.hits || []).map((h) => `<span>${esc(h)}</span>`).join("")}</div>
            </div>`).join("") : `<p class="hint">最近没有明显 AI 味，继续保持</p>`}
          </div>
        </div>

        <div class="card ops-card">
          <div class="card-head"><h3>记忆总览</h3><button class="btn small" id="ops-memory-refresh">刷新</button></div>
          <p class="hint">三层记忆分开存，先让它们各司其职；核心设定优先级最高，日记是原始流水。</p>
          <div class="ops-memory">
            ${((OPS.memory && OPS.memory.layers) || []).map((x) => `<div class="ops-check"><div class="ops-check-name">${esc(x.name)}</div><div class="ops-check-detail">${esc(String(x.count))} · ${esc(x.desc)}</div></div>`).join("")}
          </div>
          <div class="ops-actions">
            <button class="btn small" onclick="switchTab('chatmem')">打开聊天记忆</button>
            <button class="btn small" onclick="switchTab('persona')">管理核心设定</button>
          </div>
        </div>

        <div class="card ops-card">
          <div class="card-head"><h3>隐私与引导</h3></div>
          <div class="ops-setting-row">
            <div><b>隐藏 QQ 号 / 群号</b><div class="hint">控制台里把 5–12 位号码显示成 ***，方便截图分享</div></div>
            <label class="switch"><input type="checkbox" id="ops-privacy" ${OPS.settings && OPS.settings.privacy_mask ? "checked" : ""}/><span></span></label>
          </div>
          <div class="ops-setting-row">
            <div><b>每日自动备份</b><div class="hint">控制台启动时检查，24 小时内只备份一次</div></div>
            <label class="switch"><input type="checkbox" id="ops-auto-backup" ${OPS.settings && OPS.settings.backup_auto ? "checked" : ""}/><span></span></label>
          </div>
          <div class="ops-actions">
            <button class="btn small" id="ops-wizard-open">重新运行新手引导</button>
            <button class="btn small" id="ops-log-rotate">轮转日志</button>
          </div>
        </div>
      </div>

      <div id="ops-wizard-root"></div>
    `;

    document.getElementById("ops-health-refresh").onclick = () => {
      toast("正在重新体检…");
      loadOps();
    };
    document.getElementById("ops-backup-now").onclick = async () => {
      const btn = document.getElementById("ops-backup-now");
      btn.disabled = true;
      try {
        const r = await api("/api/ops/backup", { method: "POST", body: JSON.stringify({ label: "manual" }) });
        toast(r.ok ? `备份完成：${r.name}` : r.error || "备份失败", 5000);
        loadOps();
      } finally {
        btn.disabled = false;
      }
    };
    document.querySelectorAll("#ops-root [data-restore]").forEach((btn) => {
      btn.onclick = () => restoreBackup(btn.dataset.restore);
    });
    document.getElementById("ops-budget-save").onclick = saveBudget;
    bindBudgetFormat();
    document.getElementById("ops-privacy").onchange = async (e) => {
      await api("/api/ops/settings/save", { method: "POST", body: JSON.stringify({ privacy_mask: e.target.checked }) });
      toast(e.target.checked ? "已开启隐私模式，刷新后生效" : "已关闭隐私模式", 4000);
      location.reload();
    };
    document.getElementById("ops-auto-backup").onchange = async (e) => {
      await api("/api/ops/settings/save", { method: "POST", body: JSON.stringify({ backup_auto: e.target.checked }) });
      toast("已保存");
    };
    document.getElementById("ops-memory-refresh").onclick = () => loadOps();
    document.getElementById("ops-wizard-open").onclick = () => window.showGuide && window.showGuide(true);
    document.getElementById("ops-log-rotate").onclick = async () => {
      const r = await api("/api/ops/logs/rotate", { method: "POST", body: JSON.stringify({}) });
      toast(r.rotated && r.rotated.length ? "已轮转：" + r.rotated.join("、") : "日志未超过 5MB，不需要轮转");
    };
  }

  async function restoreBackup(name) {
    const ok = await modalConfirm({
      title: "恢复备份",
      message: `恢复备份 ${name}？\n会先自动备份当前状态，然后用备份覆盖人设、配置、插件数据、日记和数据库。`,
      okText: "确认恢复",
    });
    if (!ok) return;
    toast("正在恢复，请稍候…", 8000);
    try {
      const r = await api("/api/ops/restore", {
        method: "POST",
        body: JSON.stringify({ name, modules: ["personas", "config", "plugin_data", "whale_state", "database"] }),
      });
      toast(r.ok ? `恢复完成，共 ${(r.restored || []).length} 项` : r.error || "恢复失败", 8000);
      if (r.ok) setTimeout(() => location.reload(), 1500);
    } catch (e) {
      toast("恢复失败：" + e.message, 8000);
    }
  }

  function budgetNumber(id) {
    const raw = String(document.getElementById(id).value || "").replace(/[,，\s]/g, "");
    return Number(raw || 0);
  }

  function bindBudgetFormat() {
    ["ops-budget-tokens", "ops-budget-voice"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el || el._budgetFmt) return;
      el._budgetFmt = true;
      el.addEventListener("blur", () => {
        const n = budgetNumber(id);
        el.value = Number.isFinite(n) ? fmt(n) : "0";
      });
    });
  }

  async function saveBudget() {
    const payload = {
      budget: {
        daily_tokens: budgetNumber("ops-budget-tokens"),
        daily_voice_chars: budgetNumber("ops-budget-voice"),
        alert_ratio: Number(document.getElementById("ops-budget-ratio").value || 0.8),
      },
    };
    const r = await api("/api/ops/budget/save", { method: "POST", body: JSON.stringify(payload) });
    toast(r.ok ? "预算已保存" : "保存失败");
    loadOps();
  }

  /* ---------------- 隐私遮罩 ---------------- */
  function applyPrivacyMask() {
    if (!OPS.settings || !OPS.settings.privacy_mask) return;
    const mask = (text) => text.replace(/(?<!\d)(\d{5,12})(?!\d)/g, "***");
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const p = node.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        const tag = p.tagName;
        if (["INPUT", "TEXTAREA", "SCRIPT", "STYLE", "CODE", "PRE"].includes(tag)) return NodeFilter.FILTER_REJECT;
        if (p.closest(".no-privacy-mask")) return NodeFilter.FILTER_REJECT;
        return node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      const next = mask(n.textContent);
      if (next !== n.textContent) n.textContent = next;
    });
  }

  /* ---------------- 新手引导 ---------------- */
  function showWizard(force) {
    const box = document.getElementById("ops-wizard-root");
    if (!box) return;
    if (!force && OPS.settings && OPS.settings.onboarding_done) return;
    let step = 0;
    const steps = [
      {
        title: "先给她一个身份",
        desc: "人设文件决定她怎么说话，核心设定决定她不能忘什么。",
        action: `<button class="btn small" onclick="switchTab('persona')">打开人设页</button>`,
      },
      {
        title: "接上模型",
        desc: "在「插件」里确认 AstrBot 已连上模型；模型 Key 在 AstrBot 管理端配置。",
        action: `<button class="btn small" onclick="switchTab('plugins')">查看插件</button>`,
      },
      {
        title: "声音和社交",
        desc: "聊天设置里可以开语音、调概率；QQ空间在空间页管理。",
        action: `<button class="btn small" onclick="switchTab('behavior')">打开聊天设置</button>`,
      },
      {
        title: "设好边界",
        desc: "响应策略里配置白名单、高峰期和低频时段，避免她乱说话。",
        action: `<button class="btn small" onclick="switchTab('policy')">打开响应策略</button>`,
      },
    ];
    const render = () => {
      const s = steps[step];
      box.innerHTML = `<div class="modal-mask ops-wizard-mask"><div class="modal-box ops-wizard">
        <div class="modal-head"><div class="modal-title">第一次养小鲸鱼</div><button class="modal-close" id="ops-wizard-x">×</button></div>
        <div class="modal-body">
          <div class="ops-wizard-step">第 ${step + 1} / ${steps.length} 步</div>
          <div class="ops-wizard-title">${esc(s.title)}</div>
          <div class="ops-wizard-desc">${esc(s.desc)}</div>
          <div class="ops-wizard-action">${s.action}</div>
        </div>
        <div class="modal-foot">
          <button class="btn small" id="ops-wizard-skip">以后再说</button>
          <div class="ops-actions">
            <button class="btn small" id="ops-wizard-prev" ${step === 0 ? "disabled" : ""}>上一步</button>
            <button class="btn small primary" id="ops-wizard-next">${step === steps.length - 1 ? "完成" : "下一步"}</button>
          </div>
        </div>
      </div></div>`;
      document.getElementById("ops-wizard-x").onclick = finish;
      document.getElementById("ops-wizard-skip").onclick = finish;
      document.getElementById("ops-wizard-prev").onclick = () => { if (step > 0) { step--; render(); } };
      document.getElementById("ops-wizard-next").onclick = async () => {
        if (step < steps.length - 1) { step++; render(); }
        else finish();
      };
    };
    const finish = async () => {
      box.innerHTML = "";
      await api("/api/ops/onboarding/complete", { method: "POST", body: JSON.stringify({}) });
    };
    render();
  }

  window.loadOps = loadOps;

  document.addEventListener("DOMContentLoaded", async () => {
    if (location.hash === "#ops") loadOps();
    try {
      const st = await api("/api/ops/settings");
      OPS.settings = st;
      if (st.privacy_mask) {
        applyPrivacyMask();
        setInterval(applyPrivacyMask, 2000);
      }
    } catch (e) {}
  });
})();
