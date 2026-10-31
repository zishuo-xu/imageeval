const app = { runId: null, pollTimer: null, lastStatus: null, lastRun: null, messageTimer: null };

function flashMessage(text) {
  const node = qs("run-message");
  node.textContent = text;
  clearTimeout(app.messageTimer);
  app.messageTimer = setTimeout(() => {
    node.textContent = "";
  }, 6000);
}

const runLabels = { running: "评分中", completed: "已完成", paused: "已暂停", pending: "待开始", created: "待开始", cancelled: "已取消" };

function updateControls(run) {
  const start = qs("btn-start");
  const pause = qs("btn-pause");
  const finished = run.status === "completed" && run.failed === 0;
  start.disabled = run.status === "running" || finished;
  start.textContent = finished
    ? "评分已完成"
    : run.status === "completed" && run.failed > 0
      ? "重试失败样本"
      : "开始评分";
  start.title = finished ? "该评测已全部评分完成；如需重跑请新建评测" : "";
  pause.disabled = run.status !== "running";
}

var escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));

async function refreshBatches() {
  const batches = await getJSON("/api/batches");
  const select = qs("batch-select");
  select.disabled = !batches.length;
  qs("btn-create-run").disabled = !batches.length;
  select.innerHTML = batches
    .map((b) => `<option value="${b.id}">${escapeHtml(b.source_name)} (${b.sample_count})</option>`)
    .join("") || '<option value="">请先导入数据</option>';
}

async function refreshRuns() {
  const runs = await getJSON("/api/runs");
  const select = qs("run-select");
  select.disabled = !runs.length;
  select.innerHTML = runs
    .map((r) => `<option value="${r.id}">${escapeHtml(r.name)} · ${runLabels[r.status] || r.status} · ${r.done}/${r.total}</option>`)
    .join("") || '<option value="">尚未创建评测</option>';
  if (runs.length) {
    const preferred = app.runId && runs.some((r) => r.id === app.runId) ? app.runId : runs[0].id;
    select.value = preferred;
    setRun(preferred);
  }
}

function setRun(runId) {
  clearTimeout(app.pollTimer);
  app.runId = runId;
  app.lastRun = null;
  app.lastStatus = null;
  qs("run-message").textContent = "";
  qs("report-link").removeAttribute("aria-disabled");
  qs("btn-start").disabled = true;
  qs("btn-pause").disabled = true;
  qs("report-link").href = `/report?run_id=${runId}`;
  window.dispatchEvent(new CustomEvent("run-changed", { detail: { runId } }));
  pollRun();
}

async function pollRun() {
  if (!app.runId) return;
  clearTimeout(app.pollTimer);
  const runId = app.runId;
  try {
    const data = await getJSON(`/api/runs/${runId}`);
    if (runId !== app.runId) return;
    const run = data.run;
    app.lastRun = run;
    qs("judge-status").textContent = `本次裁判：${run.provider === "fake" ? "模拟裁判" : run.judge_model} · ${run.provider === "fake" ? "非真实评分" : "真实模型"}`;
    const option = [...qs("run-select").options].find(option => option.value === runId);
    if (option) option.textContent = `${run.name} · ${runLabels[run.status] || run.status} · ${run.done}/${run.total}`;
    qs("run-progress").textContent = `${runLabels[run.status] || run.status} · 已评分 ${run.done} / ${run.total} · 失败 ${run.failed}`;
    updateControls(run);
    if (run.status !== app.lastStatus) {
      app.lastStatus = run.status;
      window.dispatchEvent(new CustomEvent("run-status", { detail: { run } }));
    }
    if (run.status === "running") {
      app.pollTimer = setTimeout(pollRun, 2000);
    }
  } catch (err) {
    qs("run-progress").textContent = String(err.message);
  }
}

async function createRun() {
  const batchId = qs("batch-select").value;
  if (!batchId) {
    alert("请先导入数据");
    return;
  }
  const name = qs("run-name").value.trim() || "未命名评测";
  qs("btn-create-run").disabled = true;
  try {
    const result = await postJSON("/api/runs", { name, batch_id: batchId });
    app.runId = result.run_id;
    await refreshRuns();
    qs("run-select").value = result.run_id;
    flashMessage("评测已创建，点击开始评分");
  } catch (err) { flashMessage(`创建失败：${err.message}`); }
  finally { qs("btn-create-run").disabled = false; }
}

async function startRun() {
  if (!app.runId) return;
  const run = app.lastRun;
  if (run && run.status === "completed" && run.failed === 0) {
    flashMessage("该评测已全部评分完成，无需重复评分；如需重跑请新建评测");
    return;
  }
  try {
    await postJSON(`/api/runs/${app.runId}/start`, {});
    flashMessage(run && run.failed > 0 ? "正在重试失败样本…" : "评分任务已提交…");
  } catch (err) {
    flashMessage(`启动失败：${err.message}`);
  }
  pollRun();
}

async function pauseRun() {
  if (!app.runId) return;
  if (!app.lastRun || app.lastRun.status !== "running") {
    flashMessage("当前没有正在执行的评分任务");
    return;
  }
  try {
    await postJSON(`/api/runs/${app.runId}/pause`, {});
    flashMessage("已暂停，点击开始评分可继续");
  } catch (err) {
    flashMessage(`暂停失败：${err.message}`);
  }
  pollRun();
}

function openImport() {
  qs("modal-import").classList.remove("hidden");
  qs("import-file").focus();
}
function closeImport() {
  qs("modal-import").classList.add("hidden");
  qs("btn-import").focus();
}
async function submitImport() {
  const file = qs("import-file").files[0];
  if (!file) { qs("import-result").textContent = "请先选择 CSV 或 JSONL 文件。"; return; }
  const form = new FormData();
  form.append("file", file);
  form.append("image_root", qs("import-root").value.trim());
  form.append("download", qs("import-download").checked ? "true" : "false");
  qs("btn-import-submit").disabled = true;
  qs("import-result").textContent = "正在导入并校验图片…";
  try {
    const response = await fetch("/api/import", { method: "POST", body: form });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
    qs("import-result").textContent = `导入完成：成功 ${result.imported} 条，拒绝 ${result.rejected} 条。` +
      (result.rejected ? `\n${JSON.stringify(result, null, 2)}` : "\n关闭窗口后，为此批次创建评测。");
    await refreshBatches();
    qs("batch-select").value = result.batch_id;
    qs("btn-import-cancel").textContent = "完成";
  } catch (err) { qs("import-result").textContent = `导入失败：${err.message}`; }
  finally { qs("btn-import-submit").disabled = false; }
}

window.addEventListener("DOMContentLoaded", async () => {
  qs("btn-create-run").onclick = createRun;
  qs("btn-start").onclick = startRun;
  qs("btn-pause").onclick = pauseRun;
  qs("btn-import").onclick = openImport;
  qs("btn-import-cancel").onclick = closeImport;
  qs("btn-import-submit").onclick = submitImport;
  qs("btn-empty-import").onclick = openImport;
  qs("modal-import").addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeImport();
    if (event.key === "Tab") {
      const nodes = [...qs("modal-import").querySelectorAll("input, button")].filter(n => !n.disabled);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  qs("run-select").onchange = (event) => setRun(event.target.value);
  try {
    const judge = await getJSON("/api/judge");
    qs("judge-status").textContent = judge.provider === "fake" ? "当前使用模拟裁判" : `当前裁判：${judge.model || "未配置"} · ${judge.configured && judge.credential_present ? "已配置" : "配置不完整"}`;
    await refreshBatches();
    await refreshRuns();
  } catch (err) {
    qs("run-progress").textContent = String(err.message);
  }
});
