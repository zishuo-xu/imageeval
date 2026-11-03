const comparison = { id: null, history: false, selectionSequence: 0, data: null, pairId: null, timer: null, sequence: 0, drafts: {}, previewItems: [], saving: false };
function clearComparison(message) {
  clearTimeout(comparison.timer);
  ++comparison.sequence;
  comparison.data = null;
  comparison.pairId = null;
  comparison.previewItems = [];
  for (const id of ["ab-summary", "ab-pairs", "ab-query", "ab-pair-delta", "ab-score-run"]) qs(id).replaceChildren();
  qs("ab-images").innerHTML = `<div class="stage-empty">${escapeHtml(message)}</div>`;
  qs("ab-vote").classList.add("hidden");
  qs("ab-status").textContent = message;
  qs("ab-score").disabled = qs("ab-upgrade").disabled = true;
  qs("ab-export").removeAttribute("href");
  qs("ab-export").setAttribute("aria-disabled", "true");
}
async function refreshExperiments({followCurrent = false} = {}) {
  const selection = ++comparison.selectionSequence;
  if (followCurrent) {
    comparison.history = false;
    comparison.id = null;
    clearComparison("正在读取当前生图任务…");
  }
  try {
    const [jobs, latest] = await Promise.all([getJSON("/api/comparisons"), getJSON("/api/generation/latest")]);
    if (selection !== comparison.selectionSequence) return;
    const selectedId = comparison.history ? comparison.id : (latest?.request.ab_compare ? latest.id : null);
    if (selectedId !== comparison.id) clearComparison("正在读取当前生图任务…");
    comparison.id = selectedId;
    if (comparison.history && !jobs.some(j => j.id === comparison.id)) comparison.id = null;
    qs("ab-experiment").innerHTML = '<option value="">选择历史对比任务…</option>' + jobs.map(j => `<option value="${escapeHtml(j.id)}">${j.id === latest?.id ? "当前" : "历史"} · ${escapeHtml(j.name)} · ${escapeHtml(new Date(j.created_at).toLocaleString())} · ${j.generated}/${j.total} 张</option>`).join("");
    qs("ab-experiment").value = comparison.id || "";
    if (comparison.id) await loadComparison();
    else clearComparison(latest ? "当前任务没有生成前后两版图片。请在生图时勾选“同时生成原始版与扩写版图片”；也可从上方主动选择历史任务。" : "尚未提交生图任务，请先生成前后对比图片。");
  } catch (err) { if (selection === comparison.selectionSequence) clearComparison(`读取当前任务失败：${err.message}，请点击刷新。`); }
}
async function loadComparison() {
  clearTimeout(comparison.timer);
  const request = ++comparison.sequence;
  const requestedId = comparison.id;
  if (!comparison.id) return;
  try {
    const scoreRun = localStorage.getItem(`imageeval.comparisonRun.${comparison.id}`);
    const data = await getJSON(`/api/comparisons/${comparison.id}${scoreRun ? `?run_id=${encodeURIComponent(scoreRun)}` : ""}`);
    if (request !== comparison.sequence || requestedId !== comparison.id) return;
    comparison.data = data;
    qs("ab-score-run").innerHTML = data.score_runs.map(r=>`<option value="${r.id}">${escapeHtml(r.name)} · ${runLabels[r.status] || r.status}</option>`).join("") || '<option value="">尚未创建评分</option>';
    qs("ab-score-run").value = data.run_id || "";
    qs("ab-upgrade").disabled = !data.run_id;

    if (!data.pairs.some(p => p.id === comparison.pairId)) comparison.pairId = data.pairs[0]?.id;
    const summary = data.summary;
    qs("ab-status").textContent = `${comparison.history ? "正在查看手动选择的历史任务" : "当前生图任务"} · ${data.pairs[0]?.query || data.name} · ${data.model} · ${data.aspect_ratio} · PE ${data.pe_model} / ${data.pe_template} · 已生成 ${data.generated}/${data.total} 张${data.run ? ` · 已评分 ${data.run.done}/${data.run.total}，失败 ${data.run.failed}` : ""}${data.error ? " · " + data.error : ""}`;
    qs("ab-score").disabled = !data.run_id || data.run?.status === "running" || (data.run?.status === "completed" && !data.run.failed);
    qs("ab-score").textContent = data.run?.failed ? "重试评分失败样本" : "开始 / 继续评分";
    qs("ab-export").removeAttribute("aria-disabled"); qs("ab-export").href = `/api/comparisons/${data.id}/export${data.run_id ? `?run_id=${data.run_id}` : ""}`;
    qs("ab-summary").innerHTML = `<span>图片齐全 <b>${summary.complete}/${summary.pairs} 对</b></span><span>双方评价完成 <b>${data.pairs.filter(p => p.A?.feedback && p.B?.feedback).length} 对</b></span><span>已确认 ${summary.votes} 组</span>`;
    if (!["ab-note", "ab-winner"].includes(document.activeElement?.id)) renderComparisonPair();
    if (["queued", "running"].includes(data.status) || data.run?.status === "running") comparison.timer = setTimeout(loadComparison, 2500);
  } catch (err) { if (request === comparison.sequence) qs("ab-status").textContent = `读取失败：${err.message}，可点击刷新。`; }
}
function renderComparisonPair() {
  const data = comparison.data;
  const pair = data.pairs.find(p => p.id === comparison.pairId);
  if (!pair) return;
  qs("ab-pairs").innerHTML = data.pairs.map(p => `<button data-pair="${p.id}" aria-pressed="${p.id === pair.id}"><strong>Query ${p.query_index+1} · 候选 ${p.candidate_index+1}</strong><span>${escapeHtml(p.query)}</span><small>${!p.A || !p.B ? "图片未齐全" : p.vote ? ({A:"原始版",B:"扩写版",tie:"持平"})[p.vote.winner] : "待确认"}</small></button>`).join("");
  qs("ab-query").textContent = `共同评分依据：${pair.query}`;
  qs("ab-pair-delta").textContent = `原始版：${pair.A?.feedback?.rating || "尚无评价"} · 扩写版：${pair.B?.feedback?.rating || "尚无评价"}`;
  comparison.previewItems = [];
  qs("ab-images").innerHTML = ["A", "B"].map(side => {
    const item = pair[side], prompt = pair[side === "A" ? "prompt_a" : "prompt_b"];
    const index = comparison.previewItems.length;
    if (item) comparison.previewItems.push({...item,query:pair.query,model_name:`${side} 组 · ${data.model}`,ai:item.scores});
    return `<article class="ab-card"><h3>${side === "A" ? "原始版" : "扩写版"}</h3><details open><summary>实际生图提示词${side === "B" ? " · 高亮新增 / 改写" : ""}</summary><div class="ab-prompt pe-difference">${side === "B" ? peDifference(pair.prompt_a,prompt) : escapeHtml(prompt)}</div></details>${item ? `<button class="preview-trigger" data-preview="compare" data-index="${index}" aria-label="查看 ${side} 组大图"><img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(prompt)}"></button>` : '<div class="ab-missing">尚无图片 · 未生成或生成失败</div>'}<div class="ab-check-summary">${escapeHtml(visualCheckSummary(item?.checks || []))} · 点击图片查看细项</div><div class="ab-scores">${!item ? "无法评分" : item.status === "error" ? `评分失败：${escapeHtml(item.error)}` : item.status !== "ok" ? "等待评分" : feedbackHTML(item.feedback)}</div></article>`;
  }).join("");
  qs("ab-vote").classList.remove("hidden");
  const key = `${data.id}:${pair.id}`;
  const draft = comparison.drafts[key] || pair.vote || {winner:"",note:""};
  qs("ab-winner").value = draft.winner; qs("ab-note").value = draft.note;
  qs("ab-save").disabled = !pair.A || !pair.B || comparison.saving;
  qs("ab-save-status").textContent = comparison.drafts[key] ? "未保存" : pair.vote ? "已保存" : "";
}
window.addEventListener("DOMContentLoaded", () => {
  qs("ab-score-run").onchange = event => {localStorage.setItem(`imageeval.comparisonRun.${comparison.id}`,event.target.value); loadComparison();};
  qs("ab-upgrade").onclick = async () => {
    if (!comparison.data?.run_id) return;
    qs("ab-upgrade").disabled = true;
    try { const created = await postJSON(`/api/runs/${comparison.data.run_id}/upgrade`, {}); localStorage.setItem(`imageeval.comparisonRun.${comparison.id}`,created.run_id); await loadComparison(); }
    catch(err) { qs("ab-status").textContent = err.message; qs("ab-upgrade").disabled = false; }
  };
  qs("ab-new").onclick = () => showWorkflowStage("expand");
  qs("ab-refresh").onclick = refreshExperiments;
  qs("ab-experiment").onchange = event => {
    ++comparison.selectionSequence;
    comparison.history = true;
    comparison.id = event.target.value || null;
    clearComparison(comparison.id ? "正在读取所选历史任务…" : "请选择一个历史任务，或重新点击“前后图片对比”查看当前任务。");
    if (comparison.id) loadComparison();
  };
  qs("ab-pairs").onclick = event => { const button = event.target.closest("[data-pair]"); if(button) { comparison.pairId = button.dataset.pair; renderComparisonPair(); } };
  for (const id of ["ab-note","ab-winner"]) qs(id).addEventListener("input", () => {
    comparison.drafts[`${comparison.id}:${comparison.pairId}`] = {winner:qs("ab-winner").value,note:qs("ab-note").value}; qs("ab-save-status").textContent = "未保存";
  });
  qs("ab-save").onclick = async () => {
    const body = {winner:qs("ab-winner").value,note:qs("ab-note").value};
    if (!body.winner) { qs("ab-save-status").textContent = "请先选择 原始版、扩写版或持平"; return; }
    const id = comparison.id, pair = comparison.pairId;
    comparison.saving = true; qs("ab-save").disabled = true;
    try { await postJSON(`/api/comparisons/${id}/votes/${pair}`,body); delete comparison.drafts[`${id}:${pair}`]; await loadComparison(); }
    catch(err) { qs("ab-save-status").textContent = `保存失败：${err.message}`; }
    finally { comparison.saving = false; qs("ab-save").disabled = false; }
  };
  qs("ab-score").onclick = async () => {
    if (!comparison.data?.run_id) return;
    qs("ab-score").disabled = true;
    try { await postJSON(`/api/runs/${comparison.data.run_id}/start`,{}); await loadComparison(); }
    catch(err) { qs("ab-status").textContent = `评分启动失败：${err.message}`; qs("ab-score").disabled = false; }
  };
});

window.addEventListener("generation-job-changed", () => {
  comparison.history = false;
  comparison.id = null;
  ++comparison.selectionSequence;
  clearComparison("生图任务已切换，正在等待本轮结果。");
  if (document.body.dataset.stage === "compare") refreshExperiments({followCurrent:true});
});
