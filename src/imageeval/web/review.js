const review = {
  items: [],
  index: 0,
  total: 0,
  runId: null,
  startedAt: 0,
  zoom: 1,
  panX: 0,
  panY: 0,
  focusDim: "adherence",
  saving: false,
};

const prefill = (human, ai) => (human ?? (ai == null ? "" : Math.round(ai)));

var escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));

function current() {
  return review.items[review.index];
}

async function loadQueue() {
  if (!review.runId) return;
  const filter = qs("filter").value;
  const order = qs("order").value;
  const data = await getJSON(
    `/api/review/queue?run_id=${encodeURIComponent(review.runId)}&filter=${filter}&order=${order}&limit=200`
  );
  review.items = data.items;
  review.total = data.total;
  review.index = 0;
  render();
}

function render() {
  const item = current();
  if (!item) {
    qs("query").textContent = "当前筛选下没有样本";
    qs("requirements").innerHTML = "";
    qs("subscores").innerHTML = "";
    qs("image").removeAttribute("src");
    qs("progress-text").textContent = "0 / 0";
    qs("error-banner").textContent = "";
    qs("error-banner").classList.add("hidden");
    qs("btn-retry").classList.add("hidden");
    return;
  }
  review.startedAt = Date.now();
  qs("state-badge").textContent = item.state;
  qs("query").textContent = item.query;
  qs("image").src = item.image_url;
  review.zoom = 1;
  review.panX = 0;
  review.panY = 0;
  applyTransform();

  qs("requirements").innerHTML = item.ai.requirements
    .map(
      (r) => `
      <li class="${r.status}">
        <div>${escapeHtml(r.text)}</div>
        <div class="req-meta">${escapeHtml(r.category)} · ${r.criticality} · ${r.status}</div>
        <div class="hint">${escapeHtml(r.evidence || "")}</div>
      </li>`
    )
    .join("");

  const human = item.human;
  qs("score-adherence").value = prefill(human?.adherence, item.ai.adherence);
  qs("score-quality").value = prefill(human?.quality, item.ai.quality);
  qs("score-aesthetics").value = prefill(human?.aesthetics, item.ai.aesthetics);
  qs("note").value = human?.note ?? "";
  qs("reason-general").value = human?.reasons?.general ?? "";

  const lines = [];
  for (const dim of ["quality", "aesthetics"]) {
    for (const [key, value] of Object.entries(item.ai.subscores[dim] || {})) {
      lines.push(
        `<div>${dim}.${key}：${value.score ?? "N/A"} ${escapeHtml(value.reason || "")}</div>`
      );
    }
  }
  qs("subscores").innerHTML = lines.join("");
  qs("progress-text").textContent = `${review.index + 1} / ${review.items.length}（筛选共 ${review.total}）`;
  qs("message").textContent = item.ai.verdict || "";

  const failed = item.eval_status === "error";
  qs("error-banner").textContent = failed ? item.ai.error || "评分失败" : "";
  qs("error-banner").classList.toggle("hidden", !failed);
  qs("btn-retry").classList.toggle("hidden", !failed);
  for (const id of ["btn-accept", "btn-save", "btn-skip"]) {
    qs(id).disabled = failed;
  }
}

function applyTransform() {
  qs("image").style.transform = `translate(${review.panX}px, ${review.panY}px) scale(${review.zoom})`;
}

async function submit(decision) {
  const item = current();
  if (!item || review.saving) return;
  review.saving = true;
  const payload = {
    decision,
    note: qs("note").value,
    duration_ms: Date.now() - review.startedAt,
  };
  if (decision === "corrected") {
    payload.human_adherence = Number(qs("score-adherence").value);
    payload.human_quality = Number(qs("score-quality").value);
    payload.human_aesthetics = Number(qs("score-aesthetics").value);
    const reason = qs("reason-general").value.trim();
    if (reason) payload.reasons = { general: reason };
  }
  try {
    await postJSON(`/api/evaluations/${item.evaluation_id}/review`, payload);
    review.total = Math.max(0, review.total - 1);
    review.items.splice(review.index, 1);
    if (review.items.length === 0) {
      await loadQueue();
      return;
    }
    if (review.index >= review.items.length) review.index = 0;
    render();
  } catch (err) {
    qs("message").textContent = `保存失败：${err.message}`;
  } finally {
    review.saving = false;
  }
}

function next() {
  if (review.index < review.items.length - 1) {
    review.index += 1;
    render();
  }
}

async function retryEvaluation() {
  const item = current();
  if (!item) return;
  qs("btn-retry").disabled = true;
  try {
    await postJSON(`/api/evaluations/${item.evaluation_id}/retry`, {});
    await loadQueue();
  } catch (err) {
    qs("message").textContent = `重试失败：${err.message}`;
  } finally {
    qs("btn-retry").disabled = false;
  }
}

function prev() {
  if (review.index > 0) {
    review.index -= 1;
    render();
  }
}

document.addEventListener("keydown", (event) => {
  const tag = event.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") {
    if (event.key === "Enter") {
      if (event.repeat) return;
      event.preventDefault();
      submit("corrected");
    }
    return;
  }
  if (tag === "SELECT" || tag === "BUTTON") return;
  const key = event.key.toLowerCase();
  if (event.repeat && (key === "a" || key === "s" || key === "enter")) {
    return;
  }
  if (key === "a") {
    event.preventDefault();
    submit("accepted");
  } else if (key === "s") {
    event.preventDefault();
    submit("skipped");
  } else if (key === "j") {
    event.preventDefault();
    next();
  } else if (key === "k") {
    event.preventDefault();
    prev();
  } else if (key === "f") {
    review.zoom = 1;
    review.panX = 0;
    review.panY = 0;
    applyTransform();
  } else if (key === "z") {
    event.preventDefault();
    review.zoom = review.zoom > 1 ? 1 : 2;
    applyTransform();
  } else if (/^[1-5]$/.test(key)) {
    qs(`score-${review.focusDim}`).value = key;
    const order = ["adherence", "quality", "aesthetics"];
    review.focusDim = order[(order.indexOf(review.focusDim) + 1) % order.length];
    document
      .querySelectorAll(".score-row")
      .forEach((row) => row.classList.toggle("focused", row.dataset.dim === review.focusDim));
  } else if (key === "enter") {
    event.preventDefault();
    submit("corrected");
  }
});

window.addEventListener("run-changed", (event) => {
  review.runId = event.detail.runId;
  loadQueue();
});

window.addEventListener("run-status", () => loadQueue());

window.addEventListener("DOMContentLoaded", () => {
  qs("btn-accept").onclick = () => submit("accepted");
  qs("btn-save").onclick = () => submit("corrected");
  qs("btn-skip").onclick = () => submit("skipped");
  qs("btn-refresh").onclick = () => loadQueue();
  qs("btn-retry").onclick = () => retryEvaluation();
  qs("filter").onchange = () => loadQueue();
  qs("order").onchange = () => loadQueue();
  document.querySelectorAll(".score-row input").forEach((input) => {
    input.addEventListener("focus", () => {
      review.focusDim = input.closest(".score-row").dataset.dim;
      document
        .querySelectorAll(".score-row")
        .forEach((row) => row.classList.toggle("focused", row.dataset.dim === review.focusDim));
    });
  });

  const wrap = qs("image-wrap");
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let baseX = 0;
  let baseY = 0;
  wrap.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 0.87;
      review.zoom = Math.min(8, Math.max(0.2, review.zoom * factor));
      applyTransform();
    },
    { passive: false }
  );
  wrap.addEventListener("pointerdown", (event) => {
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    baseX = review.panX;
    baseY = review.panY;
    wrap.classList.add("dragging");
    wrap.setPointerCapture(event.pointerId);
  });
  wrap.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    review.panX = baseX + (event.clientX - startX);
    review.panY = baseY + (event.clientY - startY);
    applyTransform();
  });
  wrap.addEventListener("pointerup", () => {
    dragging = false;
    wrap.classList.remove("dragging");
  });
});
