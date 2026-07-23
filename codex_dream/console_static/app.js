const state = {
  token: "",
  overview: {},
  runs: [],
  knowledge: [],
  improvements: {items: [], attention: [], counts: {}},
  handoffs: [],
  board: {columns: [], cards: [], advisories: [], counts: {}},
  boardFilters: {project: "all", scope: "all", health: "all"},
  boardSort: "value_desc",
  validationSort: "progress_desc",
  filter: "all",
  selected: null,
  config: {},
  activeHandoff: null,
  lastUpdatedAt: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const formatDate = (value) => value
  ? new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "short", day: "numeric"}).format(new Date(value))
  : "—";
const formatDuration = (seconds) => {
  if (!Number.isFinite(seconds)) return "耗时未记录";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const restMinutes = minutes % 60;
    return `耗时 ${hours} 小时 ${restMinutes} 分`;
  }
  return `耗时 ${minutes} 分 ${remainder} 秒`;
};
const formatTokenCount = (value) => new Intl.NumberFormat("zh-CN", {notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
const tokenSummary = (run) => {
  const usage = run.run_metrics?.token_usage;
  if (!Number.isFinite(usage?.total_tokens)) return "Token 未记录";
  const breakdown = [
    Number.isFinite(usage.input_tokens) ? `输入 ${formatTokenCount(usage.input_tokens)}` : "",
    Number.isFinite(usage.cached_input_tokens) ? `缓存 ${formatTokenCount(usage.cached_input_tokens)}` : "",
    Number.isFinite(usage.output_tokens) ? `输出 ${formatTokenCount(usage.output_tokens)}` : "",
  ].filter(Boolean).join(" · ");
  return `Token ${formatTokenCount(usage.total_tokens)}${breakdown ? `（${breakdown}）` : ""}`;
};
const dreamOrdinal = (runId) => {
  const match = String(runId || "").match(/(\d+)$/);
  if (!match) return "—";
  return match[1].replace(/^0+(?=\d)/, "").padStart(2, "0");
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

const viewCopy = {
  home: ["TODAY", "今天需要你关注什么", "这里只放最关键的事项。决定以后，回到 Codex 继续真正的工作。"],
  board: ["COMMITMENT FLOW", "每一个梦境，现在走到哪里", "按泳道控制在制品、发现滞留，并优先关闭已经具备验收条件的事项。"],
  runs: ["DREAM HISTORY", "每一次梦境，都有清晰边界", "最新梦境在最上方；查看审阅范围、耗时、Token 记录与最终报告。"],
  improvements: ["IMPROVEMENT TRACKING", "掌握每一项改进的旅程", "先看全局状态，再进入单项细节；候选池不会被 Top 5 截断。"],
  knowledge: ["KNOWLEDGE BASE", "已经沉淀了什么", "检查知识、载体、采用和验证是否真正落实。"],
  help: ["OPERATING HANDBOOK", "使用指南", "从第一次 Dream、稳定接续、验证判断到故障恢复。"],
};

function setView(name) {
  if (!viewCopy[name]) name = "home";
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("is-visible", view.id === `view-${name}`));
  const [overline, title, description] = viewCopy[name];
  $("#page-overline").textContent = overline;
  $("#page-title").textContent = title;
  $("#page-description").textContent = description;
  location.hash = name;
}

function statusClass(value) {
  return `status-${String(value || "unknown").replace(/[^a-z_]/g, "")}`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 2200);
}

async function copyInstruction(button, content) {
  try {
    const text = content || state.activeHandoff?.next_instruction || "开始做梦";
    await navigator.clipboard.writeText(text);
    showToast("已复制。回到 Codex 粘贴即可继续。 ");
    if (button) {
      const original = button.textContent;
      button.textContent = "已复制";
      window.setTimeout(() => { button.textContent = original; }, 1600);
    }
  } catch (_error) {
    showToast("请手动复制页面上的接续指令。 ");
  }
}

function renderHandoffBanner() {
  const active = state.handoffs.find((item) => item.status === "handoff_pending")
    || state.handoffs.find((item) => item.status === "claimed")
    || state.handoffs.find((item) => item.status === "failed");
  const banner = $("#handoff-banner");
  state.activeHandoff = active || null;
  banner.classList.toggle("is-hidden", !active);
  if (!active) return;
  const labels = {
    handoff_pending: ["计划已确认，等待 Codex 接续", "Console 已保存你的决定，但不会自行开始实验。"],
    claimed: ["Codex 已领取这项计划", "执行和语义工作正在 Codex 中进行，完成后会回写这里。"],
    failed: ["Codex 接续遇到问题", active.error || "打开事项查看原因，再回到 Codex 处理。"],
  };
  const [title, copy] = labels[active.status];
  $("#handoff-title").textContent = title;
  $("#handoff-copy").textContent = `${copy} · ${active.action_id} · 第 ${active.payload?.attempt || 1} 次尝试`;
  $("#copy-handoff").classList.toggle("is-hidden", active.status === "failed");
  $("#retry-handoff").classList.toggle("is-hidden", active.status !== "failed");
}

function attentionCard(item, index) {
  const reasons = (item.priority_reasons || []).slice(0, 2).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("");
  return `<button type="button" class="attention-card" data-open-improvement="${escapeHtml(item.candidate_id)}">
    <span class="attention-rank">0${index + 1}</span>
    <span class="attention-body">
      <span class="attention-meta"><i class="status-pill ${statusClass(item.lifecycle)}">${escapeHtml(item.lifecycle_label)}</i>${reasons}</span>
      <b>${escapeHtml(item.title)}</b>
      <small>${escapeHtml(item.summary || "查看证据并决定下一步")}</small>
    </span>
    <span class="attention-action">${escapeHtml(item.next_action)} <i>→</i></span>
  </button>`;
}

function renderHome() {
  renderHandoffBanner();
  const isEmpty = state.runs.length === 0 && state.improvements.items.length === 0;
  $("#first-run").classList.toggle("is-hidden", !isEmpty);
  $("#nav-attention-count").textContent = state.improvements.attention.length;
  $("#attention-list").innerHTML = state.improvements.attention.length
    ? state.improvements.attention.map(attentionCard).join("")
    : '<div class="empty-state compact">现在没有需要你立即决定的事项。下一次做梦后，关键候选会出现在这里。</div>';
  const recent = state.runs.slice(0, 3);
  $("#recent-runs").innerHTML = recent.length ? recent.map((run) => `
    <article class="run-card">
      <time>${formatDate(run.started_at)}</time>
      <div><h3>${escapeHtml(run.title)}</h3><p>${run.report_path ? "已形成周期报告" : "结构化梦境周期"}</p></div>
      <span>${escapeHtml(run.status)}</span>
    </article>`).join("") : '<div class="empty-state compact">还没有完整的梦境周期。</div>';
  bindImprovementLinks();
}

function renderRuns() {
  const runs = [...state.runs].sort((a, b) => Date.parse(b.started_at || 0) - Date.parse(a.started_at || 0));
  $("#runs-list").innerHTML = runs.length ? runs.map((run) => `
    <article class="timeline-entry">
      <div class="timeline-marker"><span>${escapeHtml(dreamOrdinal(run.run_id))}</span><i></i></div>
      <div class="run-content">
        <time>${formatDate(run.started_at)} · ${escapeHtml(run.run_id)}</time>
        <h2>${escapeHtml(run.title)}</h2>
        <div class="run-metrics">
          <span>${run.reviewed_task_count ?? run.task_count ?? 0} 个审阅任务</span>
          <span>${formatDuration(run.run_metrics?.duration_seconds)}</span>
          <span class="${run.run_metrics?.token_usage ? "" : "is-missing"}">${escapeHtml(tokenSummary(run))}</span>
        </div>
        <p>${run.report_path ? `<button type="button" class="text-button" data-open-report="${escapeHtml(run.run_id)}">在 Console 安全打开报告</button>` : "这一轮尚未形成周期报告"}</p>
      </div>
      <span class="status-pill">${escapeHtml(run.status)}</span>
    </article>`).join("") : '<div class="empty-state">还没有梦境。回到 Codex 发送“开始做梦”，完成后这里会显示时间、序号和报告。</div>';
  $$('[data-open-report]').forEach((button) => button.addEventListener("click", () => openReport(button.dataset.openReport)));
}

async function openReport(runId) {
  const dialog = $("#report-dialog");
  $("#report-title").textContent = "正在读取已登记报告…";
  $("#report-content").textContent = "";
  dialog.showModal();
  try {
    const report = await api(`/api/report?run=${encodeURIComponent(runId)}`);
    $("#report-title").textContent = report.title;
    $("#report-content").textContent = report.content;
  } catch (error) {
    $("#report-title").textContent = "报告无法读取";
    $("#report-content").textContent = error.message;
  }
}

function boardCard(card) {
  const missing = card.acceptance?.missing || [];
  const progress = card.progress;
  const tags = [...(card.projects || []).slice(0, 1), card.scope].filter(Boolean);
  const metrics = card.sort_metrics || {};
  const impactLabels = ["未知", "会话", "项目", "跨项目", "全局"];
  return `<button type="button" class="flow-card ${card.health === "attention" ? "is-attention" : ""}" data-board-card="${escapeHtml(card.card_id)}">
    <span class="flow-card-meta"><b>${escapeHtml(card.entity_type)} · ${escapeHtml(card.card_id)}</b><span>${card.age_days ?? 0} 天</span></span>
    <h3>${escapeHtml(card.title)}</h3>
    ${tags.length ? `<span class="flow-card-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</span>` : ""}
    <span class="flow-card-signals"><span>价值 ${metrics.value_impact ?? 0}/5</span><span>${impactLabels[metrics.scope_breadth] || "未知"}</span><span>Dream ${metrics.dream_mentions ?? 0} 次</span></span>
    ${progress ? evidenceProgress(card) : ""}
    ${progress ? `<span class="flow-card-line"><b>进度</b><span>${progress.current}/${progress.target} 个合格任务 · ${card.evidence_summary?.observed || 0} 次反馈</span></span>` : ""}
    ${missing.length ? `<span class="flow-card-line"><b>缺口</b><span>${missing.map(humanizeGap).join("、")}</span></span>` : ""}
    <span class="flow-card-line"><b>下一步</b><span>${escapeHtml(card.next_action)}</span></span>
  </button>`;
}

function evidenceProgress(card) {
  const evidence = card.evidence_summary || {};
  const target = card.progress?.target || 0;
  const segment = (kind, count) => count && target
    ? `<i class="evidence-segment evidence-${kind} progress-p${Math.min(10, Math.max(1, Math.round(count / target * 10)))}"></i>`
    : "";
  const uncertain = (evidence.mixed || 0) + (evidence.inconclusive || 0) + (evidence.unclassified || 0);
  return `<span class="progress-track evidence-track" aria-label="验证进度 ${card.progress.current}/${target}，正向 ${evidence.positive || 0}，负向 ${evidence.negative || 0}，混合或未定 ${uncertain}">
    ${segment("positive", evidence.positive || 0)}${segment("negative", evidence.negative || 0)}${segment("uncertain", uncertain)}
  </span>`;
}

function compareBoardCards(left, right) {
  const a = left.sort_metrics || {};
  const b = right.sort_metrics || {};
  let result = 0;
  if (state.boardSort === "value_desc") {
    result = (b.value_impact || 0) - (a.value_impact || 0)
      || (b.scope_breadth || 0) - (a.scope_breadth || 0);
  } else if (state.boardSort === "mentions_desc") {
    result = (b.dream_mentions || 0) - (a.dream_mentions || 0);
  } else {
    const aTime = Date.parse(a.proposed_at || "");
    const bTime = Date.parse(b.proposed_at || "");
    if (Number.isNaN(aTime) !== Number.isNaN(bTime)) result = Number.isNaN(aTime) ? 1 : -1;
    else if (!Number.isNaN(aTime)) result = state.boardSort === "oldest_first" ? aTime - bTime : bTime - aTime;
  }
  return result || String(left.card_id).localeCompare(String(right.card_id));
}

function compareValidationCards(left, right) {
  const a = left.sort_metrics || {};
  const b = right.sort_metrics || {};
  const progress = (b.validation_progress || 0) - (a.validation_progress || 0);
  const feedback = (b.feedback_count || 0) - (a.feedback_count || 0);
  const result = state.validationSort === "feedback_desc" ? feedback || progress : progress || feedback;
  return result || String(left.card_id).localeCompare(String(right.card_id));
}

function humanizeGap(value) {
  return ({human_decision: "人工决策", human_final_decision: "最终判断", validation: "验证合同", adoption: "落实记录", handoff: "接续记录", dream_completion: "梦境完成"})[value] || String(value).replaceAll("_", " ");
}

function renderBoardFilters() {
  const projects = [...new Set(state.board.cards.flatMap((card) => card.projects || []))].sort();
  const scopes = [...new Set(state.board.cards.map((card) => card.scope).filter(Boolean))].sort();
  const setOptions = (selector, values, allLabel, selected) => {
    const select = $(selector);
    select.innerHTML = `<option value="all">${allLabel}</option>${values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
    select.value = values.includes(selected) ? selected : "all";
  };
  setOptions("#board-project-filter", projects, "全部项目", state.boardFilters.project);
  setOptions("#board-scope-filter", scopes, "全部范围", state.boardFilters.scope);
  $("#board-health-filter").value = state.boardFilters.health;
}

function renderBoard() {
  const {columns = [], cards = [], advisories = []} = state.board;
  const active = columns.filter((column) => column.wip_limit !== null);
  const activeStages = new Set(active.map((column) => column.id));
  const over = active.filter((column) => column.count > column.wip_limit);
  const closeout = columns.find((column) => column.id === "closeout")?.count || 0;
  $("#nav-board-count").textContent = advisories.length;
  $("#board-summary").innerHTML = [
    [cards.filter((card) => activeStages.has(card.stage)).length, "活跃 WIP", over.length ? "is-warning" : ""],
    [closeout, "等待收尾", closeout ? "is-warning" : ""],
    [over.length, "超限泳道", over.length ? "is-warning" : ""],
    [cards.filter((card) => card.health === "attention").length, "需关注卡片", ""],
  ].map(([value, label, klass]) => `<div class="board-metric ${klass}"><strong>${value}</strong><span>${label}</span></div>`).join("");
  $("#advisor-list").innerHTML = advisories.length ? advisories.slice(0, 3).map((item) => `<button type="button" class="advisor-item" data-board-card="${escapeHtml(item.card_id || "")}"><i></i><span>${escapeHtml(item.message)}</span><b>${escapeHtml(item.stage || "")}</b></button>`).join("") : '<div class="advisor-empty">当前没有容量或收尾提醒，可以按既定节奏推进。</div>';
  const filtered = cards.filter((card) =>
    (state.boardFilters.project === "all" || (card.projects || []).includes(state.boardFilters.project)) &&
    (state.boardFilters.scope === "all" || card.scope === state.boardFilters.scope) &&
    (state.boardFilters.health === "all" || card.health === state.boardFilters.health));
  $("#flow-board").innerHTML = columns.map((column) => {
    const values = filtered.filter((card) => card.stage === column.id)
      .sort(column.id === "validation_active" ? compareValidationCards : compareBoardCards);
    const capacity = column.wip_limit === null ? `${column.count} 项` : `${column.count}/${column.wip_limit}`;
    const validationSort = column.id === "validation_active" ? `<label class="validation-column-sort">列内排序<select id="validation-sort"><option value="progress_desc" ${state.validationSort === "progress_desc" ? "selected" : ""}>进度比例</option><option value="feedback_desc" ${state.validationSort === "feedback_desc" ? "selected" : ""}>反馈总数</option></select></label>` : "";
    return `<section class="board-column ${column.wip_limit !== null && column.count > column.wip_limit ? "is-over" : ""}" aria-labelledby="column-${column.id}">
      <header class="column-head"><h2 id="column-${column.id}">${escapeHtml(column.label)}</h2><b>${capacity}</b><small>最老 ${column.oldest_age_days || 0} 天${values.length !== column.count ? ` · 显示 ${values.length}` : ""}</small>${validationSort}</header>
      <div class="column-cards">${values.length ? values.map(boardCard).join("") : '<div class="column-empty">当前无事项</div>'}</div>
    </section>`;
  }).join("");
  $("#validation-sort")?.addEventListener("change", (event) => {
    state.validationSort = event.currentTarget.value;
    renderBoard();
  });
  $$('[data-board-card]').forEach((button) => button.addEventListener("click", () => openBoardCard(button.dataset.boardCard)));
}

function openBoardCard(cardId) {
  const card = state.board.cards.find((value) => value.card_id === cardId);
  if (!card) return;
  const missing = card.acceptance?.missing || [];
  const evidence = card.evidence_summary;
  const guidance = card.validation_guidance;
  const timeline = (card.timeline || []).map((event) => {
    const label = event.type || `${event.phase || "run"} · ${event.status || "recorded"}`;
    return `<li><span>${escapeHtml(label)} · ${formatDate(event.occurred_at)}</span></li>`;
  }).join("");
  const criteriaForm = card.entity_type === "validation" && card.stage === "closeout" ? `<form class="validation-closeout" id="validation-closeout"><p class="overline">HUMAN CLOSEOUT GATE</p><h3>逐条复核成功标准</h3>${(card.success_criteria || []).map((criterion, index) => `<label><span>${index + 1}. ${escapeHtml(criterion)}</span><select name="criterion-${index}" required><option value="">选择判断</option><option value="met">满足</option><option value="not_met">未满足</option><option value="unknown">证据不足</option></select></label>`).join("")}<div class="validation-adjust"><label><span>合格任务目标</span><input id="validation-target" type="number" min="1" value="${card.progress?.target || 1}"></label><label><span>最长观察天数</span><input id="validation-days" type="number" min="1" value="${card.max_validation_days || 30}"></label></div><label><span>判断依据</span><textarea id="validation-reason" minlength="3" required placeholder="引用证据摘要，说明为什么固化、调整、结束或继续。"></textarea></label><div class="detail-actions"><button type="button" class="button ghost" data-validation-action="continue">继续观察</button><button type="button" class="button ghost" data-validation-action="adjust">调整合同</button><button type="button" class="button danger" data-validation-action="failed">结束为失败</button><button type="button" class="button ghost" data-validation-action="inconclusive">结束为未定</button><button type="button" class="button primary" data-validation-action="proven">确认固化</button></div><p class="form-status" id="validation-status"></p></form>` : "";
  const validationInsight = guidance ? renderValidationInsight(guidance, evidence) : "";
  $("#board-detail").innerHTML = `<div class="board-detail-head"><div><p class="overline">${escapeHtml(card.entity_type)} · ${escapeHtml(card.card_id)}</p><h2>${escapeHtml(card.title)}</h2><p>${escapeHtml(card.next_action)}</p></div><i class="status-pill">${escapeHtml(card.stage)}</i></div>
    <div class="board-detail-grid"><section><h3>验收状态</h3><p>${escapeHtml(card.acceptance?.status || "—")}</p><p>${missing.length ? `仍缺：${missing.map(humanizeGap).join("、")}` : "没有未满足的显式缺口。"}</p></section>
    <section><h3>时间与健康度</h3><p>当前阶段 ${card.age_days ?? 0} 天 · ${card.health === "attention" ? "需要关注" : "节奏正常"}</p></section>
    <section><h3>关系链</h3><ul>${(card.related_ids || []).map((id) => `<li>${escapeHtml(id)}</li>`).join("") || "<li>暂无</li>"}</ul></section>
    <section><h3>证据摘要</h3><p>${evidence ? `反馈 ${evidence.observed || 0} · 合格 ${evidence.eligible} · 合规 ${evidence.compliant} · 正向 ${evidence.positive} · 负向 ${evidence.negative} · 混合/未定 ${(evidence.mixed || 0) + (evidence.inconclusive || 0) + (evidence.unclassified || 0)}` : "该阶段尚未进入验证采样。"}</p></section></div>
    ${validationInsight}<p class="overline">TRACEABLE TIMELINE</p><ol class="board-timeline">${timeline || ((card.source_dream_ids || []).map((id) => `<li><span>来源梦境 ${escapeHtml(id)}</span></li>`).join("") || "<li><span>历史阶段未知；没有伪造事件。</span></li>")}<li><span>当前实体 ${escapeHtml(card.card_id)} 位于「${escapeHtml(card.stage)}」</span></li></ol>${criteriaForm}`;
  $$('[data-validation-action]').forEach((button) => button.addEventListener("click", () => submitValidation(card, button.dataset.validationAction)));
  $("#board-dialog").showModal();
}

function asTextList(value) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return value === null || value === undefined || value === "" ? [] : [String(value)];
}

function renderValidationInsight(guidance, evidence) {
  const contract = guidance.contract || {};
  const factors = [
    ["适用条件", contract.applies_when],
    ["预期行为", contract.expected_behavior],
    ["可观察信号", contract.observable_signals],
    ["成功标准", contract.success_criteria],
    ["失败信号", contract.failure_signals],
  ];
  const factorHtml = factors.map(([label, values]) => {
    const items = asTextList(values);
    return `<div><b>${label}</b>${items.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>尚未定义</p>"}</div>`;
  }).join("");
  const blockers = (guidance.blockers || []).map((item) => `<li>${escapeHtml(item.message)}</li>`).join("");
  return `<section class="validation-insight">
    <div class="validation-recommendation"><p class="overline">NEXT VALIDATION MOVE</p><h3>接下来建议</h3><p>${escapeHtml(guidance.recommendation)}</p></div>
    <div class="validation-factors"><h3>哪些事情会影响验收</h3>${factorHtml}</div>
    <div class="validation-blockers"><h3>当前阻碍</h3><ul>${blockers || "<li>没有检测到显式阻碍；仍需由人复核证据质量。</li>"}</ul></div>
    <div class="evidence-legend"><h3>证据方向怎么理解</h3><p><b class="legend-positive">正向</b> 合格任务的结果支持成功标准。</p><p><b class="legend-negative">负向</b> 合格任务的结果反对假设或触发失败信号；它是有价值的反证，不应被隐藏。</p><p><b class="legend-uncertain">混合/未定</b> 结果方向不单一或信息不足，不能直接用于固化。</p><p>另外有 ${evidence?.excluded || 0} 次反馈未进入合格样本；它们影响验证设计，但不增加进度。</p></div>
  </section>`;
}

async function submitValidation(card, action) {
  const reason = $("#validation-reason").value.trim();
  const selects = [...$("#validation-closeout").querySelectorAll("select")];
  const assessments = selects.map((select) => select.value);
  if (reason.length < 3) { $("#validation-status").textContent = "请留下至少 3 个字的判断依据。"; return; }
  if (!["continue", "adjust"].includes(action) && assessments.some((value) => !value)) { $("#validation-status").textContent = "形成最终结论前，请逐条判断成功标准。"; return; }
  $("#validation-status").textContent = "正在保存人工复核记录…";
  try {
    await api("/api/validation-actions", {method: "POST", headers: {"X-Dream-Token": state.token}, body: JSON.stringify({knowledge_id: card.knowledge_id, validation_id: card.card_id, action, reason, assessments: ["continue", "adjust"].includes(action) ? [] : assessments, eligible_sessions_target: Number($("#validation-target").value), max_validation_days: Number($("#validation-days").value)})});
    await loadData();
    $("#board-dialog").close();
    showToast(action === "proven" ? "验证已确认固化。" : action === "continue" ? "已记录继续观察决定。" : action === "adjust" ? "验证合同已调整并保留旧版本。" : "验证结论已记录。");
  } catch (error) { $("#validation-status").textContent = error.message; }
}

function openPolicy() {
  $("#policy-fields").innerHTML = state.board.columns.filter((column) => column.wip_limit !== null).map((column) => `<label>${escapeHtml(column.label)}<input type="number" min="1" max="99" name="${escapeHtml(column.id)}" value="${column.wip_limit}"></label>`).join("");
  $("#policy-reason").value = "";
  $("#policy-status").textContent = "";
  $("#policy-dialog").showModal();
}

async function submitPolicy(event) {
  event.preventDefault();
  const reason = $("#policy-reason").value.trim();
  if (reason.length < 3) { $("#policy-status").textContent = "请留下至少 3 个字的调整理由。"; return; }
  const limits = Object.fromEntries([...new FormData(event.currentTarget).entries()].filter(([key]) => key !== "reason").map(([key, value]) => [key, Number(value)]));
  try {
    await api("/api/board-policy", {method: "POST", headers: {"X-Dream-Token": state.token}, body: JSON.stringify({limits, reason})});
    await loadData();
    $("#policy-dialog").close();
    showToast("WIP 策略已保存并留下审计记录。");
  } catch (error) { $("#policy-status").textContent = error.message; }
}

const filterLabels = {
  all: "全部",
  candidate: "新候选",
  planning: "计划中",
  deferred: "已暂缓",
  waiting_codex: "等待 Codex",
  codex_claimed: "Codex 已领取",
  experiment: "实验中",
  review: "待复核",
  implementation_pending: "待落实",
  implementing: "落实中",
  completed: "已完成",
  ended: "已结束",
};

function renderFilters() {
  const counts = state.improvements.counts || {};
  const visible = Object.keys(filterLabels).filter((key) => key === "all" || counts[key]);
  $("#improvement-filters").innerHTML = visible.map((key) => `
    <button type="button" class="filter-button ${state.filter === key ? "is-active" : ""}" data-filter="${key}">${filterLabels[key]} <span>${counts[key] || 0}</span></button>
  `).join("");
  $$("[data-filter]").forEach((button) => button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    renderImprovements();
  }));
}

function renderImprovements() {
  renderFilters();
  const all = state.improvements.items || [];
  const items = state.filter === "all" ? all : all.filter((item) => item.lifecycle === state.filter);
  $("#tracking-total").textContent = all.length;
  $("#improvement-list").innerHTML = items.length ? `
    <div class="improvement-head"><span>改进事项</span><span>当前状态</span><span>证据</span><span>下一步</span></div>
    ${items.map((item) => `<button type="button" class="improvement-row" data-open-improvement="${escapeHtml(item.candidate_id)}">
      <span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.summary || "—")}</small></span>
      <span><i class="status-pill ${statusClass(item.lifecycle)}">${escapeHtml(item.lifecycle_label)}</i></span>
      <span>${item.task_count || 0} 个任务<br><small>${formatDate(item.updated_at)}</small></span>
      <span>${escapeHtml(item.next_action)} <i>→</i></span>
    </button>`).join("")}` : '<div class="empty-state compact">这个状态下暂时没有改进项。</div>';
  bindImprovementLinks();
}

function renderKnowledge() {
  const index = $("#knowledge-index");
  index.innerHTML = state.knowledge.length ? state.knowledge.map((item, position) => `
    <button type="button" class="knowledge-link ${position === 0 ? "is-active" : ""}" data-knowledge="${escapeHtml(item.knowledge_id)}">
      <span class="knowledge-kind">${escapeHtml(item.kind)}</span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.summary)}</small>
    </button>`).join("") : '<div class="empty-state compact">还没有沉淀知识。</div>';
  $$(".knowledge-link").forEach((button) => button.addEventListener("click", () => {
    $$(".knowledge-link").forEach((item) => item.classList.toggle("is-active", item === button));
    showKnowledge(button.dataset.knowledge);
  }));
  if (state.knowledge[0]) showKnowledge(state.knowledge[0].knowledge_id);
}

function showKnowledge(id) {
  const item = state.knowledge.find((value) => value.knowledge_id === id);
  if (!item) return;
  const groups = [
    ["观察", item.observations], ["候选", item.candidates], ["人工决定", item.decisions],
    ["采用记录", item.adoptions], ["验证记录", item.validations],
  ];
  $("#knowledge-detail").innerHTML = `
    <p class="overline">${escapeHtml(item.kind)} · ${formatDate(item.updated_at)}</p>
    <h2>${escapeHtml(item.title)}</h2><p class="knowledge-summary">${escapeHtml(item.summary)}</p>
    <div class="knowledge-properties"><span>成熟度 <b>${escapeHtml(item.maturity)}</b></span><span>范围 <b>${escapeHtml(item.scope)}</b></span></div>
    <div class="knowledge-journey">${groups.map(([label, records]) => `<div><span>${records.length}</span><b>${label}</b></div>`).join("")}</div>
    <section class="next-step"><p class="overline">NEXT ACTION</p><p>${escapeHtml(item.next_action || "等待下一次独立证据")}</p></section>`;
}

const lifecycleSteps = ["候选", "计划", "实验", "落实", "完成"];
const lifecycleIndex = {
  candidate: 0, planning: 1, waiting_codex: 1, codex_claimed: 1,
  deferred: 0, experiment: 2, review: 2, implementation_pending: 3, implementing: 3, completed: 4, ended: 0,
};

function openImprovement(candidateId) {
  const item = state.improvements.items.find((value) => value.candidate_id === candidateId);
  if (!item) return;
  state.selected = item;
  const current = lifecycleIndex[item.lifecycle] ?? 0;
  const reasons = (item.priority_reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
  const evidence = (item.evidence || []).map((value) => `<li>${escapeHtml(typeof value === "string" ? value : JSON.stringify(value))}</li>`).join("");
  const handoffError = item.handoff?.status === "failed" ? `<div class="error-callout"><b>Codex 接续失败</b><span>${escapeHtml(item.handoff.error || "请回到 Codex 查看详情")}</span></div>` : "";
  const actions = item.lifecycle === "candidate" ? `<div class="detail-actions">
    <button type="button" class="button ghost" data-start-action="defer">暂不处理</button>
    <button type="button" class="button danger" data-start-action="reject">不采纳</button>
    <button type="button" class="button primary" data-start-action="enter_trial">制定试用计划</button>
  </div>` : item.lifecycle === "waiting_codex" || item.lifecycle === "review" ? `<div class="detail-actions"><button type="button" class="button primary" data-copy-detail>复制指令，回到 Codex</button></div>` : "";
  $("#improvement-detail").innerHTML = `
    <p class="overline">IMPROVEMENT JOURNEY</p>
    <div class="detail-title"><div><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.summary || "")}</p></div><i class="status-pill ${statusClass(item.lifecycle)}">${escapeHtml(item.lifecycle_label)}</i></div>
    <div class="journey-rail">${lifecycleSteps.map((label, index) => `<div class="${index < current ? "is-done" : index === current ? "is-current" : ""}"><i>${index < current ? "✓" : index + 1}</i><span>${label}</span></div>`).join("")}</div>
    ${handoffError}
    <div class="detail-grid">
      <section><p class="overline">WHY IT MATTERS</p><h3>为什么它会出现在这里</h3><ul>${reasons || "<li>已有可追溯证据，等待你的判断。</li>"}</ul></section>
      <section><p class="overline">EVIDENCE</p><h3>当前证据</h3><ul>${evidence || "<li>暂无可公开的证据摘要。</li>"}</ul></section>
      <section><p class="overline">BOUNDARY</p><h3>范围与限制</h3><p>${escapeHtml(item.limits || "尚未记录明确限制。")}</p></section>
      <section><p class="overline">NEXT</p><h3>下一步</h3><p>${escapeHtml(item.next_action)}</p></section>
    </div>${actions}`;
  $("#decision-form").classList.add("is-hidden");
  $("#handoff-result").classList.add("is-hidden");
  $("#improvement-detail").classList.remove("is-hidden");
  $$("[data-start-action]").forEach((button) => button.addEventListener("click", () => startDecision(button.dataset.startAction)));
  const copy = $("[data-copy-detail]");
  if (copy) copy.addEventListener("click", () => copyInstruction(copy));
  $("#improvement-dialog").showModal();
}

function bindImprovementLinks() {
  $$("[data-open-improvement]").forEach((button) => button.addEventListener("click", () => openImprovement(button.dataset.openImprovement)));
}

function reminderDate() {
  const value = new Date();
  value.setDate(value.getDate() + 30);
  return value.toISOString().slice(0, 10);
}

function startDecision(action) {
  const item = state.selected;
  if (!item) return;
  $("#dialog-knowledge-id").value = item.knowledge_id;
  $("#dialog-candidate-id").value = item.candidate_id;
  $("#dialog-action").value = action;
  $("#improvement-detail").classList.add("is-hidden");
  $("#decision-form").classList.remove("is-hidden");
  $("#simple-decision").classList.toggle("is-hidden", action === "enter_trial");
  $("#trial-fields").classList.toggle("is-hidden", action !== "enter_trial");
  $("#form-status").textContent = "";
  $("#decision-reason").value = "";
  if (action === "enter_trial") {
    $("#trial-proposal").value = item.summary || "";
    $("#trial-scope").value = item.scope === "global" || item.scope === "cross_project" ? "environment" : "project";
    $("#trial-reminder").value = reminderDate();
    $("#trial-carrier").value = "";
    $("#trial-success").value = item.validation_plan || "";
    $("#trial-reason").value = "";
    $("#criteria-confirmed").checked = false;
    const trial = state.board.columns.find((column) => column.id === "trial_active");
    const atCapacity = trial && trial.count >= trial.wip_limit;
    $("#wip-override-field").classList.toggle("is-hidden", !atCapacity);
    $("#wip-override-reason").value = "";
    window.setTimeout(() => $("#trial-proposal").focus(), 50);
  } else {
    $("#decision-reason").placeholder = action === "reject" ? "为什么不采纳？" : "为什么现在暂不处理？";
    window.setTimeout(() => $("#decision-reason").focus(), 50);
  }
}

function closeDialog() {
  $("#improvement-dialog").close();
  state.selected = null;
}

async function submitDecision(event) {
  event.preventDefault();
  const action = $("#dialog-action").value;
  const isTrial = action === "enter_trial";
  const reason = (isTrial ? $("#trial-reason") : $("#decision-reason")).value.trim();
  if (reason.length < 3) {
    $("#form-status").textContent = "请留下至少 3 个字的判断依据。";
    return;
  }
  const payload = {
    action,
    knowledge_id: $("#dialog-knowledge-id").value,
    candidate_id: $("#dialog-candidate-id").value,
    reason,
  };
  if (action === "defer") payload.deferred_until = (() => {
    const value = new Date();
    value.setDate(value.getDate() + 7);
    return value.toISOString().slice(0, 10);
  })();
  if (isTrial) {
    const criteria = $("#trial-success").value.split("\n").map((value) => value.trim()).filter(Boolean);
    if (!criteria.length || !$("#criteria-confirmed").checked || !$("#trial-carrier").value) {
      $("#form-status").textContent = "请确认成功标准，并选择预期固化载体。";
      return;
    }
    payload.trial_plan = {
      proposal: $("#trial-proposal").value.trim(),
      scope: $("#trial-scope").value,
      target_carrier: $("#trial-carrier").value,
      carrier_confirmed: Boolean($("#trial-carrier").value),
      eligible_sessions_target: Number($("#trial-sessions").value),
      max_validation_days: Number($("#trial-days").value),
      reminder_date: $("#trial-reminder").value,
      success_criteria: criteria,
      failure_signals: [],
      criteria_confirmed: true,
    };
    if (!$("#wip-override-field").classList.contains("is-hidden")) {
      payload.wip_override_reason = $("#wip-override-reason").value.trim();
      if (payload.wip_override_reason.length < 3) {
        $("#form-status").textContent = "试用落实泳道已满，请说明为什么仍要开启新事项。";
        return;
      }
    }
  }
  const submit = $("#decision-submit");
  submit.disabled = true;
  $("#form-status").textContent = "正在保存可追溯记录…";
  try {
    const result = await api("/api/candidate-actions", {
      method: "POST",
      headers: {"X-Dream-Token": state.token},
      body: JSON.stringify(payload),
    });
    if (result.next_instruction) {
      $("#next-instruction").textContent = result.next_instruction;
      state.activeHandoff = result.handoff;
      state.activeHandoff.next_instruction = result.next_instruction;
    }
    try {
      await loadData();
    } catch (refreshError) {
      $("#form-status").textContent = `记录已成功写入，但页面刷新失败：${refreshError.message}。请勿重复提交，点击刷新或用 Console Context 核对。`;
      $("#refresh-state").textContent = "写入成功 · 刷新失败 · 数据可能陈旧";
      return;
    }
    if (result.status === "handoff_pending") {
      $("#decision-form").classList.add("is-hidden");
      $("#handoff-result").classList.remove("is-hidden");
    } else {
      closeDialog();
      showToast(action === "reject" ? "已记录不采纳决定。" : "已暂存，候选仍保留在完整列表中。 ");
    }
  } catch (error) {
    $("#form-status").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function loadData() {
  $("#refresh-state").textContent = "正在刷新…";
  const results = await Promise.allSettled([
    api("/api/overview"), api("/api/runs"), api("/api/knowledge"), api("/api/improvements"), api("/api/handoffs"), api("/api/board"),
  ]);
  const keys = ["overview", "runs", "knowledge", "improvements", "handoffs", "board"];
  const failures = [];
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      failures.push(keys[index]);
      return;
    }
    const value = result.value;
    if (keys[index] === "runs") state.runs = value.runs;
    else if (keys[index] === "knowledge") state.knowledge = value.items;
    else if (keys[index] === "handoffs") state.handoffs = value.handoffs;
    else state[keys[index]] = value;
  });
  renderHome();
  renderRuns();
  renderImprovements();
  renderKnowledge();
  renderBoardFilters();
  renderBoard();
  state.lastUpdatedAt = new Date();
  const time = state.lastUpdatedAt.toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
  $("#refresh-state").textContent = failures.length
    ? `部分刷新失败（${failures.join("、")}）· 已保留成功数据 · ${time}`
    : `已更新 ${time}`;
  if (failures.length === results.length) throw new Error("所有 Console API 均刷新失败");
}

async function boot() {
  try {
    const config = await api("/api/config");
    state.config = config;
    state.token = config.token;
    $("#workspace-name").textContent = `${config.fingerprint} · ${config.workspace_source}`;
    await loadData();
    setView((location.hash || "#home").slice(1));
  } catch (error) {
    document.body.innerHTML = `<main class="fatal-error"><b>Dream Console 无法读取本地 Workspace</b><span>${escapeHtml(error.message)}</span></main>`;
  }
}

async function retryActiveHandoff() {
  const handoff = state.activeHandoff;
  if (!handoff || handoff.status !== "failed") return;
  const reason = window.prompt("请说明这次重试的原因（会写入历史）：", "已排除上一轮失败原因，重新接续。");
  if (!reason || reason.trim().length < 3) return;
  const requestId = globalThis.crypto?.randomUUID?.() || `retry-${Date.now()}`;
  try {
    await api("/api/handoff-retry", {
      method: "POST",
      headers: {"X-Dream-Token": state.token},
      body: JSON.stringify({action_id: handoff.action_id, reason: reason.trim(), source: "human:dream-console", request_id: requestId}),
    });
    await loadData();
    showToast("已保留失败历史并重新排队，可复制新的接续指令。 ");
  } catch (error) {
    showToast(`重试未写入：${error.message}`);
  }
}

$$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$$("[data-jump]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.jump)));
$$("[data-dialog-close]").forEach((button) => button.addEventListener("click", closeDialog));
$("[data-cancel-action]").addEventListener("click", () => {
  $("#decision-form").classList.add("is-hidden");
  $("#improvement-detail").classList.remove("is-hidden");
});
$("#decision-form").addEventListener("submit", submitDecision);
$("#copy-handoff").addEventListener("click", (event) => copyInstruction(event.currentTarget));
$("#copy-result").addEventListener("click", (event) => copyInstruction(event.currentTarget, $("#next-instruction").textContent));
$("#copy-first-dream").addEventListener("click", (event) => copyInstruction(event.currentTarget, "开始做梦"));
$("#retry-handoff").addEventListener("click", retryActiveHandoff);
$("#refresh-data").addEventListener("click", () => loadData().catch((error) => {
  $("#refresh-state").textContent = `刷新失败 · 数据可能陈旧 · ${error.message}`;
}));
$("#improvement-dialog").addEventListener("click", (event) => {
  if (event.target === $("#improvement-dialog")) closeDialog();
});
[$("#board-project-filter"), $("#board-scope-filter"), $("#board-health-filter")].forEach((select) => select.addEventListener("change", () => {
  state.boardFilters = {project: $("#board-project-filter").value, scope: $("#board-scope-filter").value, health: $("#board-health-filter").value};
  renderBoard();
}));
$("#board-sort").addEventListener("change", (event) => {
  state.boardSort = event.currentTarget.value;
  renderBoard();
});
$("#open-policy").addEventListener("click", openPolicy);
$$('[data-board-close]').forEach((button) => button.addEventListener("click", () => $("#board-dialog").close()));
$$('[data-policy-close]').forEach((button) => button.addEventListener("click", () => $("#policy-dialog").close()));
$$('[data-report-close]').forEach((button) => button.addEventListener("click", () => $("#report-dialog").close()));
$("#policy-form").addEventListener("submit", submitPolicy);
window.addEventListener("hashchange", () => setView((location.hash || "#home").slice(1)));
window.addEventListener("focus", () => loadData().catch(() => {}));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") loadData().catch(() => {});
});

boot();
