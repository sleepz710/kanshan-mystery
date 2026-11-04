"""精修档批量生成与检查结果导出。

离线验证：python -m eval.pregen --stories-dir data/pregen-mock/stories
真实生成：python -m eval.pregen --live --env-file .env --materials materials.json --count 6
素材文件使用 UTF-8 JSON 字符串数组，至少提供 --count 条素材。
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import monotonic

from dotenv import load_dotenv
import yaml

from backend import llm
from backend.studio import check as checker
from backend.studio.ingest import MAX_MATERIAL_CHARS
from backend.studio.service import StudioService
from eval.common import ROOT, evaluation_mode, positive_int, safe_error, write_reports


DEFAULT_MATERIALS = (
    "大雪封山的民宿，所有客人都在餐厅时，老板的账本消失了。写成现实逻辑的悬疑案件。",
    "旧医院已经停用的病房，深夜仍响起呼叫铃。保留恐怖氛围，真相由现实证据解释。",
    "大学社团演出前，后台同一张借用单出现了两个不同的归还时间。",
    "闭店后的书店里，预订书页中的便签被换成空白，每个人都说自己没有碰过。",
    "雨夜末班公交，司机收到一张早已停用的车票，失物箱里的伞却是干的。",
    "海边旅馆的合照里少了一个人，住客记录显示那天所有房间都已住满。",
    "博物馆开馆前，展柜封条完好，修复记录里的物品重量却发生了变化。",
    "校园广播播放一段尚未录制的通知，录音室钥匙一直由三个人轮流保管。",
)
CSV_COLUMNS = [
    "index", "material", "status", "quality", "story_id", "title", "elapsed_seconds", "checked",
    "structure_ok", "structure_problems", "playability_ok", "playability_problems",
    "pipeline_problems", "error", "call_failures",
]


class RecordingStudioService(StudioService):
    """记录生成流程已有的模型调用失败，沿用原流程的重试和保存。"""

    def __init__(self, stories_dir: Path):
        super().__init__(stories_dir)
        self.call_failures: dict[str, list[dict]] = defaultdict(list)

    async def _model_call(self, job, attempt, step, messages, **kwargs):
        started = monotonic()
        try:
            return await super()._model_call(job, attempt, step, messages, **kwargs)
        except Exception as error:
            failure = {
                "attempt": attempt, "step": step,
                "elapsed_seconds": round(monotonic() - started, 3), **safe_error(error),
            }
            upstream_status = getattr(error.__cause__, "status_code", None)
            if isinstance(upstream_status, int):
                failure["upstream_status_code"] = upstream_status
            self.call_failures[job.id].append(failure)
            raise


def sample_count(value: str) -> int:
    number = int(value)
    if not 6 <= number <= 8:
        raise argparse.ArgumentTypeError("样本数量需要在 6 到 8 之间")
    return number


def read_materials(path: Path | None, count: int) -> list[str]:
    materials = json.loads(path.read_text(encoding="utf-8-sig")) if path else list(DEFAULT_MATERIALS)
    if (not isinstance(materials, list) or len(materials) < count
            or any(not isinstance(text, str) or not text.strip() or len(text) > MAX_MATERIAL_CHARS for text in materials)):
        raise ValueError(f"素材需为至少 {count} 条非空字符串的 JSON 数组，每条不超过 {MAX_MATERIAL_CHARS} 字。")
    return [text.strip() for text in materials[:count]]


@contextmanager
def generation_mode(live: bool, env_file: Path | None):
    """模拟模式跳过配置文件，真实模式按指定文件加载后恢复进程环境。"""
    previous_environment = dict(os.environ)
    previous_env_file = llm._ENV_FILE
    try:
        if live:
            source = env_file or ROOT / ".env"
            if env_file is not None and not source.is_file():
                raise ValueError("指定的模型配置文件不存在。")
            load_dotenv(source, override=True, encoding="utf-8")
            llm._ENV_FILE = source
        with evaluation_mode(live):
            yield
    finally:
        llm._ENV_FILE = previous_env_file
        for key in set(os.environ) - previous_environment.keys():
            del os.environ[key]
        os.environ.update(previous_environment)


async def generate_one(service: RecordingStudioService, index: int, material: str) -> dict:
    row = {
        "index": index, "material": material, "status": "failed", "quality": "fine",
        "story_id": None, "title": None, "elapsed_seconds": 0, "checked": None,
        "structure_ok": None, "structure_problems": [], "playability_ok": None,
        "playability_problems": [], "pipeline_problems": [], "error": None, "call_failures": [],
    }
    started = monotonic()
    job = None
    try:
        chat_id = service.create_chat("play")["chat_id"]
        chat = service.chats[chat_id]
        chat.materials = [material]
        chat.strategy = "new"
        chat.quality = "fine"
        chat.history = [{"role": "user", "content": material}]
        existing_tasks = set(service.tasks)
        job = service._start_job(chat_id, chat.history)
        await asyncio.gather(*(service.tasks - existing_tasks))
        if job.quality != "fine":
            raise ValueError("生成服务没有使用精修档，请检查任务 19 的版本。")
        row.update(status=job.status, story_id=job.story_id, error=job.error,
                   pipeline_problems=list(dict.fromkeys([*job.problems, *(job.invalid_problems if job.status != "done" else [])])))
        if job.status == "done":
            story = yaml.safe_load((service.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8"))
            row["title"] = story["title"]
            row["checked"] = story.get("checked") if type(story.get("checked")) is bool else None
            structure = checker.check_structure(story)
            row.update(structure_ok=structure["ok"], structure_problems=structure["problems"])
            if structure["ok"]:
                problems = checker.check_playability(story)
                row.update(playability_ok=not problems, playability_problems=problems)
    except Exception as error:
        row.update(status="failed", error=safe_error(error))
    finally:
        row["elapsed_seconds"] = round(monotonic() - started, 3)
        if job is not None:
            row["call_failures"] = [failure for job_id, failures in service.call_failures.items()
                                    if job_id == job.id or job_id.startswith(job.id + "-")
                                    for failure in failures]
    return row


async def run_batch(materials: list[str], stories_dir: Path, *, concurrency: int = 2, live: bool = False) -> dict:
    if type(concurrency) is not int or concurrency < 1:
        raise ValueError("concurrency 需要是正整数")
    stories_dir = stories_dir.resolve()
    with evaluation_mode(live):
        models = {"actor": os.getenv("LLM_ACTOR_MODEL") or "deepseek-flash",
                  "writer": os.getenv("LLM_WRITER_MODEL") or "deepseek-flash"}
        service = RecordingStudioService(stories_dir)
        semaphore = asyncio.Semaphore(concurrency)

        async def run(index, material):
            async with semaphore:
                return await generate_one(service, index, material)

        try:
            rows = await asyncio.gather(*(run(index, material) for index, material in enumerate(materials, 1)))
        finally:
            await service.close()
    return {
        "report_version": 1, "evaluation": "pregen", "mode": "live" if live else "mock",
        "quality": "fine", "models": models, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stories_dir": str(stories_dir.resolve()), "concurrency": concurrency,
        "summary": {"requested": len(rows), "done": sum(row["status"] == "done" for row in rows),
                    "checked": sum(row["checked"] is True for row in rows),
                    "failed": sum(row["status"] != "done" for row in rows),
                    "call_failures": sum(len(row["call_failures"]) for row in rows)},
        "rows": rows,
    }


def export_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    # CSV 的数组和结构化错误使用 JSON 单元格，保留每条具体诊断。
    csv_rows = [{key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                 for key, value in row.items()} for row in report["rows"]]
    json_path, csv_path = write_reports({**report, "rows": csv_rows}, output_dir, "pregen", CSV_COLUMNS)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按精修档批量生成 6–8 个案件，默认离线模拟。")
    parser.add_argument("--live", action="store_true", help="允许真实模型请求和计费")
    parser.add_argument("--env-file", type=Path, help="仅 --live 时加载的模型配置文件，不打印配置值")
    parser.add_argument("--materials", type=Path, help="UTF-8 JSON 字符串数组文件，默认使用内置八条题材")
    parser.add_argument("--count", type=sample_count, default=6)
    parser.add_argument("--concurrency", type=positive_int, default=2)
    parser.add_argument("--stories-dir", type=Path, default=ROOT / "data" / "stories")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "eval" / "pregen")
    args = parser.parse_args(argv)
    if args.env_file and not args.live:
        parser.error("--env-file 需要与 --live 一起使用。")
    try:
        materials = read_materials(args.materials, args.count)
        with generation_mode(args.live, args.env_file):
            report = asyncio.run(run_batch(materials, args.stories_dir, concurrency=args.concurrency, live=args.live))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    paths = export_report(report, args.output_dir)
    summary = report["summary"]
    print(f"{report['mode']} 精修批量完成，保存 {summary['done']}/{summary['requested']} 个，检查通过 {summary['checked']} 个，失败 {summary['failed']} 个。")
    if not args.live:
        print("模拟模式使用固定联调剧本，检查结果用于验证流程。")
    print(f"JSON {paths[0]}\nCSV {paths[1]}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
