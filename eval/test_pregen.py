"""精修批量工具的离线、并发、失败与结果导出回归。"""
import asyncio
from copy import deepcopy
import csv
import json
import os
from pathlib import Path

import pytest
import yaml

from backend import llm
from backend.studio import check as checker
from backend.studio.mock import mock_story
from backend.studio.service import StudioService
from eval import pregen


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")

    def no_client(*args, **kwargs):
        pytest.fail("批量工具测试禁止真实模型客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_client)
    monkeypatch.setattr(checker, "AsyncOpenAI", no_client)


@pytest.mark.parametrize("value", ["0", "5", "9", "-1", "abc"])
def test_cli_rejects_count_outside_six_to_eight(value, capsys):
    with pytest.raises(SystemExit) as error:
        pregen.main(["--count", value])
    assert error.value.code == 2
    assert "--count" in capsys.readouterr().err


@pytest.mark.parametrize("materials", [{"text": "想法"}, ["想法"] * 5, ["想法"] * 5 + [1], ["想法"] * 5 + [" "]])
def test_material_file_requires_enough_nonempty_strings(tmp_path, materials):
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(materials, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="非空字符串"):
        pregen.read_materials(path, 6)


def test_material_file_preserves_order_and_count(tmp_path):
    path = tmp_path / "materials.json"
    path.write_text(json.dumps([f" 题材{i} " for i in range(8)], ensure_ascii=False), encoding="utf-8-sig")
    assert pregen.read_materials(path, 7) == [f"题材{i}" for i in range(7)]


def test_mock_mode_skips_env_file_and_restores_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MOCK", "0")
    source = llm._ENV_FILE
    monkeypatch.setattr(pregen, "load_dotenv", lambda *args, **kwargs: pytest.fail("模拟模式不能加载配置文件。"))
    with pregen.generation_mode(False, tmp_path / "do-not-read.env"):
        assert os.environ["LLM_MOCK"] == "1"
        assert llm._ENV_FILE == Path(os.devnull)
    assert os.environ["LLM_MOCK"] == "0"
    assert llm._ENV_FILE == source


def test_env_file_is_rejected_without_live(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        pregen.main(["--env-file", str(tmp_path / "absent.env")])
    assert error.value.code == 2
    assert "--live" in capsys.readouterr().err


def test_live_env_file_is_loaded_only_inside_scope_and_never_printed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setenv("LLM_API_KEY", "old-test-key")
    path = tmp_path / "model.env"
    path.write_text("LLM_API_KEY=fake-canary-key\nLLM_MOCK=1\nPREGEN_TEMP_SETTING=test\n", encoding="utf-8")
    source = llm._ENV_FILE
    with pregen.generation_mode(True, path):
        assert os.environ["LLM_MOCK"] == "0"
        assert os.environ["LLM_API_KEY"] == "fake-canary-key"
        assert llm._ENV_FILE == path
    assert os.environ["LLM_API_KEY"] == "old-test-key"
    assert os.environ["LLM_MOCK"] == "1"
    assert "PREGEN_TEMP_SETTING" not in os.environ
    assert llm._ENV_FILE == source
    captured = capsys.readouterr()
    assert "fake-canary-key" not in captured.out + captured.err


def test_actual_mock_six_case_cli_saves_yaml_json_and_csv(tmp_path, capsys):
    stories_dir, output_dir = tmp_path / "stories", tmp_path / "results"
    code = pregen.main(["--stories-dir", str(stories_dir), "--output-dir", str(output_dir)])
    assert code == 0
    report = json.loads((output_dir / "pregen.json").read_text(encoding="utf-8"))
    assert report["mode"] == "mock" and report["quality"] == "fine"
    assert report["concurrency"] == 2
    assert report["summary"]["requested"] == report["summary"]["done"] == 6
    assert len(list(stories_dir.glob("*.yaml"))) == 6
    assert [row["index"] for row in report["rows"]] == list(range(1, 7))
    for row in report["rows"]:
        story = yaml.safe_load((stories_dir / f"{row['story_id']}.yaml").read_text(encoding="utf-8"))
        assert row["checked"] is story["checked"]
        assert row["structure_ok"] is True
        assert row["playability_ok"] == (not row["playability_problems"])
        assert row["pipeline_problems"] == (row["playability_problems"] if not story["checked"] else [])
        assert row["quality"] == "fine" and row["elapsed_seconds"] >= 0
    with (output_dir / "pregen.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 6
    assert json.loads(csv_rows[0]["pipeline_problems"]) == report["rows"][0]["pipeline_problems"]
    assert "模拟模式" in capsys.readouterr().out


def test_cli_accepts_relative_story_and_report_directories(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert pregen.main(["--stories-dir", "relative/stories", "--output-dir", "relative/results"]) == 0
    report = json.loads((tmp_path / "relative/results/pregen.json").read_text(encoding="utf-8"))
    assert report["stories_dir"] == str((tmp_path / "relative/stories").resolve())
    assert report["summary"]["done"] == 6


def test_concurrency_is_bounded_results_stay_in_material_order_and_failures_continue(monkeypatch, tmp_path):
    active = peak = 0
    qualities = []

    async def fake_generate(self, job, material, strategy):
        nonlocal active, peak
        qualities.append((job.quality, material, strategy))
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.02 if material == ["素材0"] else .001)
            if material == ["素材2"]:
                raise RuntimeError("provider-raw-canary")
            story = deepcopy(mock_story())
            story.update(id="generated-" + job.id, checked=False)
            self._save(story)
            job.story_id, job.status = story["id"], "done"
            job.problems = ["审稿记录：一处证据仍需复核。"]
        finally:
            active -= 1

    monkeypatch.setattr(StudioService, "_generate", fake_generate)
    report = asyncio.run(pregen.run_batch([f"素材{i}" for i in range(6)], tmp_path / "stories", concurrency=2))
    assert peak == 2 and active == 0
    assert len(qualities) == 6 and all(quality == "fine" and strategy == "new" for quality, _, strategy in qualities)
    assert [row["material"] for row in report["rows"]] == [f"素材{i}" for i in range(6)]
    assert report["summary"]["done"] == 5 and report["summary"]["failed"] == 1
    assert report["rows"][2]["error"]["type"] == "RuntimeError"
    assert "provider-raw-canary" not in json.dumps(report)
    assert report["rows"][0]["pipeline_problems"] == ["审稿记录：一处证据仍需复核。"]


def test_model_failures_in_fine_branches_are_recorded_without_raw_provider_text(monkeypatch, tmp_path):
    original = StudioService._model_call

    async def failed_first_branch(self, job, attempt, step, messages, **kwargs):
        if job.id.endswith("-1") and step == "设计稿":
            raise llm.LLMError("模型服务响应超时，请稍后重试。", status_code=504)
        return await original(self, job, attempt, step, messages, **kwargs)

    monkeypatch.setattr(StudioService, "_model_call", failed_first_branch)
    report = asyncio.run(pregen.run_batch(["一条测试素材"], tmp_path / "stories"))
    row = report["rows"][0]
    assert row["status"] == "done"
    assert len(row["call_failures"]) == 1
    failure = row["call_failures"][0]
    assert failure["attempt"] == 1 and failure["step"] == "设计稿"
    assert failure["type"] == "LLMError" and failure["status_code"] == 504
    assert failure["reason"] == "model_timeout"
    assert report["summary"]["call_failures"] == 1


def test_export_keeps_checked_false_unknown_and_specific_checks(tmp_path):
    rows = [{"index": 1, "checked": False, "structure_problems": ["c7 不可达。"], "call_failures": [{"step": "设计稿", "status_code": 504}]},
            {"index": 2, "checked": None, "structure_problems": [], "call_failures": []}]
    json_path, csv_path = pregen.export_report({"rows": rows}, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["rows"] == rows
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = list(csv.DictReader(handle))
    assert exported[0]["checked"] == "False" and exported[1]["checked"] == ""
    assert json.loads(exported[0]["structure_problems"]) == ["c7 不可达。"]
    assert json.loads(exported[0]["call_failures"])[0]["status_code"] == 504


def test_upstream_billing_status_is_recorded_without_provider_body(monkeypatch, tmp_path):
    class BillingError(RuntimeError):
        status_code = 402
    async def unavailable(*args, **kwargs):
        raise llm.LLMError("模型服务暂时不可用。") from BillingError("PRIVATE_PROVIDER_BODY")
    monkeypatch.setattr(StudioService, "_model_call", unavailable)
    report = asyncio.run(pregen.run_batch(["纯技术素材"], tmp_path / "stories"))
    failures = report["rows"][0]["call_failures"]
    assert failures and all(f["upstream_status_code"] == 402 for f in failures)
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(report)


@pytest.mark.parametrize("value", [0, -1, True, "2", 1.5])
def test_run_batch_rejects_invalid_concurrency(tmp_path, value):
    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(pregen.run_batch([], tmp_path, concurrency=value))
