const generation = { job: null, timer: null, requestId: null, submittedBody: null, configured: false, submitting: false, followResult: false };
const generationActive = () => generation.submitting || ["queued", "running"].includes(generation.job?.status);

function generationFormState() {
  const busy = generationActive();
  qs("generation-form").querySelectorAll("input, textarea, select").forEach(node => { node.disabled = busy; });
  qs("btn-generation-submit").disabled = busy || !generation.configured;
  const count = qs("generation-prompts").value.split("\n").filter(v => v.trim()).length * Number(qs("generation-count").value);
  qs("btn-generation-submit").textContent = busy ? "正在生成…" : count ? qs("generation-ab").checked ? `生成前后对比 ${count} 组 · ${count * 2} 张` : `生成 ${count} 张图片` : "生成图片";
  qs("btn-reuse-prompts").disabled = busy || !generation.job;
}

function showGeneration(job) {
  const changed = generation.job?.id !== job.id;
  generation.job = job;
  if (changed) window.dispatchEvent(new CustomEvent("generation-job-changed", {detail:{job}}));
  qs("generation-progress").max = job.total || 1;
  qs("generation-progress").value = job.generated;
  qs("generation-banner").classList.remove("hidden");
  const label = {queued:"等待生成", running:"正在生成", completed:"生成完成", partial:"部分完成", failed:"生成失败", interrupted:"生成中断"}[job.status];
  qs("generation-status").textContent = `${job.model} · ${label} · 已生成 ${job.generated} / ${job.total} 张 · 已导入 ${job.imported} 张${job.error ? " · " + job.error : ""}`;
  qs("btn-generation-result").disabled = !job.request.ab_compare && !job.run_id;
  qs("btn-generation-result").textContent = job.request.ab_compare ? "查看前后图片 →" : "进入质量检查 →";
  qs("step-generate-state").textContent = `${label} ${job.generated}/${job.total}`;
  qs("generation-output-meta").textContent = `${job.total > 16 ? "预览前 16 张，全部图片请进入质量检查查看 · " : ""}${job.request.name} · ${job.request.aspect_ratio} · ${job.request.prompts.length} 条提示词 · 每条 ${job.request.images_per_prompt} 张`;
  if (generation.previewRun !== job.run_id) {
    generation.previewRun = job.run_id;
    renderGenerationPreview(job);
  }
  generationFormState();
}

async function openGenerationResult(navigate = true) {
  if (navigate && generation.job?.request.ab_compare) {
    showWorkflowStage("compare"); return;
  }
  if (!generation.job?.run_id) return;
  app.runId = generation.job.run_id;
  await refreshBatches();
  qs("batch-select").value = generation.job.batch_id;
  qs("filter").value = generation.job.request.auto_score ? "pending" : "all";
  await refreshRuns();
  if (navigate) showWorkflowStage("score");
}

async function pollGeneration() {
  clearTimeout(generation.timer);
  try {
    const job = await getJSON(`/api/generation/${generation.job.id}`);
    showGeneration(job);
    if (["queued", "running"].includes(job.status)) {
      generation.timer = setTimeout(pollGeneration, 1500);
    } else if (generation.followResult && job.run_id) {
      generation.followResult = false;
      await openGenerationResult(false);
    }
  } catch (err) {
    qs("generation-status").textContent = `读取生图进度失败：${err.message}。可刷新页面恢复查询，不要重复提交。`;
  }
}

async function submitGeneration(event) {
  event.preventDefault();
  if (generationActive()) return;
  const prompts = qs("generation-prompts").value.split("\n").map(value => value.trim()).filter(Boolean);
  const n = Number(qs("generation-count").value);
  if (!prompts.length || prompts.length * n > 16 || prompts.some(prompt => prompt.length > 1500)) {
    qs("generation-message").textContent = "请填写提示词：每条最多 1500 字符，每批最多 16 张，前后对比最多 16 组（32 张）。";
    return;
  }
  if (pe.source && JSON.stringify(pe.source) !== JSON.stringify(peQueries())) {
    qs("generation-message").textContent = "原始 Query 已修改，请返回 PE 步骤重新确认后再生图。";
    return;
  }
  if (pe.source && pe.source.length !== prompts.length) {
    qs("generation-message").textContent = "提示词行数已变化，请返回 Query / PE 扩写步骤重新确认对应关系。";
    return;
  }
  if (qs("generation-ab").checked && (!pe.source || !pe.appliedId)) {
    qs("generation-message").textContent = "请先确认扩写结果，再生成前后对比图片。"; return;
  }
  const body = {ab_compare: qs("generation-ab").checked, original_queries: pe.source, expansion_id: pe.appliedId, name: qs("generation-name").value.trim(), prompts, images_per_prompt: n,
    aspect_ratio: qs("generation-ratio").value, auto_score: qs("generation-score").checked};
  // Reuse the request ID if the POST result was lost; a second click cannot duplicate that job.
  const signature = JSON.stringify(body);
  if (generation.submittedBody !== signature || !generation.requestId) generation.requestId = crypto.randomUUID();
  generation.submittedBody = signature;
  generation.submitting = true;
  generationFormState();
  qs("generation-message").textContent = "正在提交…";
  try {
    const job = await postJSON("/api/generation", {...body, request_id: generation.requestId});
    generation.requestId = null;
    generation.followResult = true;
    showGeneration(job);
    qs("generation-message").textContent = "任务已提交，结果将在右侧显示。";
    pollGeneration();
  } catch (err) {
    qs("generation-message").textContent = `提交失败：${err.message}`;
  } finally {
    generation.submitting = false;
    generationFormState();
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  qs("btn-generate").onclick = () => { showWorkflowStage("expand"); qs("pe-queries").focus(); };
  qs("generation-form").onsubmit = submitGeneration;
  qs("btn-generation-result").onclick = () => openGenerationResult().catch(err => { qs("generation-status").textContent = err.message; });
  const estimate = () => {
    const count = qs("generation-prompts").value.split("\n").filter(value => value.trim()).length * Number(qs("generation-count").value);
    qs("generation-estimate").textContent = `${count} / 16 ${qs("generation-ab").checked ? `组 · 共 ${count * 2} 张` : "张"}${count > 16 ? " · 超出上限，请减少提示词或每条数量" : " · 保留原始 Query"}`;
    qs("generation-estimate").classList.toggle("over-limit", count > 16);
    generationFormState();
  };
  qs("generation-prompts").oninput = estimate;
  qs("generation-count").onchange = estimate;
  qs("generation-ab").onchange = estimate;
  try {
    const config = await getJSON("/api/generation/config");
    generation.configured = config.configured;
    qs("generation-config").textContent = `${config.model} · ${config.configured ? "已配置，可生成图片" : "未配置，请在服务端设置 MINIMAX_API_KEY"}`;
    const latest = await getJSON("/api/generation/latest");
    if (latest) { showGeneration(latest); if (generationActive()) pollGeneration(); }
  } catch (err) { qs("generation-config").textContent = `读取配置失败：${err.message}`; }
  generationFormState();
});

async function renderGenerationPreview(job) {
  const target = qs("generation-preview");
  if (!job.run_id) {
    target.innerHTML = '<div class="stage-empty">' + (generationActive() ? "正在生成图片…" : "暂无生成结果") + '</div>';
    return;
  }
  try {
    const data = await getJSON(`/api/samples?run_id=${encodeURIComponent(job.run_id)}&limit=16`);
    if (generation.job.id !== job.id) return;
    generation.items = data.items;
    target.innerHTML = data.items.map((item, index) => `<figure class="output-card"><button class="preview-trigger" data-preview="generate" data-index="${index}" aria-label="查看第 ${index + 1} 张大图"><img src="${escapeHtml(item.thumb_url)}" alt="${escapeHtml(item.query)}"></button><figcaption><span class="output-index">${index + 1}</span><strong>${index + 1}. ${escapeHtml(item.model_name)}</strong><p title="${escapeHtml(item.query)}">${escapeHtml(item.query)}</p></figcaption></figure>`).join("");
  } catch (err) { target.textContent = `结果读取失败：${err.message}`; }
}
