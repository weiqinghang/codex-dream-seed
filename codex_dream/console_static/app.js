const state = {
  token: "",
  overview: {},
  runs: [],
  knowledge: [],
  improvements: {items: [], attention: [], counts: {}},
  handoffs: [],
  filter: "all",
  selected: null,
};

const NEXT_INSTRUCTION = "继续处理我刚才在 Dream Console 中确认的事项。";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const formatDate = (value) => value
  ? new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "short", day: "numeric"}).format(new Date(value))
  : "—";

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
  runs: ["DREAM HISTORY", "每一次梦境，都有清晰边界", "查看周期范围、完成状态和已经形成的报告。"],
  improvements: ["IMPROVEMENT TRACKING", "掌握每一项改进的旅程", "先看全局状态，再进入单项细节；候选池不会被 Top 5 截断。"],
  knowledge: ["KNOWLEDGE BASE", "已经沉淀了什么", "检查知识、载体、采用和验证是否真正落实。"],
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

async function copyInstruction(button) {
  try {
    await navigator.clipboard.writeText(NEXT_INSTRUCTION);
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
  banner.classList.toggle("is-hidden", !active);
  if (!active) return;
  const labels = {
    handoff_pending: ["计划已确认，等待 Codex 接续", "Console 已保存你的决定，但不会自行开始实验。"],
    claimed: ["Codex 已领取这项计划", "执行和语义工作正在 Codex 中进行，完成后会回写这里。"],
    failed: ["Codex 接续遇到问题", active.error || "打开事项查看原因，再回到 Codex 处理。"],
  };
  const [title, copy] = labels[active.status];
  $("#handoff-title").textContent = title;
  $("#handoff-copy").textContent = copy;
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
  $("#runs-list").innerHTML = state.runs.length ? state.runs.map((run, index) => `
    <article class="timeline-entry">
      <div class="timeline-marker"><span>${String(index + 1).padStart(2, "0")}</span><i></i></div>
      <div><time>${formatDate(run.started_at)}</time><h2>${escapeHtml(run.title)}</h2><p>${run.report_path ? `报告已保存 · ${escapeHtml(run.report_path)}` : "这一轮尚未形成周期报告"}</p></div>
      <span class="status-pill">${escapeHtml(run.status)}</span>
    </article>`).join("") : '<div class="empty-state">还没有记录完整的梦境周期。</div>';
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
    await loadData();
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
  const [overview, runs, knowledge, improvements, handoffs] = await Promise.all([
    api("/api/overview"), api("/api/runs"), api("/api/knowledge"), api("/api/improvements"), api("/api/handoffs"),
  ]);
  state.overview = overview;
  state.runs = runs.runs;
  state.knowledge = knowledge.items;
  state.improvements = improvements;
  state.handoffs = handoffs.handoffs;
  renderHome();
  renderRuns();
  renderImprovements();
  renderKnowledge();
}

async function boot() {
  try {
    const config = await api("/api/config");
    state.token = config.token;
    $("#workspace-name").textContent = config.workspace;
    await loadData();
    setView((location.hash || "#home").slice(1));
  } catch (error) {
    document.body.innerHTML = `<main class="fatal-error"><b>Dream Console 无法读取本地 Workspace</b><span>${escapeHtml(error.message)}</span></main>`;
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
$("#copy-result").addEventListener("click", (event) => copyInstruction(event.currentTarget));
$("#improvement-dialog").addEventListener("click", (event) => {
  if (event.target === $("#improvement-dialog")) closeDialog();
});
window.addEventListener("hashchange", () => setView((location.hash || "#home").slice(1)));

boot();
