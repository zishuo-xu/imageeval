const preview = { items: [], index: 0, returnFocus: null };
function renderPreview() {
  const item = preview.items[preview.index];
  qs("preview-image").src = `/api/samples/${encodeURIComponent(item.sample_id)}/image?size=orig`;
  qs("preview-image").alt = item.query;
  qs("preview-query").textContent = item.query;
  renderPromptProvenance("preview", item.prompt_expansion);
  qs("preview-checks").innerHTML = visualChecksHTML(item.checks || []);
  qs("preview-position").textContent = `${preview.index + 1} / ${preview.items.length} · ${item.model_name || "导入图片"}`;
  qs("preview-scores").innerHTML = feedbackHTML(item.feedback || item.ai?.feedback);
  qs("preview-original").href = qs("preview-image").src;
  qs("preview-prev").disabled = preview.index === 0;
  qs("preview-next").disabled = preview.index === preview.items.length - 1;
}
window.addEventListener("DOMContentLoaded", () => {
  const storedStage = localStorage.getItem("imageeval.stage");
  if (["expand", "generate", "score", "review", "compare"].includes(storedStage)) showWorkflowStage(storedStage);
  qs("btn-manage-runs").onclick = () => {
    const open = qs("run-builder").classList.toggle("hidden") === false;
    qs("btn-manage-runs").setAttribute("aria-expanded", String(open));
    if (open) qs("run-name").focus();
  };
  const fields = ["generation-name", "generation-prompts", "generation-count", "generation-ratio", "generation-score", "generation-ab"];
  const restore = draft => fields.forEach(id => {
    if (!(id in draft)) return;
    const field = qs(id);
    if (field.type === "checkbox") field.checked = draft[id]; else field.value = draft[id];
  });
  // Malformed browser storage must not prevent the form from opening.
  try {
    const saved = JSON.parse(localStorage.getItem("imageeval.draft") || "null");
    if (saved) { restore(saved); qs("draft-status").textContent = "已恢复本地草稿"; }
  } catch { localStorage.removeItem("imageeval.draft"); }
  const save = () => {
    const draft = Object.fromEntries(fields.map(id => [id, qs(id).type === "checkbox" ? qs(id).checked : qs(id).value]));
    localStorage.setItem("imageeval.draft", JSON.stringify(draft));
    qs("draft-status").textContent = "草稿已自动保存";
    if (!generationActive()) qs("generation-message").textContent = "";
  };
  qs("generation-form").addEventListener("input", save);
  qs("generation-form").addEventListener("change", save);
  qs("generation-prompts").dispatchEvent(new Event("input"));
  qs("btn-reuse-prompts").onclick = () => {
    if (!generation.job || generationActive()) return;
    if (qs("generation-prompts").value.trim() && !window.confirm("用上次任务的提示词和参数替换当前草稿？")) return;
    const request = generation.job.request;
    restore({"generation-name":request.name, "generation-prompts":request.prompts.join("\n"), "generation-count":request.images_per_prompt, "generation-ratio":request.aspect_ratio, "generation-score":request.auto_score});
    qs("generation-ab").checked = !!request.ab_compare;
    pe.source = request.original_queries || null;
    pe.appliedId = request.expansion_id || null;
    qs("pe-queries").value = (request.original_queries || request.prompts).join("\n");
    savePE();
    updatePEContext();
    qs("generation-prompts").dispatchEvent(new Event("input", {bubbles:true}));
    qs("generation-prompts").focus();
  };
  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-preview]");
    if (!trigger) return;
    preview.items = trigger.dataset.preview === "compare" ? comparison.previewItems : trigger.dataset.preview === "generate" ? generation.items : scoring.items;
    preview.index = Number(trigger.dataset.index);
    preview.returnFocus = trigger;
    renderPreview();
    qs("preview-dialog").showModal();
    qs("preview-close").focus();
  });
  qs("preview-close").onclick = () => qs("preview-dialog").close();
  qs("preview-dialog").addEventListener("close", () => preview.returnFocus?.focus());
  qs("preview-prev").onclick = () => { if (preview.index > 0) { preview.index--; renderPreview(); } };
  qs("preview-next").onclick = () => { if (preview.index + 1 < preview.items.length) { preview.index++; renderPreview(); } };
  qs("preview-dialog").addEventListener("keydown", event => {
    if (event.key === "ArrowLeft") { event.preventDefault(); qs("preview-prev").click(); }
    if (event.key === "ArrowRight") { event.preventDefault(); qs("preview-next").click(); }
  });
});
