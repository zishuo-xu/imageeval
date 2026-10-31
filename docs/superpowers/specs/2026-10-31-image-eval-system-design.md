# 生图模型评测系统 · 设计文档

- 日期：2026-10-31
- 状态：已确认（架构 / 数据模型 / 评分体系 / 工作流 / 报告 / 导出）
- 目标：对「原始 Query + 生成图片」做需求遵循、视觉质量、美学三维评测，产出结构化结果与可视化报告，支持人工复核与标注数据积累，为后续评测模型训练与自动化迭代提供数据基础。

## 1. 范围

### 1.1 本期做

- 本地单机 Web 工具（FastAPI + SQLite + 无构建前端），单人/小团队使用
- 数据导入（CSV / JSONL + 图片目录或 URL），百~千张量级
- 云端多模态 API 自动评分（OpenAI 兼容多模态接口，Provider 可插拔）
- 三维度评分：需求遵循、视觉质量、美学；需求遵循采用「先拆原子需求、再判状态、分数本地计算」
- AI 预标注 + 人工确认/修正的工作流，AI 分与人工分双轨存储
- 可视化报告：分布、一致性、需求归因、失败案例
- 训练数据导出（raw / sft / only-reviewed；gold / silver 标签分级）

### 1.2 本期不做（明确排除）

- 多用户登录、权限、任务分配、双盲审核
- 跨模型横向对比视图（`samples.model_name` 字段保留，仅作元数据/筛选）
- 参考图 / 图像编辑任务的评分（`ref_image_path` 列保留，本期不参与评分）
- 万张级任务队列与分布式 worker
- 应用内 rubric 编辑器
- pairwise 偏好标注
- 评测模型本身的训练（本期只产出训练数据）

## 2. 总体架构

```
浏览器（标注台 / 报告页）
        │ HTTP JSON
        ▼
FastAPI（同进程托管静态页面与图片）
   ├── import API ──► SQLite (WAL)
   ├── run API ─────► Pipeline（asyncio 后台任务：限流 / 重试 / 断点续跑）
   │                        │
   │                        ▼
   │                 Judge Provider（OpenAI 兼容多模态）
   │                 base_url + model + key(仅环境变量)
   ├── review API ──► reviews 表（append-only）
   └── report API ──► 聚合统计 + 静态 HTML 导出
```

三条解耦边界：

1. **裁判可替换**：所有模型调用经 `JudgeProvider` 协议，替换裁判不改业务代码。
2. **标准可版本化**：评分标准在 `rubric/v*.yaml`，每次评测记录版本与 prompt 哈希，历史结果可复现。
3. **分数双轨**：`evaluations`（AI）与 `reviews`（人工）物理分离，人工分永不覆盖 AI 分。

## 3. 目录结构

```
.
├── pyproject.toml                # uv 管理；Python 3.14
├── config.example.toml           # 配置模板（不含密钥）
├── README.md
├── docs/superpowers/specs/       # 本文档
├── src/imageeval/
│   ├── __main__.py               # CLI：serve / import / run / export / report
│   ├── config.py                 # TOML 加载 + 环境变量覆盖 + 校验
│   ├── db.py                     # SQLite 连接、迁移、事务辅助
│   ├── models.py                 # pydantic 模型与 JSON 契约
│   ├── storage.py                # 路径安全解析、缩略图生成、图片校验
│   ├── util.py                   # UTC 时间戳等通用工具
│   ├── importer.py               # CSV/JSONL 导入、图片落盘、逐行校验
│   ├── runs.py                   # run 创建与查询
│   ├── scoring.py                # 确定性分数聚合（纯函数，可单测）
│   ├── pipeline.py               # 批量评分任务（限流、重试、续跑、进度）
│   ├── review.py                 # 复核状态推导、一致性统计
│   ├── report.py                 # 聚合统计、静态报告渲染
│   ├── export.py                 # 训练数据导出（raw / sft / only-reviewed）
│   ├── api.py                    # FastAPI 路由
│   ├── judge/
│   │   ├── base.py               # JudgeProvider Protocol + 共享类型
│   │   ├── openai_compat.py      # OpenAI 兼容多模态客户端
│   │   ├── prompts.py            # 提示词模板 + PROMPT_VERSION
│   │   └── fake.py               # 测试用确定性 Provider
│   ├── rubric/
│   │   ├── v1.yaml               # rubric v1 定义
│   │   └── loader.py             # 加载、校验、版本读取
│   └── web/                      # 原生 JS，无构建步骤
│       ├── index.html            # 标注台
│       ├── report.html           # 报告页
│       ├── app.js  review.js  report.js  api.js
│       ├── style.css
│       └── vendor/chart.umd.js   # 本地 vendored Chart.js
├── data/                         # 运行时数据（默认 ./data，可用 --data-dir 覆盖）
│   ├── imageeval.db
│   ├── images/                   # 原图（导入时拷入或下载）
│   ├── thumbs/                   # 缩略图缓存
│   ├── exports/
│   └── reports/
└── tests/
```

运行时依赖：`fastapi`、`uvicorn`、`httpx`、`pydantic`、`pyyaml`、`pillow`、`python-multipart`；开发依赖：`pytest`、`pytest-asyncio`。

## 4. 数据模型

SQLite，开启 WAL 与外键。所有时间戳为 UTC ISO-8601 字符串。

### 4.1 `schema_version`

| 列 | 类型 | 说明 |
|---|---|---|
| version | INTEGER PK | 当前 schema 版本；启动时按顺序执行幂等迁移 |

### 4.2 `import_batches`

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID |
| source_name | TEXT | 原始文件名 |
| created_at | TEXT | |
| sample_count | INTEGER | 成功导入条数 |
| rejected_count | INTEGER | 拒绝条数 |
| report_json | TEXT | 逐行校验结果 |

### 4.3 `samples`

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID |
| batch_id | TEXT FK | |
| external_id | TEXT | 调用方 ID；同批次内唯一 |
| query_text | TEXT NOT NULL | 原始 Query |
| image_path | TEXT NOT NULL | 相对 `data/images` 的路径 |
| thumb_path | TEXT | 相对 `data/thumbs` 的路径 |
| ref_image_path | TEXT NULL | 预留，本期不参与评分 |
| model_name | TEXT NULL | 元数据，不做对比视图 |
| width / height | INTEGER | 原图尺寸 |
| tags_json | TEXT | 标签数组 |
| metadata_json | TEXT | 任意附加元数据 |
| created_at | TEXT | |

唯一约束：`UNIQUE(batch_id, external_id)`。

### 4.4 `runs`

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID |
| name | TEXT | |
| batch_id | TEXT FK | 所属导入批次 |
| rubric_version | TEXT NOT NULL | 如 `v1` |
| prompt_hash | TEXT NOT NULL | 提示词模板 SHA-256 前 16 位 |
| provider | TEXT NOT NULL | provider 名称 |
| judge_model | TEXT NOT NULL | 模型标识 |
| params_json | TEXT | 温度、最大边、限流参数等快照 |
| status | TEXT | `pending` / `running` / `paused` / `completed` / `failed` / `cancelled` |
| total | INTEGER | 目标样本数 |
| done | INTEGER | 成功数 |
| failed | INTEGER | 失败数 |
| created_at / started_at / finished_at | TEXT | |
| usage_json | TEXT | 汇总 tokens 与耗时 |

### 4.5 `evaluations`（AI 产出，只增不改）

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID |
| sample_id | TEXT FK | |
| run_id | TEXT FK | |
| status | TEXT | `ok` / `error` |
| adherence_score | REAL NULL | 1–5，两位小数 |
| quality_score | REAL NULL | 1–5，两位小数 |
| aesthetics_score | REAL NULL | 1–5，两位小数 |
| overall_score | REAL NULL | 加权总分 |
| requirements_json | TEXT | 原子需求清单（含状态与证据） |
| subscores_json | TEXT | 各子项分数与理由 |
| observation | TEXT | 先观察后评分的画面描述 |
| verdict | TEXT | 一句话结论 |
| raw_response | TEXT | 未修改的原始响应 |
| parse_attempts | INTEGER | 解析尝试次数（1 或 2） |
| error | TEXT NULL | 失败原因 |
| latency_ms | INTEGER | |
| tokens_in / tokens_out | INTEGER | |
| created_at | TEXT | |

唯一约束：`UNIQUE(sample_id, run_id)`（续跑与幂等的基础）。

### 4.6 `reviews`（人工产出，append-only）

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID |
| evaluation_id | TEXT FK | |
| reviewer | TEXT | 复核人标识（本地默认 `local`） |
| decision | TEXT | `accepted` / `corrected` / `skipped` |
| human_adherence | INTEGER NULL | 1–5 整数 |
| human_quality | INTEGER NULL | 1–5 整数 |
| human_aesthetics | INTEGER NULL | 1–5 整数 |
| human_overall | REAL NULL | 用与 AI 相同的权重计算 |
| reasons_json | TEXT | 被修改维度的可选理由 |
| note | TEXT | 备注 |
| duration_ms | INTEGER | 从渲染到保存的耗时 |
| created_at | TEXT | |

不设唯一约束：同一 evaluation 可被多次复核（例如不同人、不同时间），**最新一条为当前 gold**，历史全部保留用于分歧分析。

## 5. 评分体系（rubric v1）

### 5.1 评分尺度

所有子项 1–5 整数，锚点：

| 分 | 含义 |
|---|---|
| 1 | 严重问题，不可用 |
| 2 | 明显问题，需要重做 |
| 3 | 基本可用，存在可见瑕疵 |
| 4 | 良好，仅有轻微瑕疵 |
| 5 | 优秀，无明显问题 |

### 5.2 需求遵循（权重 0.40）

**流程：先拆解，后判定，分数本地计算。**

1. 模型把 Query 拆成原子需求，每条包含：
   - `text`：需求原文/改写
   - `category`：`subject` / `attribute` / `count` / `relation` / `style` / `text_render` / `negative`
   - `criticality`：`critical`（主体、数量、明确的否定约束等不满足则任务失败）或 `normal`
   - `status`：`satisfied` / `partial` / `missing` / `contradicted`
   - `evidence`：图中支持该判定的简短描述
2. 本地计算（`scoring.aggregate_adherence`）：

```
v = satisfied: 1.0 | partial: 0.5 | missing: 0.0 | contradicted: 0.0
w = critical: 3 | normal: 1
ratio      = Σ(w_i · v_i) / Σ(w_i)
atomic_5   = 1 + 4 × ratio
若存在任一 critical 需求为 contradicted：atomic_5 = min(atomic_5, 3.0)   # 关键需求冲突封顶
adherence  = 0.75 × atomic_5 + 0.25 × intent_alignment
```

   - `intent_alignment`：模型给出的整体意图贴合度，1–5 整数（占 25%），用于捕捉「细节全对但意图跑偏」。
   - 所有需求均为 `satisfied` 且意图分为 5 时，维度分为 5。
3. 需求状态按 `category` 聚合只用于报告归因，不参与总分。

### 5.3 视觉质量（权重 0.35）

| 子项 | 权重 | 关注点 |
|---|---|---|
| clarity | 0.20 | 清晰度、锐度、细节完整性 |
| artifacts | 0.30 | 伪影、解剖畸变（手/脸/肢体）、结构融合错误 |
| text_render | 0.10 | 文字/符号/UI 元素是否乱码或伪文字；不适用时标 N/A |
| physics | 0.20 | 透视、光影一致、遮挡、比例合理 |
| consistency | 0.20 | 风格与材质是否局部割裂 |

维度分 = 适用子项按权重重归一后的加权平均，保留两位小数。

### 5.4 美学（权重 0.25）

| 子项 | 权重 | 关注点 |
|---|---|---|
| composition | 0.20 | 构图、视觉引导、主体关系 |
| color | 0.20 | 色彩和谐、配色品味 |
| lighting | 0.20 | 光影、氛围 |
| texture | 0.20 | 质感与细节丰富度 |
| appeal | 0.20 | 整体吸引力与记忆点 |

维度分 = 适用子项均值，保留两位小数。

### 5.5 总分

```
overall = 0.40 × adherence + 0.35 × quality + 0.25 × aesthetics
```

所有权重（维度权重与子项权重）只存在一处：`rubric/v*.yaml`。修改任何权重即发布新的 rubric 版本，历史 run 按自身版本复算，不受影响。

### 5.6 Judge 输出契约

严格 JSON，经 pydantic 校验：

```json
{
  "observation": "画面内容的客观描述，先观察后评分",
  "requirements": [
    {"text": "红色雨伞", "category": "attribute", "criticality": "critical",
     "status": "satisfied", "evidence": "画面中央偏左有一把红色雨伞"}
  ],
  "intent_alignment": 4,
  "subscores": {
    "quality": {
      "clarity": {"score": 4, "reason": "…"},
      "artifacts": {"score": 3, "reason": "左手手指数量异常"},
      "text_render": {"score": null, "reason": "画面无文字要求", "na": true},
      "physics": {"score": 4, "reason": "…"},
      "consistency": {"score": 4, "reason": "…"}
    },
    "aesthetics": {
      "composition": {"score": 4, "reason": "…"},
      "color": {"score": 5, "reason": "…"},
      "lighting": {"score": 4, "reason": "…"},
      "texture": {"score": 3, "reason": "…"},
      "appeal": {"score": 4, "reason": "…"}
    }
  },
  "notable_issues": ["左手手指异常"],
  "verdict": "整体符合要求，手部存在轻微畸变"
}
```

约束：

- `requirements` 非空，且至少含一条 `critical`（模型须判定哪条最关键；无法判定时选影响最大的一条）。
- 子项不适用时 `score` 为 `null`、`na` 为 `true`；**该维度适用子项少于一半时整维度记为 error**（避免空维度算出假分）。
- `score` 必须是 1–5 整数（模型输出小数则四舍五入到最近整数）。
- 解析或校验失败 → 带错误摘要重试一次；仍失败则 `status=error`，保存原始响应与错误信息，样本保留可单独重试。

## 6. 自动评分流水线

- **导入**：`POST /api/import` 接收 CSV/JSONL 与选项（`image_root`、是否下载 URL）。逐行校验 query 非空、图片存在且可解码、`external_id` 批内唯一。坏行写入 batch 报表并跳过，不阻塞好行。导入时将图片拷贝（或下载）到 `data/images/{batch_id}/`，生成最长边 480px 缩略图。
- **启动**：`POST /api/runs/{id}/start` 创建异步任务；`asyncio.Semaphore(max_concurrency=4)` 控制并发，令牌桶限制 RPM（默认 60）。
- **重试**：429 / 5xx / 超时按指数退避 + 随机抖动重试，最多 3 次；单次调用超时 90s。
- **断点续跑**：再次 start 时仅处理无 `ok` 记录的样本；`error` 样本可单独重试。
- **暂停/取消**：停止派发新任务，在途请求自然结束，状态落库。
- **进度**：`runs` 表计数持续更新，前端每 2s 轮询。
- **图片预处理**：送 API 前将最长边缩放到 `image_max_edge`（默认 1280px），以 base64 data URL 内联；原图保留供人工复核。
- **成本**：累计 `tokens_in` / `tokens_out` / `latency_ms`，run 结束写入 `usage_json`。

## 7. 人工复核工作流

### 7.1 状态推导（不额外存字段）

| 状态 | 条件 |
|---|---|
| `unscored` | 无 evaluation |
| `error` | 最新 evaluation 为 `error` |
| `ai_done` | evaluation 为 `ok` 且无 review |
| `accepted` | 最新 review 为 `accepted` |
| `corrected` | 最新 review 为 `corrected` |
| `skipped` | 最新 review 为 `skipped` |

### 7.2 标注台

```
┌──────────────────────────┬─────────────────────────┐
│                          │ Query 原文（可高亮）       │
│   图片（滚轮缩放/拖拽平移， │─────────────────────────│
│   F 适应，Z 100% 切换）    │ AI 需求清单：状态色 + 证据  │
│                          │─────────────────────────│
│                          │ 三维分输入（预填 AI 分）    │
│                          │ 子项理由（折叠）           │
│                          │ [接受全部][保存修正][跳过]  │
└──────────────────────────┴─────────────────────────┘
```

- 预标注模式：分数输入预填 AI 值，接受=一键；修正=改数字 + 可选理由。
- 需求清单只读（作为判定证据）；人工直接改三维总分，避免改状态后重算带来的歧义。
- 快捷键：`A` 接受 / `J` `K` 上一条下一条 / `1–5` 给当前聚焦维度打分 / `Tab` 切换维度 / `Enter` 保存 / `S` 跳过 / `F` 适应窗口。
- 筛选预设：待复核、AI 低分优先、修正幅度最大、随机；支持 query 关键词与标签过滤。
- 每条记录 `duration_ms`（页面渲染 → 保存），用于标注质量与成本分析。

## 8. 可视化报告

App 内报告页；支持一键导出**单文件 HTML**（缩略图 base64、数据内嵌、离线可分享）。

| 模块 | 内容 |
|---|---|
| 概览 | 样本数、已评/待复核、AI 均分 vs 人工均分、人工接受率 |
| 分布 | 三维度直方图（AI 与人工叠加）、三维度雷达图 |
| 一致性 | 每维度 MAE、Spearman ρ（n≥3 才计算）、整数分混淆矩阵、AI-vs-人工散点（含抖动） |
| 需求归因 | 原子需求状态分布；按 category 的失败率排序（satisfied 以外均计失败） |
| 失败案例墙 | 人工最低分 Top-N 与修正幅度最大 Top-N；缩略图 + 主要失败类别 |
| 明细 | 可筛选表格，点击跳转标注台定位到该样本 |

统计口径：

- 一致性只用「已复核」样本；人工侧取最新 review。
- MAE 用 AI 浮点分与人工整数的绝对差。
- 混淆矩阵把 AI 分四舍五入为整数后与人工整数比对。
- 均分展示同时给出 AI（全量已评）与人工（已复核子集），避免混淆。

## 9. 训练数据导出

`POST /api/export/dataset`，生成 `data/exports/{run_id}_{mode}_{timestamp}/`：

- `dataset.jsonl`：每样本一行
- `manifest.json`：run 元信息、rubric 版本、prompt 哈希、judge 配置、样本数、图片清单相对路径、导出时间
- 可选 `images/`：复制引用的原图

```json
{
  "sample_id": "…",
  "query": "…",
  "image": "images/…/x.png",
  "model_name": "…",
  "tags": ["…"],
  "rubric_version": "v1",
  "prompt_hash": "…",
  "judge": {"provider": "openai_compat", "model": "…"},
  "ai": {
    "adherence": 4.25, "quality": 3.8, "aesthetics": 4.2, "overall": 4.08,
    "requirements": [ … ], "subscores": { … }, "verdict": "…"
  },
  "human": {
    "adherence": 4, "quality": 4, "aesthetics": 4, "overall": 4.0,
    "reasons": { … }, "note": "…", "reviewer": "local", "decision": "corrected"
  },
  "final": {"scores": { … }, "source": "human", "label_quality": "gold"},
  "meta": {"created_at": "…", "review_duration_ms": 18300}
}
```

导出模式：

| 模式 | 内容 | 用途 |
|---|---|---|
| `raw` | AI + 人工双轨全量 | 保存完整标注事实 |
| `sft` | query + image → 人工标注 JSON（仅 gold） | 直接用于评测模型 SFT |
| `only-reviewed` | 仅已复核样本的 raw 格式 | 高质量子集 |

`label_quality`：人工复核过 = `gold`；仅 AI = `silver`。**默认导出不混用**，需显式指定。人工未复核的样本在 `sft` 模式中不出现。

## 10. 错误处理与安全

- **路径安全**：图片服务只允许 `data/images` 与 `data/thumbs` 真实路径下的文件；启动时 `realpath` 校验，拒绝任何穿越。
- **图片校验**：导入时用 Pillow 解码验证，拒绝非图片或损坏文件。
- **密钥**：只从环境变量读取（变量名由 `config.toml` 指定，如 `IMAGEEVAL_API_KEY`），配置文件中不出现密钥；日志与错误信息中不打印请求头。
- **不丢数据**：任何裁判失败均保留样本与错误详情；`raw_response` 全量落库。
- **幂等**：`evaluations` 唯一约束保证重复启动不会重复计费。
- **并发安全**：SQLite 使用 WAL；写操作通过单连接或短事务串行化，避免 `database is locked`。
- **失败可观测**：run 页展示失败样本列表与错误类别，支持单条重试。

## 11. 测试策略

- 单元测试：
  - `scoring.aggregate_adherence`：critical/normal 权重、partial 记分、contradicted 封顶、全 satisfied 上限
  - 子项 N/A 重归一、空维度判错
  - rubric YAML 加载与版本校验
  - JSON 契约解析与「解析失败 → 单次重试 → error」路径
  - 导入校验（重复 external_id、坏图、空 query）
  - 复核状态推导与最新 review 选取
  - 一致性统计（MAE、Spearman、混淆矩阵）
  - 导出三种模式与 gold/silver 过滤
- Provider 测试：`httpx.MockTransport` 模拟 429/5xx/超时/坏 JSON，验证退避与重试次数。
- 端到端：`FakeProvider` 返回确定性结果，跑通 导入 → 评分 → 复核 → 报告 → 导出。
- 测试**永不**发起真实网络请求。

## 12. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/import` | multipart 上传 CSV/JSONL；参数 `image_root`、`download`；返回 batch 与校验报告 || GET | `/api/batches` | 批次列表 |
| GET | `/api/batches/{id}/report` | 逐行导入校验结果 |
| GET | `/api/samples` | 筛选：`batch_id`、`state`、`q`、`tag`、`limit`、`offset` |
| GET | `/api/samples/{id}` | 样本详情（最新 evaluation + 最新 review） |
| GET | `/api/samples/{id}/image?size=orig\|thumb` | 原图 / 缩略图 |
| POST | `/api/runs` | 创建 run：`{name, batch_id}` |
| GET | `/api/runs` / `/api/runs/{id}` | 列表 / 进度 |
| POST | `/api/runs/{id}/start\|pause\|cancel` | 控制执行 |
| POST | `/api/evaluations/{id}/retry` | 单条重试 |
| GET | `/api/review/queue` | 复核队列：`run_id`、`filter`、`order`、`limit`，返回当前项与进度 |
| POST | `/api/evaluations/{id}/review` | 提交复核：`decision`、三维分、`reasons`、`note`、`duration_ms` |
| GET | `/api/reports/summary` | 报告数据：`run_id` |
| POST | `/api/reports/export` | 生成单文件 HTML：`{run_id, include_images}` |
| POST | `/api/exports/dataset` | 导出训练数据：`{run_id, mode}` |
| GET | `/api/exports/{id}/download` | 下载导出产物（目录打包为 zip） |

## 13. CLI

```
python -m imageeval serve   [--config config.toml] [--data-dir data] [--host 127.0.0.1] [--port 8765]
python -m imageeval import  <file.csv|file.jsonl> [--image-root DIR] [--download]
python -m imageeval run     (--run-id <id> | --new --batch-id <id> --name <name>)   # 无头执行
python -m imageeval report  --run-id <id> --out data/reports/
python -m imageeval export  --run-id <id> --mode sft|raw|only-reviewed
```

`--run-id` 执行已存在的 run；`--new` 按批次创建 run 并立即执行。CLI 与 HTTP API 共用同一服务层。

CLI 与 HTTP API 共用同一服务层，便于未来自动化调用。

## 14. 配置（config.example.toml）

```toml
[server]
host = "127.0.0.1"
port = 8765

[judge]
provider = "openai_compat"
base_url = "https://your-endpoint.example.com/v1"
model = "your-vision-model"
api_key_env = "IMAGEEVAL_API_KEY"
temperature = 0.2
max_tokens = 1200
timeout_s = 90
image_max_edge = 1280

[pipeline]
max_concurrency = 4
rpm = 60
max_retries = 3

[reviewer]
default_name = "local"
```

## 15. 里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| M1 数据层 | schema + 迁移 + 导入 + 配置 + FakeProvider + 单测 | 导入含坏行的样本集，隔离报告正确 |
| M2 评分链路 | rubric v1 + prompt + 真实 Provider + 流水线 + CLI | FakeProvider 与 MockTransport 全链路通过；配好 key 后真实 API 小样本跑通（无 key 不阻塞验收） |
| M3 标注台 | 复核 API + 前端交互 + 快捷键 + 筛选 | 50 条样本可用纯键盘完成复核 |
| M4 报告与导出 | 聚合统计 + 图表 + 静态 HTML + 训练数据导出 | 报告含三维分布/一致性/归因；导出 sft 数据通过 schema 校验 |

## 16. 学习模式约定

实施阶段将保留两处由用户实现的核心逻辑（届时提供函数签名、参数说明、注释与失败测试桩）：

1. `scoring.aggregate_adherence()`：critical 权重、partial 记分、contradicted 惩罚与封顶策略。
2. `report.select_failure_cases()`：失败案例的判定规则（低分阈值、修正幅度、需求缺失类别的组合）。

两处均直接决定报告洞察方向，存在多种合理策略，需由用户依据业务侧重决定。
