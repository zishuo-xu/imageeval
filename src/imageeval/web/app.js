const app = { runId: null, pollTimer: null };

async function refreshBatches() {
  const batches = await getJSON("/api/batches");
  const select = qs("batch-select");
  select.innerHTML = batches
    .map((b) => `<option value="${b.id}">${b.source_name} (${b.sample_count})</option>`)
    .join("");
}

async function refreshRuns() {
  const runs = await getJSON("/api/runs");
  const select = qs("run-select");
  select.innerHTML = runs
    .map((r) => `<option value="${r.id}">${r.name} · ${r.status} · ${r.done}/${r.total}</option>`)
    .join("");
  if (runs.length) {
    const preferred = app.runId && runs.some((r) => r.id === app.runId) ? app.runId : runs[0].id;
    select.value = preferred;
    setRun(preferred);
  }
}

function setRun(runId) {
  app.runId = runId;
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
    qs("run-progress").textContent = `${run.status} · ${run.done}/${run.total} · 失败 ${run.failed}`;
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
}

async function startRun() {
  if (!app.runId) return;
  await postJSON(`/api/runs/${app.runId}/start`, {});
  pollRun();
}

async function pauseRun() {
  if (!app.runId) return;
  await postJSON(`/api/runs/${app.runId}/pause`, {});
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
