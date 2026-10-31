# imageeval · 生图模型评测系统

对「原始 Query + 生成图片」做需求遵循、视觉质量、美学三维评测，支持 AI 预标注、人工复核、可视化报告与训练数据导出。

## 快速开始

```bash
uv sync --extra dev
cp config.example.toml config.toml   # 填写 base_url / model
export IMAGEEVAL_API_KEY="你的密钥"
uv run python -m imageeval serve
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

## CLI

```bash
uv run python -m imageeval import data.csv --image-root ./images
uv run python -m imageeval run --new --batch-id BATCH --name "第一轮"
uv run python -m imageeval report --run-id RUN
uv run python -m imageeval export --run-id RUN --mode sft
```

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
