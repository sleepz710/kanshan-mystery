"""任务 18/19 的调用边界、字段修补和不完整设计回归。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import pytest_asyncio
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
import yaml

from backend import llm
from backend.studio import check as checker, service as studio_service
from backend.studio.mock import mock_story
from backend.studio.service import Job, StudioService


@pytest_asyncio.fixture
async def studio(monkeypatch):
    with TemporaryDirectory(prefix="kanshan-task18-alignment-") as directory:
        monkeypatch.setenv("LLM_MOCK", "1")
        monkeypatch.setattr(llm, "_ENV_FILE", Path(directory) / "missing.env")
        for name in ("LLM_API_KEY", "LLM_WRITER_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        def no_sdk(*args, **kwargs):
            pytest.fail("流程回归必须使用离线模型替身。")

        monkeypatch.setattr(llm, "AsyncOpenAI", no_sdk)
        monkeypatch.setattr(checker, "AsyncOpenAI", no_sdk)
        monkeypatch.setattr(checker, "check_playability", lambda story: [])
        service = StudioService(Path(directory) / "stories")
        try:
            yield service
        finally:
            await service.close()


def capture_model(monkeypatch, transform=None):
    calls = []

    async def complete(messages, *, role, mock_response):
        kind = next(iter(mock_response))
        payload = json.loads(messages[-1]["content"])
        calls.append({"kind": kind, "role": role, "payload": payload, "system": messages[0]["content"]})
        response = deepcopy(mock_response)
        if transform is not None:
            return await transform(kind, payload, response)
        return response

    monkeypatch.setattr(checker, "complete_for", complete)
    return calls


def saved_story(studio, job):
    return yaml.safe_load((studio.stories_dir / f"{job.story_id}.yaml").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_fast_confirmation_runs_five_steps_and_reviews_only_design(studio, monkeypatch):
    calls = capture_model(monkeypatch)
    chat_id = studio.create_chat("play")["chat_id"]
    studio.chats[chat_id].materials = ["一封信的技术回归素材"]
    studio.chats[chat_id].asked = True

    response = await studio.message(chat_id, "快速", {})
    await asyncio.gather(*list(studio.tasks))
    job = studio.jobs[response["job"]["id"]]

    assert response["job"]["quality"] == job.public()["quality"] == "fast"
    assert [(call["kind"], call["role"]) for call in calls] == [
        ("design", "writer"), ("story", "actor"), ("problems", "actor"),
        ("answers", "writer"), ("answers", "actor"),
    ]
    review = calls[2]["payload"]
    assert set(review) == {"design", "strategy"}
    assert review["design"] == calls[1]["payload"]["design"]
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
async def test_generation_prompts_keep_evidence_and_supported_conditions(studio, monkeypatch):
    calls = capture_model(monkeypatch)
    await studio._generate(Job("evidence-contract", "chat", "play"), ["技术素材"], "new")

    design_prompt = calls[0]["system"]
    fill_prompt = calls[1]["system"]
    assert "时间区间给出上下界证据" in design_prompt
    assert "口供是答案必要依据时" in design_prompt
    assert "拆谎证据必须先于该谎的承认可取得" in design_prompt
    assert "每个人都加锁" in fill_prompt
    assert "线索content逐字保留设计稿content" in fill_prompt
    assert "问题text/options/answer逐字保留" in fill_prompt
    assert '"done":{"has":"c1"}' in fill_prompt
    assert '"shown":"c1","has":"c2"' in fill_prompt
    assert "lies.until禁止引用自身的exposed" in fill_prompt
    assert "物证内容留在线索中" in fill_prompt
    review_prompt = calls[2]["system"]
    assert "线索正文是作者确认的客观事实" in review_prompt
    assert "每条必须指出现有文本的具体冲突或缺口" in review_prompt
    assert "错误选项用于排除，可以与证据冲突" in review_prompt
    assert "不能凭truth、proves、常识或人物私有secret补齐玩家证据" in review_prompt
    assert "改口须直接纠正同一句谎话" in review_prompt
    assert "直接反驳characters.lie的旧话" in review_prompt
    assert "characters.correction是拆穿后承认的更正" in review_prompt
    assert "不能把correction当作需要反驳的对象" in review_prompt
    assert "人物evidence写明持有人及直接材料，且该材料acquire可达" in review_prompt
    assert "不要求另加口供、编号或引擎条件语法" in review_prompt
    assert "卡号的登记人不能直接等同实际刷卡者" in review_prompt
    assert "关联的早年隐情无法替代当晚行踪的纠正" in review_prompt


@pytest.mark.asyncio
async def test_format_retry_requests_fields_without_rewriting_evidence(studio, monkeypatch):
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["kanshan"]["hints"][0]["done"] = {"shown": "c1"}
            else:
                return {"fields": {"kanshan": {"hints": mock_story()["kanshan"]["hints"]}}}
        return response

    calls = capture_model(monkeypatch, repair)
    job = Job("condition-repair", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    requests = [call for call in calls if call["kind"] == "story"]
    assert len(requests) == 2
    assert requests[0]["payload"]["design"] == requests[1]["payload"]["design"]
    assert "优先只返回JSON" in requests[1]["system"]
    assert "只改报错处，保留其他条件、线索内容和证据对应" in requests[1]["system"]
    assert saved_story(studio, job)["clues"] == checker.Story.model_validate(mock_story()).model_dump()["clues"]
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
async def test_mismatched_lie_evidence_is_repaired_with_the_same_design(studio, monkeypatch):
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "design":
            response["design"]["characters"][0]["evidence"] = "王平持有的监控记录"
        elif kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["characters"][0]["lies"][0]["until"] = {"shown": "c3"}
            else:
                return {"fields": {"characters": mock_story()["characters"]}}
        return response

    calls = capture_model(monkeypatch, repair)
    job = Job("evidence-repair", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    requests = [call for call in calls if call["kind"] == "story"]
    assert len(requests) == 2
    assert requests[0]["payload"]["design"] == requests[1]["payload"]["design"]
    assert any("l1" in problem and "监控记录" in problem for problem in requests[1]["payload"]["problems"])
    assert saved_story(studio, job)["characters"][0]["lies"][0]["until"] == {"shown": "c1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_draft", [False, True])
async def test_three_mismatched_evidence_fills_preserve_existing_draft(studio, monkeypatch, existing_draft):
    async def wrong_evidence(kind, payload, response):
        if kind == "design":
            response["design"]["characters"][0]["evidence"] = "王平持有的监控记录"
        elif kind == "story":
            response["story"]["characters"][0]["lies"][0]["until"] = {"shown": "c3"}
        return response

    calls = capture_model(monkeypatch, wrong_evidence)
    job = Job("evidence-exhausted", "chat", "play")
    previous = checker.Story.model_validate(mock_story()).model_dump() if existing_draft else None
    job.draft, job.draft_problems = previous, ["原稿问题"] if previous else []
    candidate = await studio._make_candidate(job, 1, ["技术素材"], "new", None, [], "generated-evidence")

    assert [call["kind"] for call in calls] == ["design", "story", "story", "story"]
    assert candidate.story is None and candidate.local
    assert job.draft is previous
    assert job.draft_problems == (["原稿问题"] if existing_draft else [])
    assert job.invalid_draft is not None


def test_cross_character_secret_copy_requires_its_own_lock():
    story = checker.Story.model_validate(mock_story()).model_dump()
    story["characters"][2]["knows"].append("f1")
    problems = StudioService._evidence_problems(StudioService._mock_design(), story)
    assert len(problems) == 1 and "wang" in problems[0] and "f1" in problems[0]


def test_show_requirement_cannot_be_replaced_by_plain_possession():
    design = StudioService._mock_design()
    design["clues"][3]["acquire"] = "向林青出示监控记录后交出寄件单"
    story = checker.Story.model_validate(mock_story()).model_dump()
    story["clues"][3]["requires"] = {"has": "c1"}
    problems = StudioService._evidence_problems(design, story)
    assert len(problems) == 1 and "c4" in problems[0] and "shown" in problems[0]
    story["clues"][3]["requires"] = {"event": "e1"}
    assert StudioService._evidence_problems(design, story) == []


def test_evidence_reference_accepts_a_renamed_title_with_identical_content():
    design = StudioService._mock_design()
    design["characters"][0]["evidence"] = "王平持有的监控记录"
    story = checker.Story.model_validate(mock_story()).model_dump()
    story["clues"][0]["title"] = "监控记录副本"
    assert StudioService._evidence_problems(design, story) == []


@pytest.mark.asyncio
async def test_fine_first_round_verifies_only_reported_issues_and_blind_tests_selected_story(studio, monkeypatch):
    both_designs_started = asyncio.Event()
    designs_started = 0

    async def choose(kind, payload, response):
        nonlocal designs_started
        if kind == "design":
            designs_started += 1
            branch = designs_started
            if designs_started == 2:
                both_designs_started.set()
            await asyncio.wait_for(both_designs_started.wait(), timeout=1)
            response["design"]["intro"] = f"独立技术方案{branch}"
            response["design"]["clues"][0]["content"] += response["design"]["intro"]
        elif kind == "story":
            response["story"]["intro"] = payload["design"]["intro"]
            response["story"]["title"] = payload["design"]["intro"]
            response["story"]["clues"][0]["content"] = payload["design"]["clues"][0]["content"]
        elif kind == "problems" and payload["design"]["intro"] == "独立技术方案1":
            response["problems"] = ["方案一需要补充证据动机。"]
        return response

    calls = capture_model(monkeypatch, choose)
    job = Job("fine-alignment", "chat", "play", quality="fine")
    await studio._generate(job, ["技术素材"], "new")

    assert len(calls) == 9
    assert [call["kind"] for call in calls].count("design") == 2
    assert [call["kind"] for call in calls].count("story") == 2
    assert [call["kind"] for call in calls].count("problems") == 2
    assert [call["kind"] for call in calls].count("keep_indices") == 1
    assert [call["kind"] for call in calls[:2]] == ["design", "design"]
    assert [(call["kind"], call["role"]) for call in calls[-2:]] == [
        ("answers", "writer"), ("answers", "actor"),
    ]
    assert all(call["role"] == "writer" for call in calls if call["kind"] == "design")
    assert all(call["role"] == "actor" for call in calls if call["kind"] in {"story", "problems", "keep_indices"})
    assert all(call["payload"]["intro"] == "独立技术方案2" for call in calls[-2:])
    assert "独立技术方案2" in calls[-1]["payload"]["clues"][0]["content"]
    assert job.status == "done" and saved_story(studio, job)["title"] == "独立技术方案2"
    assert saved_story(studio, job)["checked"] is True
    assert len(list(studio.stories_dir.glob("*.yaml"))) == 1


@pytest.mark.asyncio
async def test_three_failed_fills_start_new_design_instead_of_fourth_fill(studio, monkeypatch):
    design_count = 0

    async def fail_first_design(kind, payload, response):
        nonlocal design_count
        if kind == "design":
            design_count += 1
            response["design"]["intro"] = f"技术设计{design_count}"
        elif kind == "story" and design_count == 1:
            response["story"]["characters"][0]["knows"] = ["unknown_fact"]
        return response

    calls = capture_model(monkeypatch, fail_first_design)
    job = Job("fill-exhausted", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    assert [call["kind"] for call in calls] == [
        "design", "story", "story", "story", "design", "story", "problems", "answers", "answers",
    ]
    fills = [call["payload"] for call in calls if call["kind"] == "story"]
    assert fills[0]["design"] == fills[1]["design"] == fills[2]["design"]
    assert fills[3]["design"]["intro"] == "技术设计2"
    assert any("unknown_fact" in problem for problem in fills[2]["problems"])
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
async def test_ending_fields_preserve_truth_questions_and_replace_endings_array(studio, monkeypatch):
    original = mock_story()
    replacement = [deepcopy(original["ending"]["endings"][0]), deepcopy(original["ending"]["endings"][-1])]
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["ending"]["endings"][-1]["text"] = ""
            else:
                return {"fields": {"ending": {"endings": replacement}}}
        return response

    calls = capture_model(monkeypatch, repair)
    job = Job("ending-fields", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    story = saved_story(studio, job)
    assert story["ending"]["truth"] == original["ending"]["truth"]
    assert story["ending"]["questions"] == original["ending"]["questions"]
    assert [ending["id"] for ending in story["ending"]["endings"]] == [item["id"] for item in replacement]
    assert story["ending"]["lessons"] == original["ending"]["lessons"]
    assert fills == 2 and len([call for call in calls if call["kind"] == "design"]) == 1
    assert job.status == "done" and story["checked"] is True


@pytest.mark.asyncio
async def test_kanshan_fields_preserve_greeting_and_replace_hints(studio, monkeypatch):
    original = mock_story()
    replacement = [deepcopy(original["kanshan"]["hints"][0])]
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["kanshan"]["hints"][-1]["direct"] = ""
            else:
                return {"fields": {"kanshan": {"hints": replacement}}}
        return response

    capture_model(monkeypatch, repair)
    job = Job("kanshan-fields", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    story = saved_story(studio, job)
    assert story["kanshan"]["greeting"] == original["kanshan"]["greeting"]
    assert story["kanshan"]["hints"] == replacement
    assert fills == 2 and story["checked"] is True


@pytest.mark.asyncio
async def test_top_level_array_fields_replace_the_whole_previous_array(studio, monkeypatch):
    replacement = deepcopy(mock_story()["clues"])
    replacement[0]["title"] = "修正后的监控记录"
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["clues"][0]["holder"] = "missing_character"
                response["story"]["clues"].append({"id": "stale_clue", "title": "待移除的材料", "content": "旧版多余材料", "holder": "wang"})
            else:
                return {"fields": {"clues": replacement}}
        return response

    capture_model(monkeypatch, repair)
    job = Job("array-fields", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    story = saved_story(studio, job)
    assert [clue["id"] for clue in story["clues"]] == [clue["id"] for clue in replacement]
    assert story["clues"][0]["title"] == "修正后的监控记录"
    assert "stale_clue" not in {clue["id"] for clue in story["clues"]}
    assert fills == 2 and story["checked"] is True


@pytest.mark.asyncio
async def test_first_fill_fields_require_a_complete_story_before_any_merge(studio, monkeypatch):
    fills = 0

    async def first_fields(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                return {"fields": {"title": "没有完整旧稿"}}
        return response

    calls = capture_model(monkeypatch, first_fields)
    job = Job("first-fields", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    requests = [call for call in calls if call["kind"] == "story"]
    assert len(requests) == 2 and requests[1]["payload"]["previous_story"] is None
    assert any("首次填表" in problem and "完整" in problem for problem in requests[1]["payload"]["problems"])
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("id", "hijacked"), ("source", "official"), ("checked", True), ("unknown", "extra")])
async def test_fields_reject_metadata_and_unknown_keys_without_modifying_previous_story(studio, monkeypatch, field, value):
    fills = 0

    async def repair(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"].pop("intro")
            elif fills == 2:
                return {"fields": {"intro": mock_story()["intro"], field: value}}
            else:
                return {"fields": {"intro": mock_story()["intro"]}}
        return response

    calls = capture_model(monkeypatch, repair)
    job = Job("metadata-fields", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    requests = [call for call in calls if call["kind"] == "story"]
    assert len(requests) == 3
    assert "intro" not in requests[2]["payload"]["previous_story"]
    assert any("fields须为" in problem for problem in requests[2]["payload"]["problems"])
    story = saved_story(studio, job)
    assert story["id"] == job.story_id and story["id"].startswith("generated-")
    assert story["source"] == "generated" and "unknown" not in story
    assert job.status == "done" and story["checked"] is True


@pytest.mark.asyncio
async def test_bare_complete_design_proceeds_without_an_extra_design_request(studio, monkeypatch):
    async def bare_design(kind, payload, response):
        return response["design"] if kind == "design" else response

    calls = capture_model(monkeypatch, bare_design)
    job = Job("bare-design", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    assert len(calls) == 5
    assert calls[1]["payload"]["design"] == StudioService._mock_design()
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
async def test_incomplete_bare_design_cannot_fill_using_previous_valid_design(studio, monkeypatch):
    previous = StudioService._mock_design()
    incomplete = deepcopy(previous)
    incomplete.pop("timeline")

    async def missing_design_field(kind, payload, response):
        assert kind == "design", "缺少设计字段时应返回具体问题，不能进入填表。"
        assert payload["previous_design"] == previous
        return incomplete

    calls = capture_model(monkeypatch, missing_design_field)
    job = Job("incomplete-design", "chat", "play")
    candidate = await studio._make_candidate(job, 2, ["技术素材"], "new", previous, [], "generated-incomplete")

    assert len(calls) == 1 and candidate.story is None and candidate.local
    assert job.draft is None and not list(studio.stories_dir.glob("*.yaml"))


@pytest.mark.asyncio
async def test_review_timeout_publishes_existing_local_candidate_as_unchecked(studio, monkeypatch):
    async def timeout_review(kind, payload, response):
        if kind == "problems":
            raise checker.ModelTimeoutError("技术测试审稿超时。")
        return response

    calls = capture_model(monkeypatch, timeout_review)
    job = Job("review-timeout", "chat", "play")
    await studio._generate(job, ["技术素材"], "new")

    assert [(call["kind"], call["role"]) for call in calls] == [
        ("design", "writer"), ("story", "actor"), ("problems", "actor"),
    ]
    story = saved_story(studio, job)
    assert job.status == "done" and story["checked"] is False
    assert story["title"] == mock_story()["title"]
    assert any("未完成" in problem for problem in job.problems)
    assert mock_story()["ending"]["truth"] not in json.dumps(job.public(), ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("section,field,value", [
    ("characters", "name", ["非法数组姓名"]),
    ("clues", "holder", {"name": "非法对象持有人"}),
    ("questions", "evidence", "非法单字符串依据"),
])
async def test_bad_nested_design_preserves_previous_playable_story(studio, monkeypatch, section, field, value):
    designs = 0

    async def later_bad_design(kind, payload, response):
        nonlocal designs
        if kind == "design":
            designs += 1
            if designs > 1:
                response["design"][section][0][field] = value
        elif kind == "problems":
            response["problems"] = ["需要下一轮补充动机材料"]
        return response

    calls = capture_model(monkeypatch, later_bad_design)
    job = Job("nested-design-preserve", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")

    assert designs == 3
    assert len([call for call in calls if call["kind"] == "story"]) == 1
    story = saved_story(studio, job)
    assert job.status == "done" and story["title"] == mock_story()["title"]
    assert story["checked"] is False
    assert any(section in problem and field in problem for problem in calls[-1]["payload"]["problems"])
    assert story["ending"]["truth"] not in json.dumps(job.public(), ensure_ascii=False)


@pytest.mark.asyncio
async def test_wrong_requested_design_size_retains_previous_quality_problems(studio, monkeypatch):
    capture_model(monkeypatch)
    job = Job("design-size-feedback", "chat", "play")
    previous_problems = ["上一轮角色动机缺少可取得证据"]
    candidate = await studio._make_candidate(
        job, 2, ["请使用9条线索"], "new", StudioService._mock_design(), previous_problems, "generated-size",
    )
    assert candidate.story is None and job.draft is None
    assert previous_problems[0] in candidate.local
    assert any("9 条线索" in problem for problem in candidate.local)


def provider_failure(kind):
    request = httpx.Request("POST", "https://model.example.test/v1/chat/completions")
    if kind == "connection":
        return APIConnectionError(request=request)
    if kind == "timeout":
        return APITimeoutError(request=request)
    return APIStatusError("PRIVATE_PROVIDER_ERROR", response=httpx.Response(kind, request=request), body=None)


def raise_model_failure(kind):
    raise llm.LLMError("模型服务暂时不可用。") from provider_failure(kind)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection", "timeout", 500, 503])
async def test_transient_fill_failure_retries_the_same_design(studio, monkeypatch, failure):
    fills = 0

    async def first_fill_fails(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                raise_model_failure(failure)
        return response

    calls = capture_model(monkeypatch, first_fill_fails)
    job = Job("fill-transport-recovery", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    fill_calls = [call for call in calls if call["kind"] == "story"]
    assert len([call for call in calls if call["kind"] == "design"]) == 1
    assert len(fill_calls) == 2
    assert fill_calls[0]["payload"]["design"] == fill_calls[1]["payload"]["design"]
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [400, 401, 402, 429])
async def test_nonretryable_fill_failure_stops_without_new_design(studio, monkeypatch, failure):
    async def fail_fill(kind, payload, response):
        if kind == "story":
            raise_model_failure(failure)
        return response

    calls = capture_model(monkeypatch, fail_fill)
    job = Job("fill-provider-rejection", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    assert [call["kind"] for call in calls] == ["design", "story"]
    assert job.status == "failed" and job.story_id is None


@pytest.mark.asyncio
async def test_three_transient_fill_failures_publish_previous_playable_draft(studio, monkeypatch):
    async def fail_fill(kind, payload, response):
        if kind == "story":
            raise_model_failure("connection")
        return response

    calls = capture_model(monkeypatch, fail_fill)
    job = Job("fill-keep-draft", "chat", "play")
    job.draft = checker.Story.model_validate(mock_story()).model_dump()
    job.draft["title"] = "原可运行稿"
    job.draft_problems = ["原稿动机待补"]
    await studio._generate(job, ["技术回归素材"], "new")
    assert [call["kind"] for call in calls] == ["design", "story", "story", "story"]
    story = saved_story(studio, job)
    assert job.status == "done" and story["title"] == "原可运行稿" and story["checked"] is False
    assert "原稿动机待补" in job.problems


@pytest.mark.asyncio
async def test_fill_transport_failure_preserves_private_invalid_draft(studio, monkeypatch):
    fills = 0

    async def invalid_then_unavailable(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"]["title"] = "保留私有坏稿"
                response["story"]["characters"][0]["knows"] = ["unknown_fact"]
            else:
                raise_model_failure("connection")
        return response

    calls = capture_model(monkeypatch, invalid_then_unavailable)
    job = Job("fill-keep-invalid", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    assert [call["kind"] for call in calls] == ["design", "story", "story", "story"]
    assert job.status == "failed" and not list(studio.stories_dir.glob("*.yaml"))
    private = yaml.safe_load((studio.stories_dir.parent / "drafts" / f"{job.id}.yaml").read_text(encoding="utf-8"))
    assert private["story"]["title"] == "保留私有坏稿" and private["checked"] is False
    assert any("unknown_fact" in problem for problem in private["problems"])


@pytest.mark.asyncio
async def test_fill_retry_preserves_fields_and_format_problems(studio, monkeypatch):
    fills = 0

    async def format_then_transport_then_fields(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                response["story"].pop("intro")
            elif fills == 2:
                raise_model_failure("connection")
            else:
                return {"fields": {"intro": mock_story()["intro"]}}
        return response

    calls = capture_model(monkeypatch, format_then_transport_then_fields)
    job = Job("fill-keep-fields", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    fill_calls = [call for call in calls if call["kind"] == "story"]
    assert len(fill_calls) == 3
    assert "intro" not in fill_calls[-1]["payload"]["previous_story"]
    assert any("intro" in problem for problem in fill_calls[-1]["payload"]["problems"])
    assert any("短暂中断" in problem for problem in fill_calls[-1]["payload"]["problems"])
    assert job.status == "done" and saved_story(studio, job)["checked"] is True


@pytest.mark.asyncio
async def test_fill_transport_retry_remains_inside_original_total_budget(studio, monkeypatch):
    fills = 0

    async def retry_then_wait(kind, payload, response):
        nonlocal fills
        if kind == "story":
            fills += 1
            if fills == 1:
                raise_model_failure("connection")
            await asyncio.Event().wait()
        return response

    calls = capture_model(monkeypatch, retry_then_wait)
    monkeypatch.setattr(studio_service, "GENERATION_TIMEOUT", studio_service.SAVE_RESERVE + 0.03)
    job = Job("fill-original-budget", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    assert [call["kind"] for call in calls] == ["design", "story", "story"]
    assert job.status == "failed" and job.error == "生成超时，请重试。"


@pytest.mark.asyncio
async def test_correction_mismatch_retries_fill_without_redesign(studio, monkeypatch):
    correction = "林青承认自己碰过信件。"
    fills = 0

    async def bind_correction(kind, payload, response):
        nonlocal fills
        if kind == "design":
            response["design"]["characters"][0]["correction"] = correction
        elif kind == "story":
            fills += 1
            if fills > 1:
                facts = mock_story()["facts"]
                facts[0]["text"] = correction
                return {"fields": {"facts": facts}}
        return response

    calls = capture_model(monkeypatch, bind_correction)
    job = Job("fill-correction", "chat", "play")
    await studio._generate(job, ["技术回归素材"], "new")
    assert len([call for call in calls if call["kind"] == "design"]) == 1
    fill_calls = [call for call in calls if call["kind"] == "story"]
    assert len(fill_calls) == 2
    assert any("correction" in problem for problem in fill_calls[-1]["payload"]["problems"])
    assert job.status == "done" and saved_story(studio, job)["facts"][0]["text"] == correction
