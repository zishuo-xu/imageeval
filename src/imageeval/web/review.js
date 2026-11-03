const review = {
  items: [],
  index: 0,
  total: 0,
  runId: null,
  startedAt: 0,
  zoom: 1,
  panX: 0,
  panY: 0,
  options: null,
  drafts: {},
  saving: false,
  queueRequest: 0,
  page: 0,
  pageSize: 16,
  view: "grid",
  loading: false,
};



var escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));

function readFeedback() {
  return {feedback: {
    rating: document.querySelector('input[name="satisfaction"]:checked')?.value || "",
    positive_points: Array.from(document.querySelectorAll('#positive-points input:checked'), n => n.value),
    negative_points: Array.from(document.querySelectorAll('#negative-points input:checked'), n => n.value),
  }, note: qs("note").value};
}
function renderFeedback(item) {
  const draft = review.drafts[item?.evaluation_id] || item?.human || {};
  const feedback = draft.feedback || {};
  const options = review.options;
  qs("satisfaction-options").innerHTML = (options?.ratings || []).map(label => `<label><input type="radio" name="satisfaction" value="${escapeHtml(label)}" ${feedback.rating === label ? "checked" : ""}><span title="${escapeHtml(options.criteria[label])}">${escapeHtml(label)}</span></label>`).join("");
  for (const [id, key] of [["positive-points", "positive_points"], ["negative-points", "negative_points"]]) {
    qs(id).innerHTML = (options?.[key] || []).map(label => `<label><input type="checkbox" value="${escapeHtml(label)}" ${(feedback[key] || []).includes(label) ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`).join("");
  }
  qs("feedback-points").classList.toggle("hidden", !feedback.rating);
  qs("note").value = draft.note || "";
  updateReviewControls();
}

function current() {
  return review.items[review.index];
}

async function loadQueue() {
  if (!review.runId) return;
  const filter = qs("filter").value;
  const order = qs("order").value;
  const request = ++review.queueRequest;
  const selectedId = current()?.evaluation_id;
  const selectedIndex = review.index;
  review.loading = true;
  updateReviewControls();
  try {
    const data = await getJSON(
      `/api/review/queue?run_id=${encodeURIComponent(review.runId)}&filter=${filter}&order=${order}&limit=${review.pageSize}&offset=${review.page * review.pageSize}`
    );
    if (request !== review.queueRequest) return;
    review.total = data.total;
    const lastPage = Math.max(0, Math.ceil(data.total / review.pageSize) - 1);
    if (review.page > lastPage) { review.page = lastPage; return await loadQueue(); }
    review.items = data.items;
    const selected = data.items.findIndex(item => item.evaluation_id === selectedId);
    review.index = selected >= 0 ? selected : Math.min(selectedIndex, Math.max(0, data.items.length - 1));
    render();
    return true;
  } catch (err) {
    if (request === review.queueRequest) qs("message").textContent = `队列加载失败：${err.message}`;
  } finally {
    if (request === review.queueRequest) { review.loading = false; updateReviewControls(); }
  }
}

function updateReviewControls() {
  const item = current();
  for (const id of ["btn-save", "btn-skip", "note"]) {
    qs(id).disabled = !item || item.eval_status === "error" || review.saving || review.loading;
  }
  document.querySelectorAll(".satisfaction-options input, .feedback-points input").forEach(input => { input.disabled = !item || item.eval_status === "error" || review.saving || review.loading; });
  qs("btn-save").disabled ||= !review.options;
  qs("btn-prev").disabled = review.saving || review.loading || (review.page === 0 && review.index === 0) || !item;
  qs("btn-next").disabled = review.saving || review.loading || review.page * review.pageSize + review.index >= review.total - 1 || !item;
  qs("btn-fit").disabled = qs("btn-zoom").disabled = qs("btn-detail").disabled = !item;
  qs("btn-prev-page").disabled = review.saving || review.loading || review.page === 0;
  qs("btn-next-page").disabled = review.saving || review.loading || (review.page + 1) * review.pageSize >= review.total;
  qs("gallery").querySelectorAll("button").forEach(button => { button.disabled = review.saving || review.loading; });
}

const stateLabels = {rated: "已评价",ai_done: "待复核", accepted: "已接受", corrected: "已修正", skipped: "已跳过", error: "评分失败"};
const scoreText = value => value == null ? "—" : Number(value).toFixed(1);

function renderGallery() {
  if (review.galleryItems !== review.items) {
  review.galleryItems = review.items;
  qs("gallery").innerHTML = review.items.map((item, index) => {
    const reviewed = ["accepted", "corrected", "rated"].includes(item.state);
    return `<button class="image-card ${index === review.index ? "selected" : ""}" data-index="${index}" aria-pressed="${index === review.index}" aria-label="第 ${review.page * review.pageSize + index + 1} 张：${escapeHtml(item.query)}" title="${escapeHtml(item.query)} · 双击查看大图">
      <img src="${escapeHtml(item.thumb_url)}" alt="" loading="lazy">
      <span class="card-state ${reviewed ? "reviewed" : item.state}">${stateLabels[item.state] || escapeHtml(item.state)}</span>
      <div class="card-caption"><div class="card-query">${review.page * review.pageSize + index + 1}. ${escapeHtml(item.query)}</div>
      <div class="card-scores"><span>AI：${escapeHtml(item.ai.feedback?.rating || "未评价")}</span><span>${item.human?.feedback ? "人工：" + escapeHtml(item.human.feedback.rating) : ""}</span></div></div>
    </button>`;
  }).join("") + (review.items.length ? Array.from({length: review.pageSize - review.items.length}, () => '<div class="empty-slot" aria-hidden="true">—</div>').join("") : "");
  }
  qs("gallery").querySelectorAll(".image-card").forEach((card, index) => {
    card.classList.toggle("selected", index === review.index);
    card.setAttribute("aria-pressed", String(index === review.index));
  });
  const pages = Math.ceil(review.total / review.pageSize);
  qs("page-position").textContent = `第 ${pages ? review.page + 1 : 0} / ${pages} 页`;
  setView(review.view);
}

function setView(view) {
  review.view = view;
  qs("gallery").classList.toggle("hidden", view !== "grid" || !current());
  qs("image-wrap").classList.toggle("hidden", view !== "detail" || !current());
  qs("btn-grid").setAttribute("aria-pressed", String(view === "grid"));
  qs("btn-detail").setAttribute("aria-pressed", String(view === "detail"));
}

async function changePage(page, index = 0) {
  if (review.saving || review.loading || page < 0 || page * review.pageSize >= review.total) return;
  review.page = page;
  review.items = [];
  review.index = index;
  await loadQueue();
}

function resetQueue() {
  review.page = 0;
  review.index = 0;
  review.items = [];
  render();
  loadQueue();
}

function render() {
  const item = current();
  document.querySelector(".panel").scrollTop = 0;
  renderGallery();
  updateReviewControls();
  qs("image").classList.toggle("hidden", !item);
  qs("empty-state").classList.toggle("hidden", !!item);
  qs("sample-position").textContent = item ? `选中 ${review.page * review.pageSize + review.index + 1} / ${review.total}` : "暂无样本";
  if (!item) {
    renderPromptProvenance("review", null);
    qs("review-checks").innerHTML = "";
    qs("state-badge").textContent = "";
    for (const id of ["sample-meta", "ai-observation", "ai-verdict"]) qs(id).textContent = "";
    qs("message").textContent = "";
    qs("ai-feedback").innerHTML = "";
    qs("note").value = "";
    renderFeedback(null);
    qs("empty-title").textContent = review.runId ? "当前队列暂无样本" : "从一批图片开始";
    qs("empty-description").textContent = review.runId ? "评分完成后可在此复核；也可以切换筛选查看其他样本。" : "导入 CSV 或 JSONL，创建评测后开始 AI 评分。";
    qs("btn-empty-import").classList.toggle("hidden", !!review.runId);
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
  qs("state-badge").textContent = ({rated: "已评价", ai_done: "待复核", pending: "待复核", accepted: "已接受", corrected: "已修正", reviewed: "已复核", skipped: "已跳过", error: "评分失败"})[item.state] || item.state;
  qs("query").textContent = item.query;
  renderPromptProvenance("review", item.prompt_expansion);
  qs("review-checks").innerHTML = visualChecksHTML(item.ai.subscores.checks || []);
  qs("sample-meta").textContent = `${item.model_name || "未标注生图模型"} · ${item.tags.join(" / ") || "无标签"}`;
  qs("ai-observation").textContent = item.ai.observation || "";
  qs("ai-verdict").textContent = item.ai.verdict || "";
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
        <div class="req-meta">${escapeHtml(r.category)} · ${r.criticality === "critical" ? "关键需求" : "普通需求"} · ${({satisfied:"满足", partial:"部分满足", missing:"缺失", contradicted:"冲突"})[r.status] || escapeHtml(r.status)}</div>
        <div class="hint">${escapeHtml(r.evidence || "")}</div>
      </li>`
    )
    .join("");

  qs("ai-feedback").innerHTML = feedbackHTML(item.ai.feedback);
  const human = item.human;
  renderFeedback(item);

  const lines = [];
  for (const dim of ["quality", "aesthetics"]) {
    for (const [key, value] of Object.entries(item.ai.subscores[dim] || {})) {
      lines.push(
        `<div>${dim}.${key}：${escapeHtml(value.reason || "")}</div>`
      );
    }
  }
  qs("subscores").innerHTML = lines.join("");
  qs("progress-text").textContent = `当前页 ${review.items.length} 张 · 共 ${review.total} 张`;
  qs("message").textContent = "";

  const failed = item.eval_status === "error";
  qs("error-banner").textContent = failed ? item.ai.error || "评分失败" : "";
  qs("error-banner").classList.toggle("hidden", !failed);
  qs("btn-retry").classList.toggle("hidden", !failed);
  updateReviewControls();
}

function applyTransform() {
  qs("btn-zoom").textContent = review.zoom > 1 ? "缩小" : "放大";
  qs("image").style.transform = `translate(${review.panX}px, ${review.panY}px) scale(${review.zoom})`;
}

async function submit(decision) {
  const item = current();
  if (!item || item.eval_status === "error" || review.saving || review.loading) return;
  const draft = readFeedback();
  if (decision === "rated" && !draft.feedback.rating) {
    qs("message").textContent = "请先选择满意度。"; return;
  }
  review.saving = true;
  updateReviewControls();
  const payload = {
    decision,
    note: qs("note").value,
    duration_ms: Date.now() - review.startedAt,
  };
  if (decision === "rated") payload.feedback = draft.feedback;
  try {
    await postJSON(`/api/evaluations/${item.evaluation_id}/review`, payload);
    delete review.drafts[item.evaluation_id];
    const refreshed = await loadQueue();
    if (refreshed) qs("message").textContent = ({rated: "评价已保存", skipped: "已跳过该样本"})[decision];
  } catch (err) {
    qs("message").textContent = `保存失败：${err.message}`;
  } finally {
    review.saving = false;
    updateReviewControls();
  }
}

function next() {
  if (review.saving || review.loading) return;
  if (review.index < review.items.length - 1) {
    review.index += 1;
    render();
  } else { changePage(review.page + 1); }
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
  if (review.saving || review.loading) return;
  if (review.index > 0) {
    review.index -= 1;
    render();
  } else { changePage(review.page - 1, review.pageSize - 1); }
}

document.addEventListener("keydown", (event) => {
  if (document.body.dataset.stage !== "review" || document.querySelector(".modal:not(.hidden), dialog[open]") || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
  const tag = event.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") {
    if (event.key === "Enter" && event.target.closest(".panel") && tag !== "TEXTAREA") {
      if (event.repeat) return;
      event.preventDefault();
      submit("rated");
    }
    return;
  }
  if (tag === "SELECT" || (tag === "BUTTON" && (!event.target.closest(".image-card") || event.key === "Enter" || event.key === " "))) return;
  const key = event.key.toLowerCase();
  if (event.repeat && (key === "a" || key === "s" || key === "enter")) {
    return;
  }
  if (key === "s") {
    event.preventDefault();
    submit("skipped");
  } else if (key === "j") {
    event.preventDefault();
    next();
  } else if (key === "k") {
    event.preventDefault();
    prev();
  } else if (key === "f") {
    setView("detail");
    review.zoom = 1;
    review.panX = 0;
    review.panY = 0;
    applyTransform();
  } else if (key === "z") {
    event.preventDefault();
    setView("detail");
    review.zoom = review.zoom > 1 ? 1 : 2;
    applyTransform();
  } else if (/^[1-5]$/.test(key)) {
    const input = document.querySelectorAll('input[name="satisfaction"]')[Number(key)-1];
    if (input && !input.disabled) { input.checked = true; input.dispatchEvent(new Event("change", {bubbles:true})); }
  } else if (key === "enter") {
    event.preventDefault();
    submit("rated");
  }
});

window.addEventListener("run-changed", (event) => {
  review.runId = event.detail.runId;
  review.page = 0;
  review.items = [];
  review.index = 0;
  render();
  loadQueue();
});

window.addEventListener("run-status", () => loadQueue());

window.addEventListener("DOMContentLoaded", () => {
  render();
  qs("btn-prev-page").onclick = () => changePage(review.page - 1);
  qs("btn-next-page").onclick = () => changePage(review.page + 1);
  qs("btn-grid").onclick = () => setView("grid");
  qs("btn-detail").onclick = () => setView("detail");
  qs("gallery").onclick = event => {
    const card = event.target.closest(".image-card");
    if (!card || review.saving || review.loading) return;
    review.index = Number(card.dataset.index);
    render();
  };
  qs("gallery").ondblclick = () => { if (current()) setView("detail"); };
  qs("btn-prev").onclick = prev;
  qs("btn-next").onclick = next;
  qs("btn-fit").onclick = () => { setView("detail"); review.zoom = 1; review.panX = review.panY = 0; applyTransform(); };
  qs("btn-zoom").onclick = () => { setView("detail"); review.zoom = review.zoom > 1 ? 1 : 2; applyTransform(); };
  qs("btn-save").onclick = () => submit("rated");
  qs("btn-skip").onclick = () => submit("skipped");
  qs("btn-refresh").onclick = () => loadQueue();
  qs("btn-retry").onclick = () => retryEvaluation();
  qs("filter").onchange = resetQueue;
  qs("order").onchange = resetQueue;
  for (const id of ["satisfaction-options", "positive-points", "negative-points", "note"]) {
    qs(id).addEventListener(id === "note" ? "input" : "change", () => {
      if (!current()) return;
      review.drafts[current().evaluation_id] = readFeedback();
      qs("feedback-points").classList.toggle("hidden", !readFeedback().feedback.rating);
    });
  }
  getJSON("/api/review/options").then(options => {
    review.options = options; review.galleryItems = null; render();
  }).catch(err => { qs("message").textContent = `评价选项加载失败，请刷新：${err.message}`; });

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
