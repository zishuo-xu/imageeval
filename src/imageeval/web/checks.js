const visualCheckLabels = {finger_count:"手指数量",hand_structure:"手掌 / 手指结构",limb_count:"肢体数量",joint_connection:"关节与连接",face_structure:"面部五官",body_proportion:"身体比例",object_structure:"物体结构",text_legibility:"文字准确性",edge_integrity:"边缘与融合",contact_occlusion:"接触与遮挡",light_perspective:"光影与透视",surface_texture:"表面细节"};
const visualStatus = {pass:"未见异常 · 5",minor:"轻微缺陷 · 4",major:"明显缺陷 · 2",severe:"严重缺陷 · 1",unassessable:"无法判定",not_applicable:"不适用"};
function visualCheckSummary(checks) {
  if (!checks.length) return "未记录细项检查";
  const count = status => checks.filter(c => c.status === status).length;
  return `严重 ${count("severe")} · 明显 ${count("major")} · 轻微 ${count("minor")} · 无法判定 ${count("unassessable")}`;
}
function visualChecksHTML(checks) {
  if (!checks.length) return '<p class="hint">此结果没有细项检查记录，不代表没有缺陷。可按新规则另建评测。</p>';
  const order = {severe:0,major:1,minor:2,unassessable:3,pass:4,not_applicable:5};
  const cap = checks.some(c=>c.status==="severe") ? 2 : checks.some(c=>c.status==="major") ? 3 : checks.some(c=>c.status==="minor") ? 4 : null;
  return `<p class="hint">${visualCheckSummary(checks)}${cap ? `。质量总分上限 ${cap}/5。` : "。"}遮挡或不可见不算缺陷。</p>` + [...checks].sort((a,b)=>order[a.status]-order[b.status]).map(c=>`<details class="visual-check ${c.status}" ${["major","severe","minor"].includes(c.status)?"open":""}><summary><strong>${escapeHtml(visualCheckLabels[c.key] || c.key)}</strong><span>${escapeHtml(visualStatus[c.status])}</span></summary><p><b>位置：</b>${escapeHtml(c.location)}<br><b>证据：</b>${escapeHtml(c.evidence)}</p></details>`).join("");
}

function feedbackHTML(feedback) {
  if (!feedback) return '<span class="hint">尚无评价</span>';
  return `<strong class="feedback-rating">${escapeHtml(feedback.rating)}</strong><div class="feedback-detail"><p class="feedback-positive">满意：${escapeHtml(feedback.positive_points.join("、") || "未选择")}</p><p class="feedback-negative">不满意：${escapeHtml(feedback.negative_points.join("、") || "未选择")}</p>${feedback.explanation ? `<p class="hint">${escapeHtml(feedback.explanation)}</p>` : ""}</div>`;
}
