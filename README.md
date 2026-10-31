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
