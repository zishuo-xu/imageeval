(function () {
  const data = window.__REPORT_DATA__;
  if (!data) return;
  const dims = ["adherence", "quality", "aesthetics"];
  const dimNames = { adherence: "需求遵循", quality: "视觉质量", aesthetics: "美学" };
  const colors = { adherence: "#7c9cff", quality: "#4ecdc4", aesthetics: "#ffb86b" };

  const fmt = (v) => (v === null || v === undefined ? "—" : Number(v).toFixed(2));
  const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%");

  document.getElementById("run-title").textContent = data.run.name || "评测报告";
  document.getElementById("run-meta").textContent =
    `${data.run.rubric_version} · ${data.run.judge_model} · ${data.counts.total} 张`;

  const cards = [
    ["样本数", data.counts.total],
    ["已评分", data.counts.ok],
    ["AI 待复核", data.counts.ai_done],
    ["已复核", data.counts.reviewed],
    ["错误", data.counts.error],
    ["人工接受率", pct(data.acceptance_rate)],
  ];
  document.getElementById("cards").innerHTML = cards
    .map(([label, value]) => `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`)
    .join("");

  const agreementCards = [];
  for (const dim of dims) {
    agreementCards.push(`<div class="card"><div class="label">${dimNames[dim]} MAE</div><div class="value">${fmt(data.agreement.mae[dim])}</div></div>`);
    agreementCards.push(`<div class="card"><div class="label">${dimNames[dim]} Spearman</div><div class="value">${fmt(data.agreement.spearman[dim])}</div></div>`);
  }
  agreementCards.push(`<div class="card"><div class="label">已复核样本</div><div class="value">${data.agreement.n}</div></div>`);
  document.getElementById("agreement-cards").innerHTML = agreementCards.join("");

  for (const dim of dims) {
    new Chart(document.getElementById(`chart-${dim}`), {
      type: "bar",
      data: {
        labels: ["1", "2", "3", "4", "5"],
        datasets: [
          { label: "AI", data: data.distributions[dim].ai, backgroundColor: colors[dim] },
          { label: "人工", data: data.distributions[dim].human, backgroundColor: "#8b93a7" },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          title: { display: true, text: `${dimNames[dim]}分布` },
          legend: { position: "bottom" },
        },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }

  new Chart(document.getElementById("chart-radar"), {
    type: "radar",
    data: {
      labels: data.radar.labels,
      datasets: [
        { label: "AI", data: data.radar.ai, borderColor: "#7c9cff", backgroundColor: "rgba(124,156,255,.2)" },
        { label: "人工", data: data.radar.human, borderColor: "#ffb86b", backgroundColor: "rgba(255,184,107,.2)" },
      ],
    },
    options: { scales: { r: { min: 1, max: 5 } } },
  });

  new Chart(document.getElementById("chart-scatter"), {
    type: "scatter",
    data: {
      datasets: dims.map((dim) => ({
        label: dimNames[dim],
        data: data.agreement.scatter.filter((p) => p.dim === dim).map((p) => ({ x: p.ai, y: p.human })),
        backgroundColor: colors[dim],
      })),
    },
    options: {
      plugins: { title: { display: true, text: "AI vs 人工" } },
      scales: {
        x: { min: 0.5, max: 5.5, title: { display: true, text: "AI 分" } },
        y: { min: 0.5, max: 5.5, title: { display: true, text: "人工分" } },
      },
    },
  });

  const attrRows = data.attribution.by_category
    .map((row) => `<tr><td>${row.category}</td><td>${row.total}</td><td>${row.failed}</td><td>${pct(row.failure_rate)}</td></tr>`)
    .join("");
  document.getElementById("table-attribution").innerHTML =
    `<tr><th>类别</th><th>需求数</th><th>失败数</th><th>失败率</th></tr>${attrRows}`;
  document.getElementById("status-counts").textContent = Object.entries(data.attribution.status_counts)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");

  document.getElementById("confusion").innerHTML = dims
    .map((dim) => {
      const rows = data.agreement.confusion[dim]
        .map((row, i) => `<tr><td>${i + 1}</td>${row.map((v) => `<td>${v}</td>`).join("")}</tr>`)
        .join("");
      return `<div class="card"><div class="label">${dimNames[dim]}</div><table><tr><th>AI\\人工</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th></tr>${rows}</table></div>`;
    })
    .join("");

  document.getElementById("failure-wall").innerHTML = data.failures
    .map((item) => `
      <div class="card">
        <img src="${item.image}" alt="">
        <div class="hint">${item.query}</div>
        <div>人工 ${fmt(item.human_overall)} / AI ${fmt(item.ai_overall)}</div>
      </div>`)
    .join("") || '<div class="hint">暂无失败案例</div>';

  const sampleRows = data.samples
    .map((s) => `<tr><td>${s.query}</td><td>${fmt(s.ai.overall)}</td><td>${fmt(s.human.overall)}</td></tr>`)
    .join("");
  document.getElementById("sample-table").innerHTML =
    `<tr><th>Query</th><th>AI 总分</th><th>人工总分</th></tr>${sampleRows}`;
})();
