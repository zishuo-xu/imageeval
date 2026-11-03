(function () {
  const data = window.__REPORT_DATA__;
  if (!data) return;
  const dims = ["adherence", "quality", "aesthetics"];
  const dimNames = { adherence: "需求遵循", quality: "视觉质量", aesthetics: "美学" };
  const colors = { adherence: "#7c9cff", quality: "#4ecdc4", aesthetics: "#ffb86b" };

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));

  const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%");

  document.getElementById("run-title").textContent = data.run.name || "评测报告";
  document.getElementById("run-meta").textContent =
    `${data.run.rubric_version} · ${data.run.judge_model} · ${data.counts.total} 张`;

  const exportButton = document.getElementById("btn-export-report");
  if (window.__STATIC_REPORT__) {
    exportButton.style.display = "none";
  } else {
    exportButton.addEventListener("click", async () => {
      exportButton.disabled = true;
      try {
        const response = await fetch("/api/reports/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ run_id: data.run.id }),
        });
        if (!response.ok) throw new Error(await response.text());
        const result = await response.json();
        const link = document.createElement("a");
        link.href = result.url;
        link.download = "";
        document.body.appendChild(link);
        link.click();
        link.remove();
      } catch (err) {
        alert(`导出失败：${err.message}`);
      } finally {
        exportButton.disabled = false;
      }
    });
  }

  const cards = [
    ["样本数", data.counts.total],
    ["已评分", data.counts.ok],
    ["AI 待复核", data.counts.ai_done],
    ["已复核", data.counts.reviewed],
    ["错误", data.counts.error],
    ["人工满意率", pct(data.feedback.human.satisfied_rate)],
  ];
  document.getElementById("cards").innerHTML = cards
    .map(([label, value]) => `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`)
    .join("");

  document.getElementById("feedback-distribution").innerHTML = ["ai", "human"].map(source => {
    const summary = data.feedback[source];
    return `<div class="card"><h3>${source === "ai" ? "AI 评价" : "人工评价"} · ${summary.total} 张</h3><p>满意率 ${pct(summary.satisfied_rate)}</p><table><tr><th>满意度</th><th>数量</th></tr>${Object.entries(summary.ratings).map(([label,count]) => `<tr><td>${escapeHtml(label)}</td><td>${count}</td></tr>`).join("")}</table></div>`;
  }).join("");
  document.getElementById("feedback-reasons").innerHTML = ["ai", "human"].map(source => `<div class="card"><h3>${source === "ai" ? "AI" : "人工"} 反馈点</h3>${[["positive_points","满意的点"],["negative_points","不满意的点"]].map(([key,title]) => `<h4>${title}</h4>${Object.entries(data.feedback[source][key]).map(([point,count])=>`<p>${escapeHtml(point)}：${count} 张</p>`).join("") || "暂无反馈"}`).join("")}</div>`).join("");
  const sampleRows = data.samples.map(s => `<tr><td>${escapeHtml(s.query)}</td><td>${escapeHtml(s.ai.feedback?.rating || "未评价")}</td><td>${escapeHtml(s.human.feedback?.rating || "未评价")}</td><td>${escapeHtml((s.human.feedback?.positive_points || []).join("、"))}</td><td>${escapeHtml((s.human.feedback?.negative_points || []).join("、"))}</td></tr>`).join("");
  document.getElementById("sample-table").innerHTML = `<tr><th>Query</th><th>AI 评价</th><th>人工评价</th><th>满意点</th><th>不满意点</th></tr>${sampleRows}`;
})();
