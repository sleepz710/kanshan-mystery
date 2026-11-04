"""审稿指控复核的严格索引、调用上限和失败保稿。"""

from copy import deepcopy
import json

import httpx
from openai import APIStatusError
import pytest
import yaml

from backend import llm
from backend.studio import check as checker
from backend.studio.service import Job, REVIEW_VERIFY_RULES, StudioService


@pytest.fixture
def studio(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(checker, "check_playability", lambda story: [])

    def no_client(*args, **kwargs):
        pytest.fail("复核回归禁止创建真实模型客户端。")

    monkeypatch.setattr(llm, "AsyncOpenAI", no_client)
    monkeypatch.setattr(checker, "AsyncOpenAI", no_client)
    return StudioService(tmp_path / "stories")


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [[], [2, 0], [0, 1, 2]])
async def test_verification_returns_only_original_issues_in_original_order(studio, monkeypatch, indices):
    issues = ["第一条缺证", "第二条缺证", "第三条缺证"]
    design = {"intro": "固定设计"}
    calls = []

    async def complete(job, attempt, step, messages, **kwargs):
        calls.append((attempt, step, messages, kwargs))
        return {"keep_indices": indices}

    monkeypatch.setattr(studio, "_model_call", complete)
    before = deepcopy((design, issues))
    actual = await studio._verify_review(Job("verify", "chat", "play"), 2, design, issues)

    assert actual == [issue for index, issue in enumerate(issues) if index in indices]
    assert len(calls) == 1
    attempt, step, messages, kwargs = calls[0]
    assert (attempt, step, kwargs["role"]) == (2, "审稿复核", "actor")
    assert kwargs["mock_response"] == {"keep_indices": [0, 1, 2]}
    assert messages[0]["content"] == REVIEW_VERIFY_RULES
    assert json.loads(messages[1]["content"]) == {"design": design, "problems": issues}
    assert (design, issues) == before


@pytest.mark.asyncio
async def test_empty_review_has_no_verification_call(studio, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("初审无问题不能增加复核调用。")

    monkeypatch.setattr(studio, "_model_call", forbidden)
    assert await studio._verify_review(Job("empty", "chat", "play"), 1, {}, []) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    None, [], {}, {"keep_indices": None}, {"keep_indices": "0"},
    {"keep_indices": [0], "explanation": "额外字段"}, {"keep_indices": [True]},
    {"keep_indices": [False]}, {"keep_indices": [0.0]}, {"keep_indices": ["0"]},
    {"keep_indices": [0, 0]}, {"keep_indices": [-1]}, {"keep_indices": [2]},
    {"keep_indices": [[]]}, {"keep_indices": [{}]},
])
async def test_invalid_verification_keeps_every_issue_and_marks_incomplete(studio, monkeypatch, response):
    calls = []

    async def complete(*args, **kwargs):
        calls.append(args)
        return deepcopy(response)

    monkeypatch.setattr(studio, "_model_call", complete)
    issues = ["原问题一", "原问题二"]
    assert await studio._verify_review(Job("invalid", "chat", "play"), 1, {}, issues) == [
        *issues, "审稿复核未完成，保留原问题。",
    ]
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [checker.ModelTimeoutError(), checker.ReplyFormatError("回复坏了", "无效JSON")])
async def test_timeout_or_format_error_keeps_original_review(studio, monkeypatch, error):
    async def complete(*args, **kwargs):
        raise error

    monkeypatch.setattr(studio, "_model_call", complete)
    assert await studio._verify_review(Job("timeout", "chat", "play"), 1, {}, ["原问题"]) == [
        "原问题", "审稿复核未完成，保留原问题。",
    ]


def capture_pipeline(monkeypatch, job, verification):
    calls = []

    async def complete(messages, *, role, mock_response):
        kind = next(iter(mock_response))
        calls.append(kind)
        if kind == "problems":
            return {"problems": ["原具体缺证问题"]}
        if kind == "keep_indices":
            assert "原具体缺证问题" in job.draft_problems
            assert job.draft is not None
            if isinstance(verification, BaseException):
                raise verification
            return deepcopy(mock_response) if verification is None else deepcopy(verification)
        return deepcopy(mock_response)

    monkeypatch.setattr(checker, "complete_for", complete)
    return calls


@pytest.mark.asyncio
async def test_valid_verification_removes_false_issue_before_normal_blind_checks(studio, monkeypatch):
    job = Job("remove-false", "chat", "play")
    calls = capture_pipeline(monkeypatch, job, {"keep_indices": []})
    await studio._generate(job, ["技术素材"], "new")

    assert calls == ["design", "story", "problems", "keep_indices", "answers", "answers"]
    assert job.status == "done" and job.draft["checked"] is True
    assert job.problems == []


@pytest.mark.asyncio
async def test_mock_verification_keeps_all_original_issues(studio, monkeypatch):
    job = Job("mock-keep", "chat", "play")
    calls = capture_pipeline(monkeypatch, job, None)
    candidate = await studio._make_candidate(job, 1, ["技术素材"], "new", None, [], "generated-mock-keep")

    assert calls == ["design", "story", "problems", "keep_indices"]
    assert candidate.review == ["原具体缺证问题"]
    assert "原具体缺证问题" in job.draft_problems


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [402, 429, 503])
async def test_provider_error_stops_later_calls_and_preserves_first_review(studio, monkeypatch, status):
    upstream = APIStatusError("上游错误", response=httpx.Response(status, request=httpx.Request("POST", "https://model.invalid")), body={})
    error = llm.LLMError("模型服务暂时不可用。")
    error.__cause__ = upstream
    job = Job("provider-" + str(status), "chat", "play")
    calls = capture_pipeline(monkeypatch, job, error)
    await studio._generate(job, ["技术素材"], "new")

    assert calls == ["design", "story", "problems", "keep_indices"]
    assert job.status == "done" and job.draft["checked"] is False
    assert "原具体缺证问题" in job.problems
    assert any("未完成" in problem for problem in job.problems)
    published = yaml.safe_load((studio.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8"))
    assert published["checked"] is False
