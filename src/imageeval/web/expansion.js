// Short original needs, deliberately separate from PE expansion and image generation.
function randomQueries(count) {
  const pick = values => values[Math.floor(Math.random() * values.length)];
  const groups = [
    ["一个人", "一位年轻女子", "一位老人"].flatMap(person => ["在看演唱会", "双手捧着咖啡杯", "坐在公园长椅上弹吉他", "站在窗边整理围巾"].map(action => person + action)),
    ["一只橘猫", "一只白色小狗", "一只兔子"].flatMap(animal => ["趴在窗台上", "坐在花园里", "在草地上奔跑", "睡在毛毯上"].map(action => animal + action)),
    ["森林", "雪山脚下", "海边"].flatMap(place => ["清晨的" + place, place + "的一间木屋", place + "的小路", "夕阳下的" + place]),
    ["雨后的", "清晨的", "夜晚的"].flatMap(time => ["城市街道", "火车站", "海边小镇", "露天集市"].map(place => time + place)),
    ["一只玻璃香水瓶", "一双运动鞋", "一副无线耳机"].flatMap(item => ["放在白色桌面上", "放在浅灰色背景前", "旁边摆着绿叶", "的产品广告图"].map(scene => item + scene)),
    ["一碗拉面", "一块草莓蛋糕", "一盘饺子"].flatMap(food => ["放在木桌上", "的俯拍照片", "旁边放着一杯茶", "的近景照片"].map(scene => food + scene)),
    ["咖啡店", "书店", "花店"].flatMap(shop => [shop + "开业海报，写着“今日开业”", shop + "的简洁标志", shop + "的门头设计", shop + "的室内设计"]),
    ["一位宇航员", "一个小机器人", "一只穿雨衣的小熊"].flatMap(subject => ["在月球上种花的插画", "在森林里散步的水彩画", "坐在云朵上的童话插画", "骑自行车的漫画"].map(scene => subject + scene)),
  ];
  // Shuffle categories, then sample without replacement within each category.
  for (let i = groups.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [groups[i], groups[j]] = [groups[j], groups[i]];
  }
  return Array.from({length: count}, (_, i) => {
    const group = groups[i % groups.length];
    const query = pick(group);
    group.splice(group.indexOf(query), 1);
    return query;
  });
}
const pe = { result: null, source: null, appliedId: null, busy: false, configured: false };
function savePE() {
  localStorage.setItem("imageeval.pe", JSON.stringify({queries: qs("pe-queries").value, result: pe.result, source: pe.source, appliedId: pe.appliedId}));
}
function peQueries() { return qs("pe-queries").value.split("\n").map(v => v.trim()).filter(Boolean); }
function peMatches() { return pe.result && JSON.stringify(peQueries()) === JSON.stringify(pe.result.items.map(i => i.original_query)); }
function updatePEControls() {
  qs("btn-expand").disabled = pe.busy || !pe.configured;
  qs("btn-expand").textContent = pe.busy ? "正在扩写…" : pe.result ? "重新扩写" : "扩写提示词";
  qs("btn-skip-pe").disabled = pe.busy;
  qs("pe-queries").disabled = pe.busy;
  for (const id of ["pe-random-count", "btn-random-queries", "btn-undo-random"]) qs(id).disabled = pe.busy;
  qs("btn-use-pe").disabled = pe.busy || !peMatches() || pe.result.items.some(i => !i.final_prompt?.trim() || i.final_prompt.trim().length > 1500);
  qs("btn-plan-ab").disabled = qs("btn-use-pe").disabled;
  qs("step-expand-state").textContent = pe.busy ? "扩写中" : peMatches() ? `${pe.result.items.length} 条待确认` : "可跳过";
}
function updatePEContext() {
  qs("generation-pe-context").textContent = pe.source ? `${pe.source.length} 条原始 Query 已保留 · 主评分按原始需求 · ${pe.appliedId ? "使用 PE 扩写" : "直接生图"}` : "未使用 PE · 当前提示词将作为原始 Query";
}
function peDifference(original, expanded) {
  const a = Array.from(original), b = Array.from(expanded);
  const width = b.length + 1;
  const lengths = new Uint16Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--)
    lengths[i * width + j] = a[i] === b[j] ? 1 + lengths[(i + 1) * width + j + 1] : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1]);
  const retained = new Set();
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { retained.add(j); i++; j++; }
    else if (lengths[(i + 1) * width + j] >= lengths[i * width + j + 1]) i++;
    else j++;
  }
  return b.map((ch, index) => retained.has(index) ? escapeHtml(ch) : `<mark>${escapeHtml(ch)}</mark>`).join("");
}
function renderPE() {
  if (!pe.result) return;
  qs("pe-results").innerHTML = pe.result.items.map((item,index) => `<article class="pe-row"><div><span class="section-eyebrow">QUERY ${index+1}</span><p>${escapeHtml(item.original_query)}</p><span class="hint">用户明确提出的要求</span></div><div><label for="pe-result-${index}">扩写提示词 · 可编辑</label><textarea id="pe-result-${index}" data-pe-index="${index}" maxlength="1500">${escapeHtml(item.final_prompt)}</textarea><div class="pe-difference" id="pe-difference-${index}">${peDifference(item.original_query, item.final_prompt)}</div><span class="hint">高亮为文本新增或改写，是否符合意图需人工判断</span>${item.error ? `<p class="over-limit">${escapeHtml(item.error)}，可手动补写或重新扩写。</p>` : ""}<details><summary class="hint">查看模型原始扩写</summary><p class="hint">${escapeHtml(item.expanded_prompt || "未返回有效扩写")}</p></details></div></article>`).join("");
  qs("pe-result-meta").textContent = `${pe.result.model} · 模板 ${pe.result.template_version} · 参数与耗时已保存 · 扩写结果需要人工确认`;
  updatePEControls();
}
function applyPE(useExpanded, compareImages = false) {
  const queries = peQueries();
  if (!queries.length || queries.length > 16 || queries.some(q => q.length > 1500)) {
    qs("pe-message").textContent = "请输入 1–16 条 Query，每条最多 1500 字符。"; return;
  }
  if (generationActive()) { qs("pe-message").textContent = "当前生图任务仍在执行，请完成后再应用新的提示词。"; return; }
  if (useExpanded && !peMatches()) return;
  qs("generation-ab").checked = compareImages;
  pe.source = queries;
  pe.appliedId = useExpanded ? pe.result.id : null;
  const prompts = useExpanded ? pe.result.items.map(i => i.final_prompt.trim()) : queries;
  // One prompt per line is the generation form's contract.
  qs("generation-prompts").value = prompts.map(p => p.replace(/\s*\n\s*/g, " ")).join("\n");
  savePE(); updatePEContext();
  qs("generation-prompts").dispatchEvent(new Event("input", {bubbles: true}));
  showWorkflowStage("generate");
}
function renderPromptProvenance(prefix, info) {
  qs(`${prefix}-pe`).classList.toggle("hidden", !info || info.mode === "direct");
  qs(`${prefix}-generation-prompt`).textContent = info?.generation_prompt || "";
  qs(`${prefix}-pe-meta`).textContent = info ? `${info.model || "手动提示词"} · ${info.template_version || "无 PE 模板"}${info.edited ? " · 已人工修改" : ""}。新增细节仅供诊断，主评分仍按原始 Query。` : "";
}
window.addEventListener("DOMContentLoaded", async () => {
  try {
    const saved = JSON.parse(localStorage.getItem("imageeval.pe") || "null");
    if (saved) { Object.assign(pe, {result:saved.result, source:saved.source, appliedId:saved.appliedId}); qs("pe-queries").value = saved.queries || ""; }
  } catch { localStorage.removeItem("imageeval.pe"); }
  renderPE(); updatePEContext(); updatePEControls();
  qs("pe-queries").oninput = () => {
    savePE(); updatePEControls();
    qs("pe-message").textContent = pe.result && !peMatches() ? "Query 已改变，旧扩写不可应用。请重新扩写或跳过 PE。" : "";
  };
  let beforeRandom = null;
  qs("btn-random-queries").onclick = () => {
    const count = Number(qs("pe-random-count").value);
    if (!Number.isInteger(count) || count < 1 || count > 16) {
      qs("pe-message").textContent = "请输入 1–16 的整数条数。";
      qs("pe-random-count").focus(); return;
    }
    beforeRandom = qs("pe-queries").value;
    qs("pe-queries").value = randomQueries(count).join("\n");
    qs("pe-queries").dispatchEvent(new Event("input", {bubbles:true}));
    qs("btn-undo-random").classList.remove("hidden");
    qs("pe-message").textContent = `已随机生成 ${count} 条场景指令，可编辑后扩写或直接生图。`;
  };
  qs("btn-undo-random").onclick = () => {
    qs("pe-queries").value = beforeRandom;
    qs("pe-queries").dispatchEvent(new Event("input", {bubbles:true}));
    qs("btn-undo-random").classList.add("hidden");
  };
  qs("pe-results").addEventListener("input", event => {
    if (event.target.dataset.peIndex === undefined) return;
    const index = Number(event.target.dataset.peIndex);
    pe.result.items[index].final_prompt = event.target.value;
    qs(`pe-difference-${index}`).innerHTML = peDifference(pe.result.items[index].original_query, event.target.value);
    savePE(); updatePEControls();
  });
  qs("btn-skip-pe").onclick = () => applyPE(false);
  qs("btn-use-pe").onclick = () => applyPE(true);
  qs("btn-plan-ab").onclick = () => applyPE(true, true);
  qs("btn-expand").onclick = async () => {
    const queries = peQueries();
    if (!queries.length || queries.length > 16 || queries.some(q => q.length > 1500)) {
      qs("pe-message").textContent = "请输入 1–16 条 Query，每条最多 1500 字符。"; return;
    }
    pe.busy = true; updatePEControls();
    qs("pe-message").textContent = "正在调用 PE 模型，请保留此页面。此操作只扩写文本，不会生成图片。";
    qs("pe-results").querySelectorAll("textarea").forEach(e => e.disabled = true);
    try {
      const result = await postJSON("/api/expansion", {queries});
      result.items.forEach(item => item.final_prompt = item.expanded_prompt || "");
      pe.result = result;
      renderPE(); savePE();
      qs("pe-message").textContent = `扩写完成：${result.items.filter(i => !i.error).length}/${result.items.length}。请检查新增内容后使用。`;
    } catch (err) { qs("pe-message").textContent = `扩写失败：${err.message}，可跳过 PE 直接生图。`; }
    finally { pe.busy = false; qs("pe-results").querySelectorAll("textarea").forEach(e => e.disabled = false); updatePEControls(); }
  };
  try {
    const config = await getJSON("/api/expansion/config"); pe.configured = config.configured;
    qs("pe-config").textContent = `${config.model || "未配置模型"} · ${config.configured ? "可扩写" : "未配置，可跳过"}${config.uses_judge_config ? " · 当前复用裁判接口，PE 可独立配置" : " · 独立 PE 配置"}`;
  } catch (err) { qs("pe-config").textContent = `PE 配置读取失败：${err.message}`; }
  updatePEControls();
});
