"""评测模式、样本选择与结果导出。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from backend import llm


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def evaluation_mode(live: bool):
    """默认强制模拟并跳过真实 .env；--live 才允许读取模型配置。"""
    previous = os.environ.get("LLM_MOCK")
    env_file = llm._ENV_FILE
    os.environ["LLM_MOCK"] = "0" if live else "1"
    if not live:
        llm._ENV_FILE = Path(os.devnull)
    try:
        yield
    finally:
        llm._ENV_FILE = env_file
        if previous is None:
            os.environ.pop("LLM_MOCK", None)
        else:
            os.environ["LLM_MOCK"] = previous


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("需要填写正整数")
    return number


def safe_error(error: Exception) -> dict:
    """评测记录保留错误类型和状态码，不复制服务商异常正文。"""
    reasons = {
        "模型没有返回有效的 JSON，请重试。": "invalid_json",
        "模型返回的 JSON 必须是对象。": "invalid_json_object",
        "模型没有返回回复内容。": "empty_response",
        "模型回复超过长度限制，请缩短输入后重试。": "truncated_response",
        "角色返回的内容格式有误，请重试。": "invalid_actor_schema",
        "核查返回的内容格式有误，请重试。": "invalid_guard_schema",
        "核查返回的判定不完整，请重试。": "inconsistent_guard",
        "角色回复未通过核查，请重新提问。": "guard_rejected",
        "模型服务响应超时，请稍后重试。": "model_timeout",
        "模型服务请求失败，请检查模型配置后重试。": "provider_request_failed",
    }
    return {
        "type": type(error).__name__,
        "status_code": getattr(error, "status_code", None),
        "message": "调用或返回内容校验失败，请检查配置与对应模块。",
        "reason": reasons.get(str(error), "model_or_validation_error"),
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--live", action="store_true", help="显式允许真实模型请求和计费；默认只验证模拟管线")
    parser.add_argument("--story-id", help="只评测这个现有剧本；可选招牌案件作小规模验证")
    parser.add_argument("--stories-dir", type=Path, default=ROOT / "stories", help="现有固定剧本目录，只读")
    parser.add_argument("--generated-stories-dir", type=Path, default=ROOT / "data" / "stories", help="现有生成剧本目录，只读")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "eval", help="报告目录，默认 data/eval，不进入 Git")
    return parser


def select_samples(engine, story_id: str | None, *, generated_only: bool) -> list[dict]:
    catalog = engine.list_stories()
    if story_id:
        return [item for item in catalog if item["id"] == story_id]
    return [item for item in catalog if not generated_only or item["source"] == "generated"]


def base_report(kind: str, live: bool, engine) -> dict:
    return {
        "report_version": 1,
        "evaluation": kind,
        "mode": "live" if live else "mock",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_directories": {
            "official": str(engine.stories_dir),
            "generated": str(engine.generated_stories_dir),
        },
    }


def write_reports(report: dict, output_dir: Path, stem: str, columns: list[str]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = output_dir / f"{stem}.json", output_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["rows"])
    return json_path, csv_path
