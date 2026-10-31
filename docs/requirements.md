# 生图模型评测系统 · 需求定义与验收标准

| 项目 | 内容 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-11-01 |
| 状态 | 已实现（M1–M4），部分增强项列为后续 |
| 关联文档 | [设计文档](superpowers/specs/2026-10-31-image-eval-system-design.md) · [实施计划](superpowers/plans/2026-10-31-image-eval-system.md) |
| 适用对象 | 算法 / 评测 / 数据标注同学 |

## 1. 一句话需求

对每一组「原始 Query + 生成图片」进行 **需求遵循、视觉质量、美学** 三维评测，产出可复核、可追溯、可导出的结构化结果，用于评价生图模型效果，并积累后续评测模型训练所需的人工标注数据。

## 2. 背景与问题

生图模型迭代需要稳定、可解释、可复现的效果评价，但现状存在三个矛盾：

1. **纯人工评价**：标准难统一、成本高、速度慢，无法支撑高频迭代。
2. **纯模型打分**：单次分数不可解释、不可追溯，模型偏差无法被人工纠正。
3. **标注数据流失**：人工复核结果散落在表格里，无法沉淀为可训练的数据资产。

本系统要解决的不是"给一张图打一个分"，而是建立一条 **AI 预标注 → 人工修正 → 结构化沉淀** 的评测数据飞轮。

## 3. 目标

| 编号 | 目标 | 可验证结果 |
|---|---|---|
| G1 | 三维结构化评分 | 每条样本输出需求遵循 / 视觉质量 / 美学三个 1–5 维度分，附带需求拆解与理由 |
| G2 | 人工复核闭环 | 复核人可接受、修正、跳过；AI 分与人工分双轨留存，人工分不覆盖 AI 分 |
| G3 | 可视化报告 | 分布、雷达、AI/人工一致性、需求归因、失败案例，可导出单文件 HTML |
| G4 | 训练数据沉淀 | 导出 `raw` / `only-reviewed` / `sft` 三种数据集，明确 gold / silver |
| G5 | 可复现 | 每次评测记录 rubric 版本、prompt 哈希、裁判模型、原始响应与 token 消耗 |

## 4. 非目标（本期明确不做）

- 多用户登录、权限、任务分配、双盲审核
- 跨模型横向对比视图（`model_name` 仅作为元数据）
- 参考图 / 图像编辑任务的一致性评分
- 万张级任务队列与分布式 worker
- 应用内 rubric 编辑器
- pairwise 偏好标注
- 评测模型本身的训练（本期只产出训练数据）

## 5. 用户与典型场景

**用户**：单人或小团队，在本机或局域网使用，数据量百~千张。

**场景 A · 版本验收**：同一批 Query 生成新版本图片，跑一遍评分，看三维均分与需求类别失败率是否改善。

**场景 B · Badcase 归因**：查看低分样本与需求归因，回答"模型系统性错在数量、文字还是空间关系"。

**场景 C · 标注数据生产**：人工复核 AI 预标注结果，导出 gold 数据，为后续训练轻量评测模型做准备。

## 6. 术语

| 术语 | 定义 |
|---|---|
| Query | 生成图片时使用的原始提示词 |
| 原子需求 | 从 Query 拆出的最小可判定需求，如"红色的猫""两只""阳光从左侧" |
| critical / normal | 关键需求（不满足则任务失败）/ 普通需求 |
| satisfied / partial / missing / contradicted | 满足 / 部分满足 / 缺失 / 与需求冲突 |
| intent_alignment | 整体意图贴合度，1–5 整数 |
| rubric | 评分标准，包含维度权重、子项权重、1–5 锚点；当前版本 `v1` |
| AI 预标注 | 裁判模型给出的三维分、需求清单、子项理由与结论 |
| gold / silver | 人工复核过的标签 / 仅 AI 生成的标签 |
| batch | 一次导入形成的数据批次 |
| run | 针对一个 batch 的一次批量评测 |

## 7. 功能需求

### FR-1 数据导入

系统 **必须** 支持 CSV 与 JSONL 导入，字段包括 `external_id`、`query`、`image`（本地路径或 URL）、`model_name`、`tags`、`metadata`。

**验收标准**

- 逐行校验：`external_id` 批内唯一、`query` 非空、图片可解码。
- 坏行被拒绝并记录行号与原因，**不得阻塞**好行。
- 图片拷贝到 `data/images/{batch_id}/`，生成最长边 480px 缩略图。
- 导入结果返回 `imported` / `rejected` / 逐行报告。

### FR-2 自动评分

系统 **必须** 通过 OpenAI 兼容的多模态 `/chat/completions` 接口调用裁判模型，输出严格 JSON。

**验收标准**

- 输出包含：`observation`、`requirements[]`（至少一条 critical）、`intent_alignment`、`subscores`、`notable_issues`、`verdict`。
- JSON/schema 失败时带错误信息重试一次；仍失败则保存原始响应与错误，样本标记为 `error`。
- 记录 token 消耗、延迟、解析尝试次数。
- 密钥只从环境变量读取，不写入配置文件、不打印。

### FR-3 评分口径

见第 8 节。评分 **必须** 由本地确定性代码计算，不得由模型直接给维度总分。

### FR-4 批量执行

**验收标准**

- 并发受 `max_concurrency` 限制，调用频率受 `rpm` 限制。
- 仅对 `RetryableJudgeError`（超时/429/5xx/网络）重试，指数退避，最多 `max_retries` 次。
- 断点续跑：再次启动只处理没有 `ok` 评估的样本。
- 支持暂停、恢复、取消。
- 成功评估 **不得** 被错误重试覆盖。
- 失败样本可见错误原因，支持单条重试；重试不重跑整个 run。

### FR-5 人工复核

**验收标准**

- 标注台预填 AI 分数（四舍五入为 1–5 整数），显示需求清单、子项理由、结论。
- 支持"接受全部 / 保存修正 / 跳过"。
- 快捷键：`A` 接受、`J/K` 切换、`1–5` 打分、`Enter` 保存、`S` 跳过、`F` 适应、`Z` 缩放。
- `reviews` 只追加；最新一条为当前 gold。
- `accepted` 用 AI 四舍五入分填充人工分；`corrected` 必须提供三维整数分；`skipped` 记空。
- 失败评估不可被复核。

### FR-6 可视化报告

**验收标准**

- 概览：样本数、已评/待复核、AI 与人工均分、人工接受率。
- 分布：三维直方图（AI/人工叠加）、雷达图。
- 一致性：每维度 MAE、Spearman（n≥3）、整数混淆矩阵、散点。
- 需求归因：状态分布、按 category 的失败率排序。
- 失败案例：低分与修正幅度案例墙。
- 一键导出单文件 HTML（CSS/Chart.js/数据/缩略图内嵌，离线可开）。

### FR-7 数据导出

**验收标准**

- `raw`：所有已评分样本，AI + 人工双轨。
- `only-reviewed`：仅 gold。
- `sft`：仅 gold，`query + image → label`。
- 每条记录含 `label_quality`（gold/silver）与 `final.source`（human/ai）。
- 输出 `dataset.jsonl` + `manifest.json`（rubric 版本、prompt 哈希、judge、计数、图片清单）+ `images/`。
- 打包 zip 下载，路径经 `resolve_under` 校验。

### FR-8 CLI 与 API

**验收标准**

- CLI：`serve` / `import` / `run` / `report` / `export`，支持 `--config`、`--data-dir`、`serve --host/--port`。
- API：导入、批次、样本、图片、run 控制、复核队列与提交、报告汇总、静态报告导出、数据集导出与下载。
- 状态映射：未知资源 404；非法参数 400；状态冲突 409；schema 错误 422。

### FR-9 安全

**验收标准**

- API key 仅环境变量。
- 所有图片/报告/导出下载路径经 `resolve_under` 校验，拒绝目录穿越。
- 用户或模型产生的文本在报告页与标注台必须转义。
- 测试不发起真实网络请求。

## 8. 评分口径（规范性）

### 8.1 尺度

所有子项 1–5 整数，锚点：1 不可用 / 2 明显问题 / 3 基本可用有瑕疵 / 4 良好 / 5 优秀。

### 8.2 需求遵循（权重 0.40）

```
v = satisfied:1.0 | partial:0.5 | missing:0.0 | contradicted:0.0
w = critical:3 | normal:1
ratio     = Σ(w·v) / Σw
atomic    = 1 + 4 × ratio
若存在 critical contradicted：atomic = min(atomic, 3.0)
adherence = round(0.75 × atomic + 0.25 × intent_alignment, 2)
```

`requirements` 为空时抛错。critical 冲突时 atomic 封顶，但仍与意图分混合（例如唯一 critical 冲突且意图 5 → 2.0）。

### 8.3 视觉质量（权重 0.35）

`clarity 0.20 / artifacts 0.30 / text_render 0.10 / physics 0.20 / consistency 0.20`。

不适用子项标 N/A 并重新归一；适用子项少于一半时该维度记为错误。

### 8.4 美学（权重 0.25）

`composition / color / lighting / texture / appeal` 各 0.20。

### 8.5 总分

```
overall = 0.40×adherence + 0.35×quality + 0.25×aesthetics
```

### 8.6 舍入与来源

- AI 维度分为两位小数；AI → 整数（人工预填、直方图、混淆矩阵）统一使用 **half-up**（`2.5 → 3`，`4.5 → 5`）。
- 所有权重唯一来源：`src/imageeval/rubric/v1.yaml`。修改权重 = 发布新 rubric 版本。

## 9. 数据与可追溯性

| 数据 | 规则 |
|---|---|
| 评估 `evaluations` | 每个 `(sample_id, run_id)` 唯一；成功行不可覆盖；错误行可被重试覆盖 |
| 复核 `reviews` | 只追加；最新一条（`created_at DESC, id DESC`）为当前 gold |
| 原始响应 | 失败时也保存 `raw_response` 与 `parse_attempts` |
| 复现信息 | 每次 run 记录 `rubric_version`、`prompt_hash`、provider、judge model、参数快照 |
| 成本 | 每次评估记录 token 与延迟，run 汇总到 `usage_json` |

## 10. 非功能需求

| 编号 | 需求 | 验收 |
|---|---|---|
| NFR-1 | 本地单机部署，数据不外传（除裁判 API 的图片） | 默认 `127.0.0.1`，SQLite 本地文件 |
| NFR-2 | 百~千张可用 | 并发/限流可配，进度 2s 轮询 |
| NFR-3 | 可靠 | 断点续跑、幂等、失败不丢样本 |
| NFR-4 | 安全 | 密钥仅环境变量、路径穿越防护、文本转义 |
| NFR-5 | 可复现 | rubric 版本 + prompt 哈希 + 原始响应 |
| NFR-6 | 可测试 | 全量测试离线运行（FakeProvider / MockTransport） |
| NFR-7 | 易用 | 中文界面、无 npm/构建步骤、单命令启动 |

## 11. 验收标准（总体）

| 编号 | 验收项 | 通过条件 |
|---|---|---|
| AC-1 | 导入容错 | 含坏行的 CSV：好行入库、坏行进入报告，计数正确 |
| AC-2 | 全链路 | 导入 → 评分 → 复核 → 报告 → 导出 全流程通过（FakeProvider） |
| AC-3 | 真实裁判 | 配置真实多模态 API 后，样本返回结构化评分 |
| AC-4 | 复核状态 | accepted / corrected / skipped 状态与计数正确，历史保留 |
| AC-5 | 报告口径 | 均分、接受率、MAE、需求归因与手算一致 |
| AC-6 | 导出分级 | `raw` 含 gold+silver；`sft`/`only-reviewed` 仅 gold |
| AC-7 | 回归 | `uv run pytest -q` 全绿（当前 96 项） |

## 12. 当前实现状态与已知差距

### 12.1 已实现

- 需求定义中的 FR-1 至 FR-9 核心路径、评分口径、双轨数据、报告与三种导出。
- 补充能力：失败样本错误横幅与单条重试、单文件报告一键导出、half-up 舍入、CSV tags 支持 JSON 数组、`serve --host/--port`。

### 12.2 尚未实现（非阻塞，列为后续）

| 项 | 影响 | 建议 |
|---|---|---|
| Query 关键词 / 标签筛选 | 千张级检索不便 | 增加队列查询参数与 UI 输入 |
| 按维度填写修正理由 | 目前只有一条综合理由 | 增加三维理由输入 |
| 失败案例拆成"低分 Top-N / 修正幅度 Top-N" | 报告洞察粒度较粗 | 拆分两个列表 |
| 报告明细表可点击跳转、可筛选 | 定位样本需手动找 | 增加深链与前端筛选 |
| `include_images` 导出参数 | 静态报告总是内嵌图片 | API 契约补全 |
| `/api/samples` 的 `batch_id` / `tag` / `unscored` 筛选 | API 目前以 `run_id` 为主 | 补全或文档化 |
| append-only 数据库触发器、迁移原子性 | 依赖服务层约束 | v2 前加固 |
| 前端行为测试（当前为静态断言） | JS 回归覆盖弱 | 引入轻量 DOM 测试 |

> 这些差距不影响评分、复核、报告与导出的正确性；需求定义以本节作为"已交付 vs 后续"的校准记录。

## 13. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-31 | v0.1 | 初始设计与范围 |
| 2026-11-01 | v1.0 | 与实现对齐，补充需求编号、评分口径、验收标准与未实现清单 |

## 14. 参考

- 设计文档：[2026-10-31-image-eval-system-design.md](superpowers/specs/2026-10-31-image-eval-system-design.md)
- 实施计划：[2026-10-31-image-eval-system.md](superpowers/plans/2026-10-31-image-eval-system.md)
- 使用说明：[README.md](../README.md)
