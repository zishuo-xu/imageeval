# imageeval · 生图模型评测系统

对「原始 Query + 生成图片」做需求遵循、视觉质量、美学三维评测，支持 AI 预标注、人工复核、可视化报告与训练数据导出。

## 需求定义

完整的需求定义、评分口径、功能编号（FR-1~FR-9）与验收标准见 **[docs/requirements.md](docs/requirements.md)**。

一句话版本：对每组「原始 Query + 生成图片」做三维结构化评分，通过「AI 预标注 → 人工修正」沉淀 gold 数据，用于评价生图模型效果并为后续评测模型训练积累数据。

## 快速开始

```bash
uv sync --extra dev
cp config.example.toml config.toml   # 填写 base_url / model
export IMAGEEVAL_API_KEY="你的密钥"
uv run python -m imageeval --config config.toml serve
```

`--config` 是顶层选项，必须写在子命令之前。不传时不会读取 TOML，将退回内置默认值。

已验证的裁判配置（DeepSeek 多模态）：

```toml
[judge]
provider = "openai_compat"
base_url = "https://api.deepseek.com"
model = "deepseek-flash"
api_key_env = "IMAGEEVAL_API_KEY"
max_tokens = 4096   # 推理模型，留足输出预算
timeout_s = 180
```

打开 http://127.0.0.1:8765 。

## 桌面网格复核

标注台默认使用 4×4 网格，每页最多 16 张图片。卡片展示需求遵循、视觉质量、美学、总分和复核状态；点击卡片在右侧复核，双击或点击「单图」查看大图。「上一页 / 下一页」翻页，「上一张 / 下一张」及 J/K 跨页切换样本。筛选、排序后从第一页开始；不足 16 张时保留空位。

页面显示本次评测记录的裁判模型，模拟裁判会明确标为非真实评分。运行真实评分需要配置多模态模型 endpoint、model，并向启动服务的进程提供 `IMAGEEVAL_API_KEY`；凭据不会返回浏览器。`config.toml` 和本地数据不提交 Git。

## MiniMax 生图测试

设置环境变量 `MINIMAX_API_KEY` 后启动服务，点击顶部「AI 生图」。每行一条提示词，每条可生成 1、2 或 4 张，每批最多 16 张。生成成功后自动保存图片、创建批次及评测，可选自动调用裁判评分。

M Plan 使用套餐详情中的订阅 Key；普通开放平台 Key 按量扣余额。`[generation].base_url` 需与 Key 所属服务区域匹配。Key 只从环境变量读取，不写入任务或前端。图片参数、平台请求 ID 与耗时保存在样本 metadata，原始生成文件保存在 `data/generations/`。

任务进度在刷新后可恢复查看。当前一次执行一个生图任务，失败会停止后续生成并保留已成功的样本；请求超时、失败或服务重启均不自动重试生图，避免重复消耗额度。服务中断后可检查保留的响应和图片，已生成文件可使用原有导入功能恢复。

## 数据格式

CSV 列或 JSONL 字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| external_id | 是 | 批内唯一 |
| query | 是 | 原始提示词 |
| image | 是 | 本地路径（相对 `--image-root` 或文件所在目录）或 URL |
| model_name | 否 | 生成模型标识 |
| tags | 否 | 分号分隔，或 JSON 数组 |
| metadata | 否 | JSON 对象字符串 |

URL 图片必须加 `--download`，否则该行会被拒绝。

## CLI

```bash
uv run python -m imageeval --config config.toml import data.csv --image-root ./images
uv run python -m imageeval --config config.toml run --new --batch-id BATCH --name "第一轮"
uv run python -m imageeval --config config.toml run --run-id RUN
uv run python -m imageeval --config config.toml report --run-id RUN
uv run python -m imageeval --config config.toml export --run-id RUN --mode sft
```

`run --run-id RUN` 用于断点续跑，跳过已有 `ok` 评估。

## 导出模式

| 模式 | 包含样本 | 用途 |
|---|---|---|
| `raw` | 所有已评分样本（gold + silver） | 保存完整标注事实 |
| `only-reviewed` | 仅已复核样本（gold） | 导出高质量子集 |
| `sft` | 仅已复核样本（gold），query+image → 标注 | 评测模型 SFT |

## 评分口径

- 需求遵循 0.40、视觉质量 0.35、美学 0.25；全部权重在 `src/imageeval/rubric/v1.yaml`。
- 需求遵循由原子需求状态本地计算，critical 冲突封顶。
- 人工分 1-5 整数；AI 维度分保留两位小数。
- 导出区分 `gold`（人工复核）与 `silver`（仅 AI）。

## 测试

```bash
uv run pytest -v
```

测试不发起任何真实网络请求。

## 示例数据

`sample_data/` 提供 12 张示例图（4 个 Query × 好/部分/差三档）与 `samples.csv`，用于跑通导入、评分、复核、报告与导出：

```bash
uv run python -m imageeval --config config.toml import sample_data/samples.csv --image-root sample_data/images
```

## 文档

- [需求定义与验收标准](docs/requirements.md)
- [设计文档](docs/superpowers/specs/2026-10-31-image-eval-system-design.md)
- [实施计划](docs/superpowers/plans/2026-10-31-image-eval-system.md)

页面流程分为「生图 → AI 评分 → 人工复核」三个独立步骤。生图页填写多行提示词、每条图片数量和画面比例，右侧查看结果；点击「进入 AI 评分」会选中该图片批次对应的评测。可勾选自动评分，或在评分页手动开始。评分后进入 4×4 人工复核工作台，确认或修正分数。切换步骤保留当前表单输入；刷新后恢复最近一次生图任务及其结果。

桌面工作台支持生图与评分结果的 4×4 总览，点击图片可在页内查看原图，使用左右方向键切换、Esc 关闭。提示词草稿、当前步骤和所选评测保存在当前浏览器；“复用上次”可重新载入最近生图任务的参数。评分失败会单独标记，新建评测表单由“＋ 新建评测”展开。

### Query 与 PE 扩写

流程新增「Query / PE 扩写 → 生图 → AI 评分 → 人工复核」。输入每行一个原始 Query，最多 16 条；可以跳过 PE 直接生图，也可以调用 PE、逐条编辑扩写结果后应用。原始 Query 变化后，旧扩写不能直接应用。改变生成提示词行数时需要返回 PE 步骤重新确认对应关系。

PE 默认复用已连接的 `[judge]` 文本接口；配置独立 `[pe]` 可替换模型、接口、环境变量、temperature、max_tokens 和 timeout_s。模板版本 `pe-v1` 保留主体、数量、颜色、位置、文字、否定要求，扩写只作为候选提示词，仍需人工确认。扩写失败可手动补写、重新扩写或跳过；重新扩写会再次调用模型。

`data/expansions/<id>.json` 保存模型原始扩写、原始 Query、模型名、模板版本、参数、token 用量和耗时；生图样本的 `metadata.prompt_expansion` 另存实际发给生图模型的提示词及是否被人工修改。主评分只接收原始 Query，不把 PE 补充细节当作用户要求。预览和复核可展开来源；raw、only-reviewed、sft 导出均携带 `prompt_expansion`，不修改历史样本。

当前实现保留双提示词和主需求评分，按生产任务流程执行；尚未增加扩写忠实度独立评分、图片对扩写要求的独立评分或费用换算。token 用量不能直接当作实际账单。

### 生产任务流程

平台主流程为原始需求 → 可选 PE 扩写 → 批量生图 → 质量检查 → 人工复核 → 报告与导出。每批最多生成 16 张，保留原始需求、最终生图文本、模型来源与质检记录。

扩写前后图片对比是生图任务的可选功能：原始版和扩写版各生成一组，最多 16 组、32 张；并排查看提示词、图片、质检差异，记录成图选择并导出结果。页面不再使用实验和胜率表达，历史任务保持可用。HTML 与脚本禁用缓存，避免旧页面资源与接口不一致。

### 细项缺陷检查 visual-v2

真实裁判新增 12 项检查：手指数量、手部结构、肢体数量、关节连接、面部结构、身体比例、物体结构、文字准确性、边缘融合、接触遮挡、光影透视和表面细节。每项保存 key、status、location、evidence，显示为正常(5)、轻微(4)、明显(2)、严重(1)、无法判定或不适用。最后两项不等于零分，也不表示通过；动物不按人体五指标准检查，遮挡、手套、出画、低清不推断缺指，明确的风格或特殊身体设定不应作为畸形扣分。

主维度仍为遵循/质量/美学。质量先按原有加权子项计算，再执行可见缺陷封顶：任一严重项 ≤2，任一明显项 ≤3，任一轻微项 ≤4；无明确缺陷不附加封顶。细项分值不是简单平均，也不表示医学诊断。人审可根据实际图片修正总体分，并在理由中指出错误细项。

检查明细保存在 subscores.checks，进入预览、人工复核以及数据集导出。真实接口遗漏检查项会进入格式修复流程，而非默认视为通过。新评测记录 checklist_version=visual-v2 和更新后的 prompt_hash。历史结果保持不变；“按新规则重评”复制原批次建立新评测，不重新生图、不覆盖旧结果。旧规则任务不可直接续跑或重试混入新规则。

细项版默认输出上限为 8192 tokens，避免完整清单被截断；实际使用量仍由模型响应决定。若接口返回 finish_reason=length，会明确标注输出截断，不尝试把残缺 JSON 当有效评分。重新质检创建新版本，旧版本依旧保留。

## 服务器部署

公网登录入口、systemd 服务、配置位置、更新与备份恢复见 [deploy/README.md](deploy/README.md)。

## 选项式评价

AI 与人工使用相同五档满意度（非常满意、满意、一般、不满意、非常不满意），可同时选择满意点和不满意点，并补充具体说明。AI 依据原始需求及可见证据直接判断满意度；人工独立选择，不预填 AI 结论。报告汇总满意率、五档分布及问题频次。SFT 导出使用 `label_type=satisfaction` 和结构化选项标签。

严格评价标准：需局部修改最高为“一般”，需大幅修改或关键需求失败最高为“不满意”；“非常满意”要求无已发现问题、无需修改及至少两项有具体证据的优秀表现。标准记录为 `strict-v1`。
