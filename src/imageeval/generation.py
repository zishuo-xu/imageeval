from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, StringConstraints, model_validator

from .importer import import_file
from .runs import create_run
from .storage import validate_image
from .util import utcnow

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)]


class GenerationRequest(BaseModel):
    request_id: UUID
    name: str = Field(default="MiniMax 生图评测", min_length=1, max_length=100)
    prompts: list[Prompt] = Field(min_length=1, max_length=16)
    images_per_prompt: int = Field(default=1, ge=1, le=4)
    aspect_ratio: Literal["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16"] = "1:1"
    auto_score: bool = True
    ab_compare: bool = False
    original_queries: list[Prompt] | None = None
    expansion_id: UUID | None = None

    @model_validator(mode="after")
    def limit_total(self):
        if self.ab_compare and (not self.original_queries or not self.expansion_id):
            raise ValueError("A/B 实验需要原始 Query 和已确认的 PE 扩写记录")
        if len(self.prompts) * self.images_per_prompt > 16:
            raise ValueError("普通生图最多 16 张；A/B 最多 16 对、32 张")
        if self.original_queries is not None and len(self.original_queries) != len(self.prompts):
            raise ValueError("原始 Query 与生图提示词必须逐条对应")
        if self.expansion_id and self.original_queries is None:
            raise ValueError("PE 生图必须保留原始 Query")
        return self


class GenerationError(Exception):
    pass


class MiniMaxGenerator:
    def __init__(self, cfg):
        self.cfg = cfg

    async def generate(self, prompt: str, n: int, aspect_ratio: str, directory: Path) -> list[dict]:
        key = os.environ.get(self.cfg.api_key_env)
        if not key:
            raise GenerationError("未配置 MiniMax 订阅 Key")
        payload = {"model": self.cfg.model, "prompt": prompt, "n": n,
                   "aspect_ratio": aspect_ratio, "prompt_optimizer": False, "response_format": "url"}
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
            try:
                response = await client.post(self.cfg.base_url.rstrip("/") + "/image_generation",
                                             headers={"Authorization": f"Bearer {key}"}, json=payload)
            except httpx.HTTPError:
                raise GenerationError("生图请求超时或网络中断，结果未知；未自动重试，请先检查平台用量") from None
            if response.status_code != 200:
                raise GenerationError(f"MiniMax 返回 HTTP {response.status_code}，请检查订阅权限或限流")
            try:
                data = response.json()
                code = data["base_resp"]["status_code"]
                if code != 0:
                    # Upstream messages can contain request data; do not expose them to the browser.
                    reasons = {
                        1008: "余额不足；M Plan 用户请确认使用套餐详情中的订阅 Key，并核对国内/海外服务区域",
                        1004: "Key 未授权，请检查凭据及服务区域",
                        1002: "请求频率超限，请稍后再试",
                        2056: "M Plan 当前额度已用完，请等待额度刷新",
                        2057: "此接口需要 M Plan 订阅 Key",
                        2061: "当前套餐不支持该模型",
                        2067: "套餐额度已用完且未开启积分消耗",
                        1026: "提示词未通过内容审核",
                        1027: "生成图片未通过内容审核",
                    }
                    raise GenerationError(f"MiniMax 错误 {code}：{reasons.get(code, '请求被拒绝，请查询平台错误码说明')}")
                urls = data["data"]["image_urls"]
                if not isinstance(urls, list) or not 1 <= len(urls) <= n:
                    raise ValueError("invalid image count")
            except (ValueError, KeyError, TypeError):
                raise GenerationError("MiniMax 返回了无效的图片结果，未自动重试") from None
            # Persist the upstream result before downloading; generated assets can be recovered on failure.
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "response.json").write_text(json.dumps(data, ensure_ascii=False))
            images = []
            for index, url in enumerate(urls):
                if not isinstance(url, str) or httpx.URL(url).scheme != "https":
                    raise GenerationError("MiniMax 返回了无效的图片地址")
                try:
                    image = await client.get(url)
                    image.raise_for_status()
                except httpx.HTTPError:
                    raise GenerationError("图片已生成，但下载失败；响应已保存在本地，未重复生图") from None
                path = directory / f"{index + 1}.png"
                path.write_bytes(image.content)
                try:
                    validate_image(path)
                except (ValueError, OSError):
                    raise GenerationError("下载的文件无法解码为图片") from None
                images.append({"path": str(path.resolve()), "request_id": data.get("id"),
                               "latency_ms": round((time.perf_counter() - started) * 1000)})
            return images


class GenerationManager:
    """One local generation job at a time; never automatically retry billable requests."""

    def __init__(self, cfg, db, rubric, run_manager, generator=None):
        self.cfg, self.db, self.rubric, self.run_manager = cfg, db, rubric, run_manager
        self.generator = generator or MiniMaxGenerator(cfg.generation)
        self.root = cfg.data_dir / "generations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.task = None
        for path in self.root.glob("*/job.json"):
            job = json.loads(path.read_text())
            if job["status"] in ("queued", "running"):
                job.update(status="interrupted", error="服务重启，生成任务已中断；已保存文件保留，未自动重新调用")
                self.save(job)

    def save(self, job):
        target = self.root / job["id"] / "job.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False))
        temporary.replace(target)

    def get(self, job_id: UUID):
        path = self.root / str(job_id) / "job.json"
        if not path.exists():
            raise LookupError("生成任务不存在")
        return json.loads(path.read_text())

    def latest(self):
        paths = list(self.root.glob("*/job.json"))
        return json.loads(max(paths, key=lambda p: p.stat().st_mtime).read_text()) if paths else None

    def start(self, request: GenerationRequest):
        job_id = str(request.request_id)
        directory = self.root / job_id
        if directory.exists():
            job = self.get(request.request_id)
            if GenerationRequest.model_validate(job["request"]).model_dump(mode="json") != request.model_dump(mode="json"):
                raise ValueError("同一请求 ID 不能用于不同的生成参数")
            return job
        if self.task and not self.task.done():
            raise ValueError("已有生图任务正在执行，请等待完成")
        if not os.environ.get(self.cfg.generation.api_key_env):
            raise ValueError("未配置 MiniMax 订阅 Key")
        expansion = None
        if request.expansion_id:
            path = self.cfg.data_dir / "expansions" / f"{request.expansion_id}.json"
            if not path.exists():
                raise ValueError("PE 扩写记录不存在，请重新扩写或跳过 PE")
            expansion = json.loads(path.read_text())
            if [item["original_query"] for item in expansion["items"]] != request.original_queries:
                raise ValueError("原始 Query 已变化，请重新扩写，避免提示词错配")
        directory.mkdir()
        job = {"id": job_id, "request": request.model_dump(mode="json"), "status": "queued",
               "created_at": utcnow(), "total": len(request.prompts) * request.images_per_prompt * (2 if request.ab_compare else 1),
               "generated": 0, "imported": 0, "processed_prompts": 0, "error": None,
               "batch_id": None, "run_id": None, "model": self.cfg.generation.model, "expansion": expansion}
        self.save(job)
        self.task = asyncio.create_task(self.execute(job, request))
        return job

    async def execute(self, job, request):
        directory = self.root / job["id"]
        records = []
        job["status"] = "running"
        self.save(job)
        try:
            plan = []
            for index, prompt in enumerate(request.prompts):
                if request.ab_compare:
                    plan.append((index, "A", request.original_queries[index]))
                plan.append((index, "B" if request.ab_compare else "single", prompt))
            for step, (index, variant, prompt) in enumerate(plan):
                try:
                    images = await self.generator.generate(prompt, request.images_per_prompt,
                                                           request.aspect_ratio, directory / f"{index + 1}-{variant}")
                except GenerationError as exc:
                    job["error"] = str(exc)
                    break
                for image_index, image in enumerate(images):
                    records.append({"external_id": f"{index + 1}-{variant}-{image_index + 1}", "query": request.original_queries[index] if request.original_queries else prompt,
                                    "image": image["path"], "model_name": self.cfg.generation.model,
                                    "tags": ["minimax", "generated"],
                                    "metadata": {"generation_job_id": job["id"], "provider_request_id": image["request_id"],
                                                 "aspect_ratio": request.aspect_ratio, "prompt_optimizer": False,
                                                 "latency_ms": image["latency_ms"],
                                                 "comparison": {"experiment_id": job["id"], "pair_id": f"{index + 1}-{image_index + 1}",
                                                                "query_index": index, "candidate_index": image_index, "variant": variant} if request.ab_compare else None,
                                                 "prompt_expansion": self.prompt_provenance(job if variant != "A" else {"expansion": None}, request, index, prompt)}})
                job["processed_prompts"] = step + 1
                job["generated"] = len(records)
                (directory / "samples.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
                self.save(job)
            if records:
                # Keep the database batch and run creation atomic; image files are retained for recovery.
                with self.db.transaction():
                    result = import_file(self.db, self.cfg, directory / "samples.jsonl",
                                         source_name=request.name)
                    job["batch_id"] = result.batch_id
                    job["imported"] = result.imported
                    if result.rejected:
                        job["error"] = f"有 {result.rejected} 张图片导入失败，已保留生成文件"
                    if result.imported:
                        job["run_id"] = create_run(self.db, self.cfg, self.rubric, result.batch_id, request.name)
                if request.auto_score and job["run_id"]:
                    self.run_manager.start(job["run_id"])
            job["status"] = "completed" if job["imported"] == job["total"] else "partial" if job["imported"] else "failed"
            if job["status"] != "completed" and not job["error"]:
                job["error"] = "平台返回的图片少于请求数量，可能有内容审核未通过；未自动补生成"
        except asyncio.CancelledError:
            job.update(status="interrupted", error="生成任务中断，已保存文件保留；未自动重试")
            raise
        except Exception:
            job.update(status="failed", error="生成或导入出现内部错误，已保存文件保留，请检查服务日志")
            import logging
            logging.getLogger(__name__).exception("Generation job failed: %s", job["id"])
        finally:
            self.save(job)

    @staticmethod
    def prompt_provenance(job, request, index, prompt):
        original = request.original_queries[index] if request.original_queries else prompt
        expansion = job.get("expansion")
        item = expansion["items"][index] if expansion else {}
        return {"original_query": original, "generation_prompt": prompt,
                "mode": "pe" if expansion else "manual" if original != prompt else "direct",
                "expanded_prompt": item.get("expanded_prompt"),
                "edited": bool(expansion and prompt != item.get("expanded_prompt")),
                "expansion_id": expansion["id"] if expansion else None,
                "model": expansion["model"] if expansion else None,
                "template_version": expansion["template_version"] if expansion else None,
                "parameters": expansion["parameters"] if expansion else {},
                "latency_ms": item.get("latency_ms"), "usage": item.get("usage"),
                "error": item.get("error")}

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
