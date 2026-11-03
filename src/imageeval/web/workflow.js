const scoring = { page: 0, request: 0, signature: null };

function showWorkflowStage(stage) {
  document.body.dataset.stage = stage;
  localStorage.setItem("imageeval.stage", stage);
  for (const name of ["expand", "generate", "score", "review", "compare"]) {
    const button = qs(`step-${name}`);
    if (name === stage) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
  if (stage === "score") renderScoringPreview();
  if (stage === "compare") refreshExperiments({followCurrent: true});
}

function updateScoringSummary() {
  const run = app.lastRun;
  qs("score-total").textContent = run?.total ?? "—";
  qs("score-done").textContent = run?.done ?? "—";
  qs("score-failed").textContent = run?.failed ?? "—";
  qs("score-failed").parentElement.classList.toggle("has-failures", !!run?.failed);
  qs("score-model").textContent = run ? (run.provider === "fake" ? "模拟裁判" : run.judge_model) : "—";
  qs("btn-to-review").disabled = !run?.done;
  qs("step-score-state").textContent = run ? `${runStatusText(run)} ${run.done}/${run.total}` : "待选择评测";
  const pages = Math.ceil((run?.total || 0) / 16);
  qs("score-page-position").textContent = `第 ${pages ? scoring.page + 1 : 0} / ${pages} 页 · 每页 16 张`;
  qs("score-prev-page").disabled = scoring.page === 0;
  qs("score-next-page").disabled = scoring.page + 1 >= pages;
}

async function renderScoringPreview() {
  updateScoringSummary();
  const request = ++scoring.request;
  const target = qs("score-preview");
  if (!app.runId) { target.innerHTML = '<div class="stage-empty">先生成或导入图片，再创建评测。</div>'; return; }
  try {
    const data = await getJSON(`/api/samples?run_id=${encodeURIComponent(app.runId)}&limit=16&offset=${scoring.page * 16}`);
    if (request !== scoring.request) return;
    scoring.items = data.items;
    target.innerHTML = data.items.map((item, index) => `<figure class="output-card ${item.state === "error" ? "has-failures" : ""}"><button class="preview-trigger" data-preview="score" data-index="${index}" aria-label="查看第 ${scoring.page * 16 + index + 1} 张大图"><img src="${escapeHtml(item.thumb_url)}" alt="${escapeHtml(item.query)}"></button><figcaption><span class="output-index">${scoring.page * 16 + index + 1}</span><strong>${scoring.page * 16 + index + 1}. ${escapeHtml(item.model_name || "导入图片")}</strong><p title="${escapeHtml(item.query)}">${escapeHtml(item.query)}</p><div class="output-scores">${item.feedback ? feedbackHTML(item.feedback) : item.state === "error" ? "评价失败 · 可重试" : "尚无评价"}</div></figcaption></figure>`).join("") || '<div class="stage-empty">此评测暂无图片。</div>';
  } catch (err) { if (request === scoring.request) target.textContent = `图片读取失败：${err.message}`; }
}

window.addEventListener("DOMContentLoaded", () => {
  for (const stage of ["expand", "generate", "score", "review", "compare"]) qs(`step-${stage}`).onclick = () => showWorkflowStage(stage);
  qs("btn-to-review").onclick = () => showWorkflowStage("review");
  qs("score-prev-page").onclick = () => { scoring.page--; renderScoringPreview(); };
  qs("score-next-page").onclick = () => { scoring.page++; renderScoringPreview(); };
  updateScoringSummary();
});
window.addEventListener("run-changed", () => {
  scoring.page = 0;
  scoring.signature = null;
  ++scoring.request;
  qs("score-preview").innerHTML = '<div class="stage-empty">正在读取图片…</div>';
  updateScoringSummary();
});
window.addEventListener("run-updated", ({detail: {run}}) => {
  updateScoringSummary();
  const signature = `${app.runId}:${run.status}:${run.done}:${run.failed}`;
  if (signature !== scoring.signature && document.body.dataset.stage === "score") renderScoringPreview();
  scoring.signature = signature;
});
