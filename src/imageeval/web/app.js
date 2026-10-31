const app = { runId: null, pollTimer: null, lastStatus: null, lastRun: null, messageTimer: null };

function flashMessage(text) {
  const node = qs("run-message");
  node.textContent = text;
  clearTimeout(app.messageTimer);
  app.messageTimer = setTimeout(() => {
    node.textContent = "";
  }, 6000);
}

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
  select.innerHTML = batches
    .map((b) => `<option value="${b.id}">${escapeHtml(b.source_name)} (${b.sample_count})</option>`)
    .join("");
}

async function refreshRuns() {
  const runs = await getJSON("/api/runs");
  const select = qs("run-select");
  select.innerHTML = runs
    .map((r) => `<option value="${r.id}">${escapeHtml(r.name)} · ${r.status} · ${r.done}/${r.total}</option>`)
    .join("");
  if (runs.length) {
    const preferred = app.runId && runs.some((r) => r.id === app.runId) ? app.runId : runs[0].id;
    select.value = preferred;
    setRun(preferred);
  }
}

function setRun(runId) {
  app.runId = runId;
  app.lastRun = null;
  app.lastStatus = null;
  qs("run-message").textContent = "";
  qs("report-link").href = `/report?run_id=${runId}`;
  window.dispatchEvent(new CustomEvent("run-changed", { detail: { runId } }));
  pollRun();
}

async function pollRun() {
  if (!app.runId) return;
  clearTimeout(app.pollTimer);
  try {
    const data = await getJSON(`/api/runs/${app.runId}`);
    const run = data.run;
    app.lastRun = run;
    qs("run-progress").textContent = `${run.status} · ${run.done}/${run.total} · 失败 ${run.failed}`;
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
  const result = await postJSON("/api/runs", { name, batch_id: batchId });
  app.runId = result.run_id;
  await refreshRuns();
  qs("run-select").value = result.run_id;
  setRun(result.run_id);
  flashMessage("评测已创建，点击开始评分");
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

async function submitImport() {
  const file = qs("import-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("image_root", qs("import-root").value.trim());
  form.append("download", qs("import-download").checked ? "true" : "false");
  const response = await fetch("/api/import", { method: "POST", body: form });
  const text = await response.text();
  qs("import-result").textContent = text;
  if (response.ok) {
    await refreshBatches();
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  qs("btn-create-run").onclick = createRun;
  qs("btn-start").onclick = startRun;
  qs("btn-pause").onclick = pauseRun;
  qs("btn-import").onclick = () => qs("modal-import").classList.remove("hidden");
  qs("btn-import-cancel").onclick = () => qs("modal-import").classList.add("hidden");
  qs("btn-import-submit").onclick = submitImport;
  qs("run-select").onchange = (event) => setRun(event.target.value);
  try {
    await refreshBatches();
    await refreshRuns();
  } catch (err) {
    qs("run-progress").textContent = String(err.message);
  }
});
