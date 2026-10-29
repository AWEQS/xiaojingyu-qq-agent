/* 记忆星图：事实 → 星座 → 篇章 */
(function () {
  if (window.__starmapLoaded) return;
  window.__starmapLoaded = true;

  const SM = {
    graph: null,
    selected: null,
    rot: { yaw: 0.65, pitch: 0.22 },
    zoom: 1,
    auto: true,
    spin: 1,
    resumeAt: 0,
    lastFrame: 0,
    drag: null,
    hover: null,
    screen: [],
    raf: 0,
    ro: null,
  };

  function fmt(n) {
    return Number(n || 0).toLocaleString("zh-CN");
  }

  async function loadStarmap() {
    const root = document.getElementById("starmap-root");
    if (!root) return;
    root.innerHTML = `<div class="card"><p class="hint">正在展开星图…</p></div>`;
    try {
      const [graph, settings, sagas] = await Promise.all([
        api("/api/starmap/graph"),
        api("/api/starmap/settings").catch(() => ({})),
        api("/api/starmap/sagas").catch(() => ({ sagas: [] })),
      ]);
      SM.graph = graph;
      SM.settings = settings || {};
      SM.sagas = (sagas && sagas.sagas) || [];
      renderStarmap();
    } catch (e) {
      root.innerHTML = `<div class="card"><p class="hint">读取失败：${esc(e.message)}</p></div>`;
    }
  }

  function renderStarmap() {
    const root = document.getElementById("starmap-root");
    if (!root) return;
    const g = SM.graph || {};
    const stats = g.stats || {};
    root.innerHTML = `
      <div class="sm-root">
        <div class="sm-hero">
          <div>
            <div class="sm-title">记忆星图</div>
            <div class="sm-sub">把散落的事实连成星座，再拼成你们的故事。每条记忆都能回到原话。</div>
            <div class="sm-stats">
              <span class="sm-stat">星座 <b>${fmt(stats.constellations)}</b></span>
              <span class="sm-stat">记忆 <b>${fmt(stats.approved)}</b></span>
              <span class="sm-stat">待审核 <b>${fmt(stats.pending)}</b></span>
              <span class="sm-stat">篇章 <b>${fmt(stats.episodes)}</b></span>
              <span class="sm-stat">上次抽取 <b>${esc(stats.last_extract || "还没抽过")}</b></span>
            </div>
          </div>
          <div class="sm-actions">
            <button class="btn small primary" id="sm-extract">抽取新记忆</button>
            <button class="btn small" id="sm-auto">自动抽取：${SM.settings && SM.settings.auto ? "开" : "关"}</button>
            <button class="btn small" id="sm-entities">实体合并</button>
            <button class="btn small" id="sm-semantic">语义检索</button>
            <button class="btn small" id="sm-saga-generate">生成长弧线</button>
            <button class="btn small" id="sm-seed">从核心设定初始化</button>
            <button class="btn small" id="sm-refresh">刷新</button>
          </div>
        </div>
        <div class="sm-layout">
          <div class="card sm-canvas-card" id="sm-canvas-card">
            <div class="card-head sm-canvas-head">
              <div class="sm-canvas-title">
                <h3>星图</h3>
                <span class="hint">拖拽旋转 · 滚轮缩放 · 悬停看名称 · 点击星点看来源 · 双击空白全屏</span>
              </div>
              <div class="sm-view-actions">
                <button class="btn small" id="sm-auto-rotate">自转：开</button>
                <button class="btn small" id="sm-focus">聚焦</button>
                <button class="btn small" id="sm-side-toggle">侧栏</button>
                <button class="btn small" id="sm-fullscreen">全屏</button>
              </div>
            </div>
            <div class="sm-hud sm-hud-tl">SECTOR 07 // MEMORY GRID<br>LINK STATUS: STABLE</div>
            <div class="sm-hud sm-hud-tr">STAR-NET // 0x7E<br>SYNC ONLINE</div>
            <div class="sm-hud sm-hud-bl">ORBIT 1.02 AU // GRAVITY LOCKED</div>
            <div class="sm-zoom">
              <button id="sm-zoom-in">＋</button>
              <button id="sm-zoom-out">－</button>
              <button id="sm-zoom-reset">⌂</button>
            </div>
            <div class="sm-canvas-wrap"><canvas id="sm-canvas"></canvas></div>
            <div class="sm-legend" id="sm-legend"></div>
          </div>
          <div class="sm-side">
            <div class="card">
              <div class="sm-side-title"><span>待审核</span><span class="plugin-badge">${(g.pending || []).length}</span></div>
              <div id="sm-pending"></div>
            </div>
            <div class="card">
              <div class="sm-side-title"><span>篇章</span><span class="plugin-badge">${(g.episodes || []).length}</span></div>
              <div id="sm-episodes"></div>
            </div>
            <div class="card">
              <div class="sm-side-title"><span>长弧线</span><span class="plugin-badge">${(SM.sagas || []).length}</span></div>
              <div id="sm-sagas"></div>
            </div>
            <div class="card">
              <div class="sm-side-title"><span>记忆详情</span></div>
              <div id="sm-detail"><p class="sm-detail-empty">点一颗星星，看它来自哪句话。</p></div>
            </div>
          </div>
        </div>
      </div>`;

    document.getElementById("sm-extract").onclick = extractNow;
    document.getElementById("sm-auto").onclick = toggleAuto;
    document.getElementById("sm-entities").onclick = openEntityModal;
    document.getElementById("sm-semantic").onclick = openSemanticModal;
    document.getElementById("sm-saga-generate").onclick = generateSaga;
    document.getElementById("sm-seed").onclick = seedCore;
    document.getElementById("sm-refresh").onclick = loadStarmap;
    document.getElementById("sm-zoom-in").onclick = () => zoomBy(1.2);
    document.getElementById("sm-zoom-out").onclick = () => zoomBy(0.82);
    document.getElementById("sm-zoom-reset").onclick = resetView;
    document.getElementById("sm-auto-rotate").onclick = toggleAutoRotate;
    document.getElementById("sm-focus").onclick = resetView;
    document.getElementById("sm-side-toggle").onclick = toggleSidebar;
    document.getElementById("sm-fullscreen").onclick = toggleFullscreen;
    renderPending();
    renderEpisodes();
    renderSagas();
    renderLegend();
    setupStarCanvas();
  }

  function renderLegend() {
    const box = document.getElementById("sm-legend");
    if (!box) return;
    const cons = SM.graph.constellations || [];
    box.innerHTML = cons
      .map((c) => `<span><i style="background:#d8ecff;box-shadow:0 0 7px rgba(170,220,255,.8)"></i>${esc(c.name)}</span>`)
      .join("");
  }

  function renderPending() {
    const box = document.getElementById("sm-pending");
    if (!box) return;
    const items = (SM.graph && SM.graph.pending) || [];
    if (!items.length) {
      box.innerHTML = `<p class="hint">没有待审核的记忆</p>`;
      return;
    }
    box.innerHTML = items
      .map(
        (c) => `<div class="sm-pending-item">
          <div class="sm-pending-text"><em>${esc(c.subject)}</em> ${esc(c.predicate)} ${esc(c.object)}</div>
          ${c.quote ? `<div class="sm-pending-quote">“${esc(c.quote)}”</div>` : ""}
          <div class="sm-pending-foot">
            <span class="hint">${esc(c.category || "")} · ${Math.round((c.confidence || 0) * 100)}%</span>
            <span class="sm-mini-actions">
              <button class="btn small primary" data-sm-approve="${c.id}">通过</button>
              <button class="btn small" data-sm-reject="${c.id}">忽略</button>
            </span>
          </div>
        </div>`
      )
      .join("");
    box.querySelectorAll("[data-sm-approve]").forEach((b) => (b.onclick = () => decide(b.dataset.smApprove, true)));
    box.querySelectorAll("[data-sm-reject]").forEach((b) => (b.onclick = () => decide(b.dataset.smReject, false)));
  }

  function renderEpisodes() {
    const box = document.getElementById("sm-episodes");
    if (!box) return;
    const items = (SM.graph && SM.graph.episodes) || [];
    if (!items.length) {
      box.innerHTML = `<p class="hint">还没有篇章，审核几条记忆后会自动成篇</p>`;
      return;
    }
    box.innerHTML = items
      .map(
        (e) => `<div class="sm-episode-item" data-sm-episode="${e.id}">
          <div class="sm-episode-title">${esc(e.title || e.date)}</div>
          <div class="sm-episode-meta">${(e.claim_ids || []).length} 条记忆 · ${esc(e.date || "")}</div>
          ${e.summary ? `<div class="sm-episode-summary">${esc(String(e.summary).slice(0, 90))}</div>` : ""}
        </div>`
      )
      .join("");
    box.querySelectorAll("[data-sm-episode]").forEach((el) => {
      el.onclick = () => {
        const ep = items.find((x) => String(x.id) === el.dataset.smEpisode);
        if (!ep) return;
        SM.selected = null;
        document.getElementById("sm-detail").innerHTML = `<div class="sm-detail">
          <div class="sm-detail-title">${esc(ep.title || ep.date)}</div>
          ${ep.summary ? `<div class="sm-detail-quote">${esc(ep.summary)}</div>` : `<div class="sm-detail-row">还没有篇章摘要</div>`}
          <div class="sm-detail-row">篇章包含 ${(ep.claim_ids || []).length} 条记忆</div>
          <div class="sm-detail-row">${(ep.claim_ids || []).map((id) => {
            const c = (SM.graph.claims || []).find((x) => Number(x.id) === Number(id));
            return c ? `· ${esc(c.subject)} ${esc(c.predicate)} ${esc(c.object)}` : "";
          }).join("<br>")}</div>
          <button class="btn small" id="sm-summary-btn" style="margin-top:8px">${ep.summary ? "重新生成摘要" : "生成篇章摘要"}</button>
        </div>`;
        const sb = document.getElementById("sm-summary-btn");
        if (sb) sb.onclick = () => summarizeEpisode(ep.id);
      };
    });
  }

  function pseudo(n) {
    const x = Math.sin(n * 12.9898) * 43758.5453;
    return x - Math.floor(x);
  }

  function buildLayout() {
    if (SM.layoutGraph === SM.graph && SM.nodes) return;
    const claims = (SM.graph && SM.graph.claims) || [];
    const cons = (SM.graph && SM.graph.constellations) || [];
    const centers = new Map();
    cons.forEach((c, i) => {
      const n = Math.max(1, cons.length);
      const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
      centers.set(String(c.id), {
        x: Math.cos(angle) * 300 + (pseudo(i + 2) - 0.5) * 70,
        y: Math.sin(angle) * 190 + (pseudo(i + 5) - 0.5) * 60,
        z: Math.sin(angle * 1.6 + i) * 260,
      });
    });
    const grouped = new Map();
    claims.forEach((c) => {
      const key = String(c.constellation_id || 0);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(c);
    });
    const nodes = [];
    claims.forEach((c) => {
      const key = String(c.constellation_id || 0);
      const list = grouped.get(key) || [];
      const idx = Math.max(0, list.findIndex((x) => Number(x.id) === Number(c.id)));
      const center = centers.get(key) || { x: 0, y: 0, z: 0 };
      const a = idx * 2.399963 + (Number(c.id) % 9) * 0.21;
      const r = 46 + (idx % 4) * 24 + Math.floor(idx / 7) * 34;
      nodes.push({
        id: Number(c.id),
        claim: c,
        x: center.x + Math.cos(a) * r,
        y: center.y + Math.sin(a) * r * 0.72,
        z: center.z + Math.sin(a * 1.55) * r * 0.9 + (pseudo(Number(c.id) + 11) - 0.5) * 18,
      });
    });
    SM.nodes = nodes;
    SM.centers = cons.map((c) => ({ ...c, ...(centers.get(String(c.id)) || { x: 0, y: 0, z: 0 }) }));
    SM.stars = Array.from({ length: 360 }, (_, i) => {
      const seed = i * 3 + 1;
      return {
        x: (pseudo(seed) * 2 - 1) * 820,
        y: (pseudo(seed + 1) * 2 - 1) * 620,
        z: (pseudo(seed + 2) * 2 - 1) * 760,
        b: 0.18 + pseudo(seed + 3) * 0.82,
        r: 0.45 + pseudo(seed + 4) * 1.15,
      };
    });
    SM.layoutGraph = SM.graph;
  }

  function projectPoint(p) {
    const cy = Math.cos(SM.rot.yaw);
    const sy = Math.sin(SM.rot.yaw);
    const cp = Math.cos(SM.rot.pitch);
    const sp = Math.sin(SM.rot.pitch);
    const x1 = p.x * cy + p.z * sy;
    const z1 = -p.x * sy + p.z * cy;
    const y1 = p.y * cp - z1 * sp;
    const z2 = p.y * sp + z1 * cp;
    const f = 1600 / (1600 + z2);
    const scale = Math.min(SM.cw, SM.ch) / 900;
    const depthA = Math.max(0.2, Math.min(1, 0.3 + (700 - z2) / 1200));
    return {
      x: SM.cw / 2 + x1 * f * SM.zoom * scale,
      y: SM.ch / 2 + y1 * f * SM.zoom * scale,
      z: z2,
      f,
      a: depthA,
    };
  }

  function nodeAt(x, y) {
    let best = null;
    for (const n of SM.screen) {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d <= Math.max(11, n.r + 8) && (!best || d < best.d)) best = { ...n, d };
    }
    return best;
  }

  function setupStarCanvas() {
    const canvas = document.getElementById("sm-canvas");
    if (!canvas) return;
    if (SM.raf) cancelAnimationFrame(SM.raf);
    SM.raf = 0;
    if (SM.ro) SM.ro.disconnect();
    SM.canvas = canvas;
    SM.ctx = canvas.getContext("2d");
    const wrap = canvas.parentElement;
    const resize = () => {
      if (!SM.canvas || !SM.ctx) return;
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, rect.width);
      const h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      SM.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      SM.cw = w;
      SM.ch = h;
    };
    resize();
    SM.ro = new ResizeObserver(resize);
    SM.ro.observe(wrap);
    bindStarEvents(canvas);
    buildLayout();
    const loop = (t) => {
      if (!SM.canvas || !SM.canvas.isConnected) {
        SM.raf = 0;
        return;
      }
      const now = performance.now();
      const dt = SM.lastFrame ? Math.min(0.05, (t - SM.lastFrame) / 1000) : 0;
      SM.lastFrame = t;
      if (!SM.drag) {
        if (SM.auto && !document.hidden) {
          SM.spin = Math.min(1, (SM.spin || 0) + dt / 2.2);
          SM.rot.yaw += 0.11 * SM.spin * dt;
        }
      }
      drawStarCanvas();
      SM.raf = requestAnimationFrame(loop);
    };
    SM.raf = requestAnimationFrame(loop);
  }

  function drawStarCanvas() {
    const ctx = SM.ctx;
    if (!ctx) return;
    const w = SM.cw;
    const h = SM.ch;
    ctx.clearRect(0, 0, w, h);
    const bg = ctx.createRadialGradient(w * 0.36, h * 0.32, 0, w * 0.5, h * 0.5, Math.max(w, h) * 0.85);
    bg.addColorStop(0, "#0a1626");
    bg.addColorStop(0.45, "#050a14");
    bg.addColorStop(1, "#01030a");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    for (const s of SM.stars) {
      const p = projectPoint(s);
      if (p.x < -10 || p.x > w + 10 || p.y < -10 || p.y > h + 10) continue;
      ctx.globalAlpha = s.b * p.a * 0.9;
      ctx.fillStyle = "#dbe9ff";
      ctx.beginPath();
      ctx.arc(p.x, p.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    buildLayout();
    const nodeMap = new Map(SM.nodes.map((n) => [n.id, n]));

    const links = (SM.graph && SM.graph.links) || [];
    ctx.lineWidth = 0.9;
    ctx.setLineDash([2, 5]);
    for (const l of links) {
      const a = nodeMap.get(Number(l.source));
      const b = nodeMap.get(Number(l.target));
      if (!a || !b) continue;
      const pa = projectPoint(a);
      const pb = projectPoint(b);
      ctx.globalAlpha = 0.34 * Math.min(pa.a, pb.a);
      ctx.strokeStyle = "#b8d8ff";
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    const groups = new Map();
    for (const n of SM.nodes) {
      const key = String(n.claim.constellation_id || 0);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    }
    ctx.setLineDash([1, 6]);
    for (const list of groups.values()) {
      if (list.length < 2) continue;
      const sorted = list.slice().sort((a, b) => Math.atan2(a.z, a.x) - Math.atan2(b.z, b.x));
      for (let i = 0; i < sorted.length; i++) {
        const a = sorted[i];
        const b = sorted[(i + 1) % sorted.length];
        const pa = projectPoint(a);
        const pb = projectPoint(b);
        ctx.globalAlpha = 0.18 * Math.min(pa.a, pb.a);
        ctx.strokeStyle = "#9fc4ff";
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);

    for (const c of SM.centers) {
      const p = projectPoint(c);
      const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 120);
      glow.addColorStop(0, "rgba(160,210,255,.10)");
      glow.addColorStop(1, "rgba(160,210,255,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.fillRect(p.x - 120, p.y - 120, 240, 240);
      ctx.globalAlpha = 0.30 * p.a;
      ctx.fillStyle = "#cfe6ff";
      ctx.font = "11px 'Cascadia Code', Consolas, monospace";
      ctx.textAlign = "center";
      ctx.fillText(String(c.name || ""), p.x, p.y - 8);
    }

    const projected = SM.nodes.map((n) => ({ n, p: projectPoint(n) }));
    projected.sort((a, b) => b.p.z - a.p.z);
    SM.screen = [];
    for (const { n, p } of projected) {
      if (p.x < -40 || p.x > w + 40 || p.y < -40 || p.y > h + 40) continue;
      const selected = SM.selected === n.id;
      const hover = SM.hover === n.id;
      const r = selected ? 3.8 : hover ? 3.1 : 2.2;
      SM.screen.push({ id: n.id, x: p.x, y: p.y, r });
      ctx.globalAlpha = p.a * (selected || hover ? 1 : 0.9);
      ctx.shadowBlur = selected ? 24 : hover ? 16 : 9;
      ctx.shadowColor = selected ? "rgba(120,230,255,.95)" : "rgba(170,215,255,.8)";
      ctx.fillStyle = selected ? "#bff4ff" : "#eef7ff";
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      if (selected) {
        ctx.globalAlpha = 0.75;
        ctx.strokeStyle = "rgba(120,230,255,.8)";
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 10, 0, Math.PI * 2);
        ctx.stroke();
      }
      if (selected || hover) {
        const c = n.claim;
        const label = String(c.object || c.predicate || "").slice(0, 16);
        ctx.globalAlpha = selected ? 0.98 : 0.9;
        ctx.fillStyle = selected ? "#dff9ff" : "#d4e9ff";
        ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(label, p.x + 9, p.y + 4);
      }
    }
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }

  function resetView() {
    SM.rot = { yaw: 0.65, pitch: 0.22 };
    SM.zoom = 1;
    SM.auto = true;
    SM.spin = 1;
    SM.resumeAt = 0;
    const btn = document.getElementById("sm-auto-rotate");
    if (btn) btn.textContent = "自转：开";
    drawStarCanvas();
  }

  function toggleAutoRotate() {
    SM.auto = !SM.auto;
    SM.spin = SM.auto ? 1 : 0;
    SM.resumeAt = 0;
    const btn = document.getElementById("sm-auto-rotate");
    if (btn) btn.textContent = "自转：" + (SM.auto ? "开" : "关");
  }

  function toggleSidebar() {
    const layout = document.querySelector(".sm-layout");
    if (!layout) return;
    layout.classList.toggle("side-hidden");
    const btn = document.getElementById("sm-side-toggle");
    if (btn) btn.textContent = layout.classList.contains("side-hidden") ? "显示侧栏" : "侧栏";
  }

  function setPseudoFullscreen(on) {
    const card = document.getElementById("sm-canvas-card");
    if (!card) return;
    card.classList.toggle("sm-pseudo-fullscreen", on);
    const btn = document.getElementById("sm-fullscreen");
    if (btn) btn.textContent = on ? "退出全屏" : "全屏";
    setTimeout(() => {
      const canvas = document.getElementById("sm-canvas");
      if (canvas && SM.ro) {
        SM.ro.disconnect();
        SM.ro.observe(canvas.parentElement);
      }
    }, 80);
  }

  function toggleFullscreen() {
    const card = document.getElementById("sm-canvas-card");
    if (!card) return;
    if (card.classList.contains("sm-pseudo-fullscreen")) {
      setPseudoFullscreen(false);
      return;
    }
    if (document.fullscreenElement) {
      document.exitFullscreen?.().catch(() => {});
      return;
    }
    if (card.requestFullscreen) {
      card.requestFullscreen().catch(() => setPseudoFullscreen(true));
    } else {
      setPseudoFullscreen(true);
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const card = document.getElementById("sm-canvas-card");
      if (card && card.classList.contains("sm-pseudo-fullscreen")) setPseudoFullscreen(false);
    }
  });

  document.addEventListener("fullscreenchange", () => {
    const btn = document.getElementById("sm-fullscreen");
    if (btn) btn.textContent = document.fullscreenElement ? "退出全屏" : "全屏";
    setTimeout(() => {
      const canvas = document.getElementById("sm-canvas");
      if (canvas && SM.ro) {
        SM.ro.disconnect();
        SM.ro.observe(canvas.parentElement);
      }
    }, 80);
  });

  function showDetail(id) {
    const c = (SM.graph.claims || []).find((x) => Number(x.id) === Number(id));
    const box = document.getElementById("sm-detail");
    if (!c || !box) return;
    const ep = (SM.graph.episodes || []).find((e) => Number(e.id) === Number(c.episode_id));
    box.innerHTML = `<div class="sm-detail">
      <div class="sm-detail-title">${esc(c.subject)} ${esc(c.predicate)} ${esc(c.object)}</div>
      <div class="sm-detail-row">${esc(c.category || "")} · 置信度 ${Math.round((c.confidence || 0) * 100)}% · ${esc(c.date || "")}</div>
      ${c.quote ? `<div class="sm-detail-quote">“${esc(c.quote)}”</div>` : ""}
      <div class="sm-detail-row">${ep ? "属于篇章：" + esc(ep.title) : "还没有归入篇章"}</div>
      <button class="btn small" id="sm-unapprove" style="margin-top:8px">撤销通过</button>
    </div>`;
    const ub = document.getElementById("sm-unapprove");
    if (ub) ub.onclick = async () => {
      const ok = await modalConfirm({ title: "撤销通过", message: "把这条记忆退回待审核？", okText: "撤销通过" });
      if (!ok) return;
      const r = await api("/api/starmap/unapprove", { method: "POST", body: JSON.stringify({ id: Number(c.id) }) });
      if (!r.ok) return toast(r.error || "撤销失败", 5000);
      toast("已退回待审核");
      await loadStarmap();
    };
  }

  function bindStarEvents(canvas) {
    if (canvas._smBound) return;
    canvas._smBound = true;
    const point = (e) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      canvas.setPointerCapture?.(e.pointerId);
      const p = point(e);
      SM.drag = { x: p.x, y: p.y, yaw: SM.rot.yaw, pitch: SM.rot.pitch, moved: 0 };
      SM.spin = 0;
      SM.resumeAt = 0;
      canvas.style.cursor = "grabbing";
    });
    canvas.addEventListener("pointermove", (e) => {
      const p = point(e);
      if (SM.drag) {
        const dx = p.x - SM.drag.x;
        const dy = p.y - SM.drag.y;
        SM.drag.moved = Math.max(SM.drag.moved, Math.hypot(dx, dy));
        SM.rot.yaw = SM.drag.yaw - dx * 0.006;
        SM.rot.pitch = Math.max(-1.15, Math.min(1.15, SM.drag.pitch + dy * 0.0045));
        drawStarCanvas();
        return;
      }
      const n = nodeAt(p.x, p.y);
      SM.hover = n ? n.id : null;
      canvas.style.cursor = n ? "pointer" : "grab";
    });
    const endDrag = (e) => {
      if (!SM.drag) return;
      const p = point(e);
      const moved = Math.hypot(p.x - SM.drag.x, p.y - SM.drag.y);
      const wasClick = moved < 6 && SM.drag.moved < 6;
      SM.drag = null;
      canvas.style.cursor = "grab";
      if (!wasClick) {
        SM.spin = 1 / 3;
        SM.resumeAt = 0;
        return;
      }
      const n = nodeAt(p.x, p.y);
      if (n) {
        SM.selected = n.id;
        showDetail(n.id);
        const layout = document.querySelector(".sm-layout");
        if (layout && layout.classList.contains("side-hidden")) toggleSidebar();
      } else {
        SM.selected = null;
      }
      drawStarCanvas();
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", () => {
      SM.drag = null;
      canvas.style.cursor = "grab";
    });
    canvas.addEventListener("pointerleave", () => {
      if (!SM.drag) SM.hover = null;
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      zoomBy(e.deltaY > 0 ? 0.9 : 1.1);
    }, { passive: false });
    canvas.addEventListener("dblclick", (e) => {
      const p = point(e);
      if (nodeAt(p.x, p.y)) return;
      e.preventDefault();
      toggleFullscreen();
    });
  }

  function zoomBy(scale) {
    SM.zoom = Math.max(0.42, Math.min(3.2, SM.zoom * scale));
    drawStarCanvas();
  }

  async function decide(id, approve) {
    try {
      const r = await api("/api/starmap/decision", {
        method: "POST",
        body: JSON.stringify({ id: Number(id), approve, auto_summary: approve }),
      });
      if (!r.ok) return toast(r.error || "操作失败", 4000);
      toast(approve ? "已点亮一颗星" : "已忽略");
      await loadStarmap();
    } catch (e) {
      toast("操作失败：" + e.message, 4000);
    }
  }

  async function extractNow() {
    const btn = document.getElementById("sm-extract");
    btn.disabled = true;
    btn.textContent = "抽取中…";
    try {
      const r = await api("/api/starmap/extract", { method: "POST", body: JSON.stringify({ limit: 60 }) });
      if (!r.ok) toast(r.error || "抽取失败", 6000);
      else toast(r.added ? `抽到 ${r.added} 条待审核记忆` : r.message || "没有新记忆", 5000);
      await loadStarmap();
    } catch (e) {
      toast("抽取失败：" + e.message, 6000);
    } finally {
      btn.disabled = false;
      btn.textContent = "抽取新记忆";
    }
  }

  async function seedCore() {
    try {
      const r = await api("/api/starmap/seed", { method: "POST", body: JSON.stringify({}) });
      toast(r.ok ? `从核心设定点亮 ${r.added} 颗星` : r.error || "初始化失败", 5000);
      await loadStarmap();
    } catch (e) {
      toast("初始化失败：" + e.message, 5000);
    }
  }

  async function openEntityModal() {
    let data;
    try {
      data = await api("/api/starmap/entities");
    } catch (e) {
      return toast("读取实体失败：" + e.message, 5000);
    }
    const subjects = data.subjects || [];
    const aliases = data.aliases || [];
    const history = data.history || [];
    const suggestions = data.suggestions || [];
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.id = "sm-entity-mask";
    const options = subjects.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}（${x.n}）</option>`).join("");
    mask.innerHTML = `<div class="modal-box sm-entity-box">
      <div class="modal-head"><div class="modal-title">实体合并</div><button class="modal-close" id="sm-entity-close">×</button></div>
      <div class="modal-body">
        <p class="hint">把同一个人的不同叫法并成一个名字。合并后历史记忆会一起改；如果合错，可以在下方「合并记录」里撤销。</p>
        <div class="sm-entity-suggest">
          ${suggestions.length ? suggestions.map((x) => `<div class="sm-entity-suggest-row"><span>${esc(x.a)} ≈ ${esc(x.b)}</span><span class="sm-mini-actions"><button class="btn small" data-sm-merge="${esc(x.a)}|${esc(x.b)}">${esc(x.a)} → ${esc(x.b)}</button><button class="btn small" data-sm-merge="${esc(x.b)}|${esc(x.a)}">${esc(x.b)} → ${esc(x.a)}</button></span></div>`).join("") : `<p class="hint">没有自动候选，可以手动合并。</p>`}
        </div>
        <div class="sm-entity-form">
          <label>别名（要被合并掉的名字）<input id="sm-alias" list="sm-entity-names" placeholder="例如：鲸鱼娘" /></label>
          <label>正式名（保留的名字）<select id="sm-canonical">${options}</select></label>
        </div>
        <datalist id="sm-entity-names">${options}</datalist>
        <div class="sm-entity-aliases">
          <b>已有别名</b>
          ${aliases.length ? aliases.map((a) => `<span class="sm-alias-chip">${esc(a.alias)} → ${esc(a.canonical)}</span>`).join("") : `<span class="hint">还没有</span>`}
        </div>
        <div class="sm-entity-history">
          <b>合并记录</b>
          ${history.length ? history.map((h) => `<div class="sm-entity-history-row"><span>${esc(h.alias)} → ${esc(h.canonical)} · ${h.changed} 条</span><button class="btn small" data-sm-undo="${h.id}">撤销</button></div>`).join("") : `<span class="hint">还没有合并记录</span>`}
        </div>
        <div class="sm-entity-foot">
          <button class="btn small" id="sm-entity-cancel">取消</button>
          <button class="btn primary small" id="sm-entity-merge">合并</button>
        </div>
      </div>
    </div>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    document.getElementById("sm-entity-close").onclick = close;
    document.getElementById("sm-entity-cancel").onclick = close;
    mask.addEventListener("click", (e) => { if (e.target === mask) close(); });
    const doMerge = async (alias, canonical) => {
      if (!alias || !canonical || alias === canonical) return toast("别名和正式名要不同");
      const btn = document.getElementById("sm-entity-merge");
      if (btn) btn.disabled = true;
      try {
        const r = await api("/api/starmap/alias/merge", {
          method: "POST",
          body: JSON.stringify({ alias, canonical }),
        });
        if (!r.ok) return toast(r.error || "合并失败", 5000);
        toast(`已把「${alias}」并入「${canonical}」，影响 ${r.changed} 条记忆`, 4000);
        close();
        await loadStarmap();
      } catch (e) {
        toast("合并失败：" + e.message, 5000);
      }
    };
    mask.querySelectorAll("[data-sm-merge]").forEach((b) => {
      b.onclick = () => {
        const [a, c] = b.dataset.smMerge.split("|");
        doMerge(a, c);
      };
    });
    document.getElementById("sm-entity-merge").onclick = () => {
      doMerge(
        document.getElementById("sm-alias").value.trim(),
        document.getElementById("sm-canonical").value.trim()
      );
    };
    mask.querySelectorAll("[data-sm-undo]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        try {
          const r = await api("/api/starmap/alias/undo", {
            method: "POST",
            body: JSON.stringify({ id: Number(b.dataset.smUndo) }),
          });
          if (!r.ok) return toast(r.error || "撤销失败", 5000);
          toast("已撤销这次合并");
          close();
          await loadStarmap();
        } catch (e) {
          toast("撤销失败：" + e.message, 5000);
        }
      };
    });
  }


  function renderSagas() {
    const box = document.getElementById("sm-sagas");
    if (!box) return;
    const items = SM.sagas || [];
    if (!items.length) {
      box.innerHTML = `<p class="hint">还没有长弧线，点顶部「生成长弧线」</p>`;
      return;
    }
    box.innerHTML = items
      .map(
        (x) => `<div class="sm-episode-item" data-sm-saga="${x.id}">
          <div class="sm-episode-title">${esc(x.title || "")}</div>
          <div class="sm-episode-meta">${(x.episode_ids || []).length} 篇 · ${esc(x.start_date || "")} ~ ${esc(x.end_date || "")}</div>
          <div class="sm-episode-summary">${esc(String(x.summary || "").slice(0, 100))}</div>
        </div>`
      )
      .join("");
    box.querySelectorAll("[data-sm-saga]").forEach((el) => {
      el.onclick = () => {
        const saga = items.find((x) => String(x.id) === el.dataset.smSaga);
        if (!saga) return;
        document.getElementById("sm-detail").innerHTML = `<div class="sm-detail">
          <div class="sm-detail-title">${esc(saga.title || "")}</div>
          <div class="sm-detail-quote">${esc(saga.summary || "")}</div>
          <div class="sm-detail-row">跨越 ${esc(saga.start_date || "")} ~ ${esc(saga.end_date || "")}</div>
        </div>`;
      };
    });
  }

  async function generateSaga() {
    const btn = document.getElementById("sm-saga-generate");
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const r = await api("/api/starmap/saga/generate", { method: "POST", body: JSON.stringify({}) });
      if (!r.ok) toast(r.error || "生成失败", 6000);
      else toast(`已生成 ${r.sagas || 0} 条长弧线`, 4000);
      await loadStarmap();
    } catch (e) {
      toast("生成失败：" + e.message, 6000);
    } finally {
      btn.disabled = false;
      btn.textContent = "生成长弧线";
    }
  }

  async function openSemanticModal() {
    let cfg = {};
    try {
      cfg = (await api("/api/plugins/config?plugin_id=astrbot_plugin_memory_starmap")).config || {};
    } catch (e) {}
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.id = "sm-semantic-mask";
    mask.innerHTML = `<div class="modal-box sm-entity-box">
      <div class="modal-head"><div class="modal-title">语义检索设置</div><button class="modal-close" id="sm-semantic-close">×</button></div>
      <div class="modal-body">
        <p class="hint">默认用本地 BGE 语义模型；也可以切外部 OpenAI 兼容 embedding，或回退本地词形向量。</p>
        <div class="sm-entity-form">
          <label>模式
            <select id="sm-emb-mode">
              <option value="fastembed" ${cfg.embedding_mode === "fastembed" ? "selected" : ""}>本地 fastembed 语义</option>
              <option value="local" ${cfg.embedding_mode !== "api" && cfg.embedding_mode !== "fastembed" ? "selected" : ""}>本地词形向量（备用）</option>
              <option value="api" ${cfg.embedding_mode === "api" ? "selected" : ""}>外部 embedding API</option>
            </select>
          </label>
          <label>fastembed 模型<input id="sm-emb-fastmodel" value="${esc(cfg.fastembed_model || "BAAI/bge-small-zh-v1.5")}" placeholder="BAAI/bge-small-zh-v1.5" /></label>
          <label>外部模型名<input id="sm-emb-model" value="${esc(cfg.embedding_model || "")}" placeholder="例如 BAAI/bge-m3" /></label>
          <label>接口地址<input id="sm-emb-base" value="${esc(cfg.embedding_base || "")}" placeholder="https://api.siliconflow.cn/v1" /></label>
          <label>API Key<input id="sm-emb-key" type="password" value="${esc(cfg.embedding_key || "")}" placeholder="sk-..." /></label>
          <label>语义权重（0.3–0.95）<input id="sm-emb-weight" type="number" step="0.05" min="0.3" max="0.95" value="${esc(String(cfg.semantic_weight ?? 0.8))}" /></label>
        </div>
        <p class="hint" style="margin-top:10px">默认本地 BGE 语义模型，不联网；外部接口失败会自动回退。</p>
        <div class="sm-entity-foot">
          <button class="btn small" id="sm-semantic-cancel">取消</button>
          <button class="btn primary small" id="sm-semantic-save">保存</button>
        </div>
      </div>
    </div>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    document.getElementById("sm-semantic-close").onclick = close;
    document.getElementById("sm-semantic-cancel").onclick = close;
    mask.addEventListener("click", (e) => { if (e.target === mask) close(); });
    document.getElementById("sm-semantic-save").onclick = async () => {
      const next = {
        ...cfg,
        embedding_mode: document.getElementById("sm-emb-mode").value,
        fastembed_model: document.getElementById("sm-emb-fastmodel").value.trim(),
        embedding_model: document.getElementById("sm-emb-model").value.trim(),
        semantic_weight: Number(document.getElementById("sm-emb-weight").value || 0.8),
        embedding_base: document.getElementById("sm-emb-base").value.trim(),
        embedding_key: document.getElementById("sm-emb-key").value.trim(),
      };
      try {
        const r = await api("/api/plugins/config/save", {
          method: "POST",
          body: JSON.stringify({ plugin_id: "astrbot_plugin_memory_starmap", config: next }),
        });
        if (!r.ok) return toast(r.error || "保存失败", 5000);
        toast("语义检索设置已保存，插件已重载");
        close();
      } catch (e) {
        toast("保存失败：" + e.message, 5000);
      }
    };
  }

  async function toggleAuto() {
    const next = !(SM.settings && SM.settings.auto);
    try {
      const r = await api("/api/starmap/settings", {
        method: "POST",
        body: JSON.stringify({ starmap_auto: next }),
      });
      SM.settings = { ...(SM.settings || {}), auto: next };
      toast(next ? "自动抽取已开启，每 30 分钟检查一次" : "自动抽取已关闭");
      await loadStarmap();
    } catch (e) {
      toast("保存失败：" + e.message, 4000);
    }
  }

  async function summarizeEpisode(id) {
    const btn = document.getElementById("sm-summary-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "生成中…";
    }
    try {
      const r = await api("/api/starmap/episode/summary", {
        method: "POST",
        body: JSON.stringify({ id: Number(id) }),
      });
      if (!r.ok) return toast(r.error || "生成失败", 6000);
      toast("篇章摘要已生成");
      await loadStarmap();
    } catch (e) {
      toast("生成失败：" + e.message, 6000);
    }
  }

  window.loadStarmap = loadStarmap;
  document.addEventListener("DOMContentLoaded", () => {
    if (location.hash === "#starmap") loadStarmap();
  });
})();
