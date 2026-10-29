/* 使用引导：新用户从 QQ 登录到试聊的完整步骤 */
(function () {
  if (window.__guideLoaded) return;
  window.__guideLoaded = true;

  const GUIDE = {
    step: 0,
    open: false,
    checks: {},
    settings: null,
    fab: null,
  };

  const STEPS = [
    {
      id: "start",
      title: "启动软件，登录 QQ",
      desc: "软件启动后，AstrBot、NapCat、控制台会自动跑起来。QQ 需要你扫码登录一次。",
      points: [
        "确认顶部状态是「AstrBot 运行中」「NapCat 已登录」",
        "点下面的按钮打开 NapCat 管理端",
        "用手机 QQ 扫码，并在手机上确认登录",
        "回到这里点「检查状态」",
      ],
      actions: [
        { label: "打开 NapCat 管理端", kind: "status" },
      ],
      check: (c) => ({
        ok: !!(c.status && c.status.astrbot && c.status.astrbot.up && c.status.napcat && c.status.napcat.up && (c.status.napcat.uin || c.status.connection === 2)),
        text: c.status && c.status.napcat && c.status.napcat.uin ? `已登录 QQ ${c.status.napcat.uin}` : "还没有登录 QQ",
      }),
    },
    {
      id: "model",
      title: "注册 DeepSeek，配置模型",
      desc: "她的大脑需要模型 API。没有模型，她不会说话。",
      points: [
        "打开 DeepSeek 开放平台，注册/登录",
        "创建 API Key（sk- 开头），复制",
        "回到 AstrBot 管理端 → 服务提供商 → 添加 DeepSeek",
        "填入 API Key，选择 deepseek-chat 或 deepseek-flash",
      ],
      actions: [
        { label: "DeepSeek 开放平台", href: "https://platform.deepseek.com/api_keys" },
        { label: "打开 AstrBot 管理端", kind: "astrbot" },
      ],
      check: (c) => ({
        ok: !!(c.status && c.status.model && c.status.model.model && c.status.model.key_masked),
        text: c.status && c.status.model && c.status.model.model ? `当前模型：${c.status.model.model}` : "还没有可用模型",
      }),
    },
    {
      id: "owner",
      title: "设置主人、管理员和白名单",
      desc: "先让机器人认你，再决定她能在哪些群/私聊说话，不然她会完全沉默。",
      points: [
        "在 AstrBot 管理端把自己 QQ 设为管理员/主人",
        "打开响应策略，把你自己加进「允许的私聊」",
        "要让她进群，把群加进「允许的群」",
        "不想限制时，可以关闭白名单",
      ],
      actions: [
        { label: "打开 AstrBot 管理端", kind: "astrbot" },
        { label: "打开响应策略", kind: "tab", tab: "policy" },
      ],
      check: (c) => {
        const p = (c.policy && c.policy.policy) || {};
        const ok = p.whitelist_enabled === false || (p.allowed_private_users || []).length > 0 || (p.allowed_groups || []).length > 0;
        return { ok, text: ok ? "白名单已配置（管理员权限请在 AstrBot 侧确认）" : "白名单还是空的" };
      },
    },
    {
      id: "persona",
      title: "选人设，写核心设定",
      desc: "人设决定她怎么说话，核心设定决定她不能忘什么。两者合起来才是「她」。",
      points: [
        "打开人设页，选一个默认人设",
        "在「核心设定」里写：她是谁、和你的关系、说话铁律、底线",
        "保存后下一条消息生效，不用重启",
        "AI 想改核心设定时，会先提交提议，你点通过才生效",
      ],
      actions: [
        { label: "打开人设页", kind: "tab", tab: "persona" },
      ],
      check: (c) => ({
        ok: !!(c.persona && c.persona.active && c.persona.core_chars > 0),
        text: c.persona && c.persona.active ? `当前人设：${c.persona.active} · 核心设定 ${c.persona.core_chars} 字` : "还没有选中人设",
      }),
    },
    {
      id: "voice",
      title: "语音（可选）",
      desc: "想让她发语音，就接 Breeze TTS 2。不想用可以跳过这一步。",
      points: [
        "打开 BreezeBlue 官网注册，创建 API Key",
        "回到聊天设置 → 语音，把 Key 填进去",
        "上传 3–60 秒干净人声，创建克隆音色",
        "设好语音概率、冷却和每日字符预算",
      ],
      optional: true,
      actions: [
        { label: "Breeze 官网 / API Key", href: "https://breezeblue.ai/app/developer/api-keys" },
        { label: "打开聊天设置", kind: "tab", tab: "behavior" },
      ],
      check: (c) => ({
        ok: !!(c.voice && c.voice.api_key && c.voice.voice_id),
        text: c.voice && c.voice.api_key ? (c.voice.voice_id ? "语音已配置" : "Key 已填，还没选音色") : "还没配置语音",
      }),
    },
    {
      id: "qzone",
      title: "QQ 空间（可选）",
      desc: "想让她自动发说说、看空间动态，就绑定 QQ 空间。不绑定不影响聊天。",
      points: [
        "打开 QQ 空间页，确认 daemon 已启动",
        "按页面提示登录/绑定 QQ 空间",
        "之后可以在聊天设置里控制自动发说说的频率",
      ],
      optional: true,
      actions: [
        { label: "打开 QQ 空间", kind: "tab", tab: "qzone" },
      ],
      check: (c) => {
        const s = (c.qzone && c.qzone.status) || {};
        const ok = s.daemon_state === "ready" && !s.needs_rebind && (s.cookie_count || 0) > 0;
        return { ok, text: ok ? "QQ 空间已就绪" : "QQ 空间未绑定/需要重新登录" };
      },
    },
    {
      id: "backup",
      title: "备份和隐私（建议）",
      desc: "先备份一次，之后换电脑或误删都能恢复；截图分享前可以打开隐私遮罩。",
      points: [
        "点下面「立即备份」，生成第一份备份",
        "备份包含人设、核心设定、配置、插件数据、日记、主数据库",
        "想分享截图时，在运营页打开「隐藏 QQ 号 / 群号」",
        "以后每天启动会自动备份一次，保留最近 7 份",
      ],
      actions: [
        { label: "立即备份", kind: "backup" },
        { label: "打开运营页", kind: "tab", tab: "ops" },
      ],
      check: (c) => ({
        ok: !!(c.backups && c.backups.length > 0),
        text: c.backups && c.backups.length ? `已有 ${c.backups.length} 份备份` : "还没有备份",
      }),
    },
    {
      id: "test",
      title: "第一次试聊",
      desc: "最后一步：用你自己的 QQ 私聊她，发一句「在吗」，看看她回不回、像不像活人。",
      points: [
        "用你的 QQ 私聊机器人账号，发一句「在吗」",
        "如果没回：回运营页看健康自检和白名单",
        "觉得太吵/太安静：调整响应策略和聊天设置",
        "想听声音：在聊天设置里把语音打开",
      ],
      actions: [
        { label: "打开运营页", kind: "tab", tab: "ops" },
      ],
      check: () => ({ ok: true, text: "手动验收" }),
    },
  ];

  function stepStatus(step) {
    try {
      return step.check(GUIDE.checks) || { ok: false, text: "" };
    } catch (e) {
      return { ok: false, text: "检查失败" };
    }
  }

  async function refreshChecks() {
    const out = {};
    try {
      out.status = await api("/api/status");
    } catch (e) {}
    try {
      out.policy = await api("/api/policy");
    } catch (e) {}
    try {
      const ps = await api("/api/personas");
      const list = ps.value || ps || [];
      const active = (list.find((x) => x.active) || list[0] || {}).name;
      if (active) {
        const core = await api(`/api/persona/core?name=${encodeURIComponent(active)}`);
        out.persona = { active, core_chars: (core.core || "").length };
      }
    } catch (e) {}
    try {
      out.voice = (await api("/api/plugins/config?plugin_id=astrbot_plugin_breeze_tts")).config || {};
    } catch (e) {}
    try {
      out.qzone = await api("/api/qzone/status");
    } catch (e) {}
    try {
      out.backups = (await api("/api/ops/backups")).backups || [];
    } catch (e) {}
    GUIDE.checks = out;
  }

  function ensureFab() {
    if (GUIDE.fab) return GUIDE.fab;
    const b = document.createElement("button");
    b.className = "guide-fab";
    b.innerHTML = `<span>🧭</span>继续引导`;
    b.onclick = () => showGuide(true);
    document.body.appendChild(b);
    GUIDE.fab = b;
    return b;
  }

  function hideFab() {
    if (GUIDE.fab) GUIDE.fab.remove();
    GUIDE.fab = null;
  }

  function minimizeGuide() {
    GUIDE.open = false;
    const mask = document.getElementById("guide-mask");
    if (mask) mask.remove();
    ensureFab();
  }

  async function showGuide(force) {
    if (GUIDE.open && !force) return;
    GUIDE.open = true;
    GUIDE.settings = GUIDE.settings || (await api("/api/ops/settings").catch(() => ({})));
    const done = () => api("/api/ops/settings/save", { method: "POST", body: JSON.stringify({ onboarding_done: true, guide_version: 2 }) }).catch(() => {});
    const closeAll = async () => {
      const mask = document.getElementById("guide-mask");
      if (mask) mask.remove();
      GUIDE.open = false;
      hideFab();
      await done();
      toast("引导已完成，之后可在「设置 → 使用引导」再次打开", 5000);
    };
    GUIDE.closeAll = closeAll;
    window.__closeGuide = closeAll;
    await refreshChecks();
    renderGuide();
  }

  function renderGuide() {
    let mask = document.getElementById("guide-mask");
    if (!mask) {
      mask = document.createElement("div");
      mask.id = "guide-mask";
      mask.className = "modal-mask guide-mask";
      document.body.appendChild(mask);
    }
    const step = STEPS[GUIDE.step];
    const st = stepStatus(step);
    const total = STEPS.length;
    const doneCount = STEPS.filter((s) => (s.optional ? true : stepStatus(s).ok)).length;
    const stepChecks = STEPS.map((s, i) => {
      const ok = stepStatus(s).ok;
      return `<button class="guide-step ${i === GUIDE.step ? "active" : ""} ${ok ? "done" : ""}" data-guide-step="${i}">
        <span class="guide-step-num">${ok ? "✓" : i + 1}</span>
        <span class="guide-step-text">${esc(s.title)}${s.optional ? ' <em>可选</em>' : ""}</span>
      </button>`;
    }).join("");

    mask.innerHTML = `<div class="modal-box guide-box">
      <div class="guide-head">
        <div>
          <div class="guide-kicker">第一次养小鲸鱼 · 使用引导</div>
          <div class="guide-progress-text">${GUIDE.step + 1} / ${total} 步 · 建议先完成必做项</div>
        </div>
        <button class="modal-close" id="guide-close">×</button>
      </div>
      <div class="guide-body">
        <aside class="guide-steps">${stepChecks}</aside>
        <section class="guide-content">
          <div class="guide-title">${esc(step.title)} <span class="guide-badge ${st.ok ? "ok" : ""}">${st.ok ? "已完成" : step.optional ? "可选" : "待完成"}</span></div>
          <div class="guide-desc">${esc(step.desc)}</div>
          <ol class="guide-points">${step.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
          <div class="guide-status ${st.ok ? "ok" : ""}">${st.ok ? "✓" : "○"} ${esc(st.text || "")}</div>
          <div class="guide-actions">
            ${step.actions.map((a, i) => `<button class="btn ${i === 0 ? "primary" : ""} small" data-guide-action="${i}">${esc(a.label)}</button>`).join("")}
            <button class="btn small" id="guide-recheck">重新检查</button>
          </div>
        </section>
      </div>
      <div class="guide-foot">
        <button class="btn small" id="guide-skip">跳过引导</button>
        <div class="guide-nav">
          <button class="btn small" id="guide-prev" ${GUIDE.step === 0 ? "disabled" : ""}>上一步</button>
          ${GUIDE.step === STEPS.length - 1
            ? `<button class="btn primary small" id="guide-finish">完成引导</button>`
            : `<button class="btn primary small" id="guide-next">下一步</button>`}
        </div>
      </div>
      <div class="guide-bar"><i style="width:${((GUIDE.step + 1) / total) * 100}%"></i></div>
    </div>`;

    document.getElementById("guide-close").onclick = () => minimizeGuide();
    document.getElementById("guide-skip").onclick = () => (window.__closeGuide ? window.__closeGuide() : GUIDE.closeAll());
    document.getElementById("guide-prev").onclick = () => { if (GUIDE.step > 0) { GUIDE.step--; renderGuide(); } };
    const nextBtn = document.getElementById("guide-next");
    if (nextBtn) nextBtn.onclick = () => { if (GUIDE.step < STEPS.length - 1) { GUIDE.step++; renderGuide(); } };
    const finishBtn = document.getElementById("guide-finish");
    if (finishBtn) finishBtn.onclick = () => (window.__closeGuide ? window.__closeGuide() : GUIDE.closeAll());
    document.getElementById("guide-recheck").onclick = async () => {
      document.getElementById("guide-recheck").textContent = "检查中…";
      await refreshChecks();
      renderGuide();
    };
    document.querySelectorAll("[data-guide-step]").forEach((b) => {
      b.onclick = () => { GUIDE.step = Number(b.dataset.guideStep); renderGuide(); };
    });
    document.querySelectorAll("#guide-mask [data-guide-action]").forEach((b) => {
      b.onclick = async () => {
        const a = step.actions[Number(b.dataset.guideAction)];
        if (!a) return;
        if (a.href) window.open(a.href, "_blank");
        else if (a.kind === "tab") {
          minimizeGuide();
          switchTab(a.tab);
        } else if (a.kind === "astrbot") {
          const s = GUIDE.checks.status || {};
          window.open((s.astrbot && s.astrbot.webui) || "http://127.0.0.1:6185", "_blank");
        } else if (a.kind === "status") {
          const s = GUIDE.checks.status || {};
          window.open((s.napcat && s.napcat.webui_url) || "http://127.0.0.1:6099/webui", "_blank");
        } else if (a.kind === "backup") {
          b.disabled = true;
          b.textContent = "备份中…";
          const r = await api("/api/ops/backup", { method: "POST", body: JSON.stringify({ label: "first-guide" }) }).catch((e) => ({ ok: false, error: e.message }));
          toast(r.ok ? "备份完成" : r.error || "备份失败", 5000);
          await refreshChecks();
          renderGuide();
        }
      };
    });
  }

  async function autoStart() {
    try {
      const st = await api("/api/ops/settings");
      GUIDE.settings = st;
      if ((st.guide_version || 1) < 2) {
        setTimeout(() => showGuide(true), 600);
      }
    } catch (e) {}
  }

  document.addEventListener("DOMContentLoaded", () => {
    autoStart();
    const btn = document.getElementById("btn-open-guide");
    if (btn) btn.onclick = () => showGuide(true);
  });

  window.showGuide = showGuide;
})();
