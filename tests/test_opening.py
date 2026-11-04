"""开局盲答使用真实引擎权限，全部模型调用在本地替身中完成。"""

import json
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
import yaml

from backend.engine import GameEngine
from backend.studio import check as checker


def opening_story():
    return {
        "id": "opening-protocol", "title": "开局协议样本", "source": "generated", "intro": "公开汤面",
        "facts": [
            {"id": "f_public", "text": "PUBLIC_FACT"},
            {"id": "f_zhenxiang", "text": "CORE_SECRET q1=LEFT q2=RIGHT q3=LEFT q4=RIGHT"},
            {"id": "f_denied", "text": "LIE_ADMISSION_SECRET"},
            {"id": "f_followup", "text": "FUTURE_ADMISSION_SECRET"},
            {"id": "f_unknown", "text": "UNKNOWN_FACT_SECRET"},
        ],
        "characters": [
            {"id": "a", "name": "甲", "avatar": "a.png", "profile": "PUBLIC_PROFILE_A",
             "persona": "PRIVATE_PERSONA_A", "knows": ["f_public", "f_denied", "f_followup", "f_zhenxiang"],
             "secrets": [{"fact": "f_zhenxiang", "until": {"trust": 3}}], "trust_start": 0,
             "lies": [
                 {"id": "l1", "claim": "CURRENT_STATEMENT", "until": {"shown": "c0"}, "admit": "f_denied"},
                 {"id": "l2", "claim": "FUTURE_STATEMENT_SECRET", "until": {"exposed": "l1", "shown": "c1"}, "admit": "f_followup"},
             ]},
            {"id": "b", "name": "乙", "avatar": "b.png", "profile": "PUBLIC_PROFILE_B",
             "persona": "PRIVATE_PERSONA_B", "knows": ["f_zhenxiang"],
             "secrets": [{"fact": "f_zhenxiang", "until": {"trust": 2}}], "lies": [], "trust_start": 0},
        ],
        "clues": [
            {"id": "c0", "title": "PUBLIC_CLUE_TITLE", "content": "PUBLIC_CLUE", "holder": "a"},
            {"id": "c1", "title": "LOCKED_CLUE_TITLE", "content": "LOCKED_CLUE_SECRET", "holder": "b", "requires": {"trust": 1}},
            {"id": "c2", "title": "EVENT_CLUE_TITLE", "content": "EVENT_CLUE_SECRET", "holder": "a", "requires": {}},
        ],
        "events": [{"id": "e1", "when": {"to": "b", "shown": "c0"}, "confront": ["a", "b"], "unlock": ["c2"]}],
        "kanshan": {"greeting": "PUBLIC_GREETING", "hints": [{"done": {"has": "c0"}, "vague": "HINT_SECRET", "direct": "DIRECT_HINT_SECRET"}]},
        "ending": {
            "questions": [
                {"id": f"q{index}", "text": f"技术问题 {index}", "options": ["LEFT", "RIGHT"], "answer": answer}
                for index, answer in enumerate(["LEFT", "RIGHT", "LEFT", "RIGHT"], start=1)
            ],
            "endings": [
                {"id": "truth", "title": "答案", "text": "ENDING_TEXT_SECRET", "when": {"correct": ["q1", "q2", "q3", "q4"]}},
                {"id": "retry", "title": "继续", "text": "继续调查", "retry": True},
            ],
            "truth": "FULL_TRUTH_SECRET", "lessons": ["LESSON_SECRET"],
        },
    }


@pytest.fixture(autouse=True)
def no_checker_sdk(monkeypatch):
    def unexpected_client(*args, **kwargs):
        pytest.fail("开局测试不得创建真实模型客户端。")

    monkeypatch.setattr(checker, "AsyncOpenAI", unexpected_client)


def public_material(messages):
    return json.loads(messages[1]["content"])


async def material_solver(messages, *, role, mock_response):
    """只认技术样本已公开的完整记录，未获得记录时返回 null。"""
    material = public_material(messages)
    facts = [fact for character in material["characters"] for fact in character["facts"]]
    text = " ".join(fact["text"] for fact in facts)
    outcomes = dict(part.split("=") for part in text.split() if "=" in part)
    answers = {question["id"]: outcomes.get(question["id"]) for question in material["questions"]}
    evidence = {}
    for question_id, answer in answers.items():
        if answer is not None:
            quote = f"{question_id}={answer}"
            source = next(fact for fact in facts if quote in fact["text"])
            evidence[question_id] = [{"source_id": source["source_id"], "quote": quote}]
    return {"answers": answers, "evidence": evidence}


def null_reply():
    return {"answers": {f"q{index}": None for index in range(1, 5)}, "evidence": {}}


@pytest.mark.asyncio
async def test_unlocked_composite_fact_reveals_majority_and_names_all_knowers():
    story = opening_story()
    for character in story["characters"]:
        character["secrets"] = []
    before = deepcopy(story)
    model = AsyncMock(side_effect=material_solver)

    result = await checker.check_opening(story, complete=model)

    assert not result["ok"]
    assert len(result["problems"]) == 1
    problem = result["problems"][0]
    assert "4/4" in problem and "q1, q2, q3, q4" in problem
    assert "a 的公开事实 [f_public, f_zhenxiang]" in problem
    assert "b 的公开事实 [f_zhenxiang]" in problem
    assert "已核对引文来源为角色 a 的事实 f_zhenxiang" in problem
    assert "秘密锁" in problem and "profile" in problem
    assert model.await_count == 1 and model.call_args.kwargs["role"] == "actor"
    assert story == before


@pytest.mark.asyncio
async def test_locking_core_for_every_knower_prevents_opening_solution():
    model = AsyncMock(side_effect=material_solver)

    assert await checker.check_opening(opening_story(), complete=model) == {"ok": True, "problems": []}

    material = public_material(model.call_args.args[0])
    assert all("CORE_SECRET" not in fact["text"] for character in material["characters"] for fact in character["facts"])


@pytest.mark.asyncio
async def test_one_unlocked_knower_still_exposes_core_fact():
    story = opening_story()
    story["characters"][1]["secrets"] = []

    result = await checker.check_opening(story, complete=material_solver)

    assert not result["ok"] and "b 的公开事实 [f_zhenxiang]" in result["problems"][0]


@pytest.mark.asyncio
async def test_opening_payload_contains_only_initial_public_material():
    model = AsyncMock(return_value=null_reply())

    assert (await checker.check_opening(opening_story(), complete=model))["ok"]

    material = public_material(model.call_args.args[0])
    assert set(material) == {"intro", "greeting", "characters", "questions"}
    assert material["intro"]["text"] == "公开汤面" and material["greeting"]["text"] == "PUBLIC_GREETING"
    assert all(set(character) == {"id", "name", "profile", "facts", "available_clues", "statements"} for character in material["characters"])
    assert material["characters"][0]["facts"] == [{"source_id": "s4", "text": "PUBLIC_FACT"}]
    assert material["characters"][0]["available_clues"] == [{"source_id": "s5", "text": "PUBLIC_CLUE_TITLE\nPUBLIC_CLUE"}]
    assert material["characters"][0]["statements"] == ["CURRENT_STATEMENT"]
    assert material["characters"][1]["facts"] == []
    assert material["characters"][1]["available_clues"] == []
    assert all(set(question) == {"id", "text", "options"} for question in material["questions"])
    serialized = json.dumps(material)
    for hidden in (
        "CORE_SECRET", "LIE_ADMISSION_SECRET", "FUTURE_ADMISSION_SECRET", "UNKNOWN_FACT_SECRET",
        "PRIVATE_PERSONA", "LOCKED_CLUE", "EVENT_CLUE", "FUTURE_STATEMENT_SECRET", "HINT_SECRET",
        "ENDING_TEXT_SECRET", "FULL_TRUTH_SECRET", "LESSON_SECRET", "active_lies", "lies", "admit",
        "secrets", "until", "forbidden_facts", "trust", "answer", "f_public", "f_zhenxiang", '"c0"',
    ):
        assert hidden not in serialized


@pytest.mark.asyncio
async def test_public_profile_is_included_but_private_persona_is_excluded():
    story = opening_story()
    story["characters"][0]["profile"] = "PROFILE_CAN_REVEAL_ANSWERS"
    model = AsyncMock(return_value=null_reply())

    await checker.check_opening(story, complete=model)

    material = public_material(model.call_args.args[0])
    assert material["characters"][0]["profile"]["text"] == "PROFILE_CAN_REVEAL_ANSWERS"
    assert "PRIVATE_PERSONA" not in json.dumps(material)


@pytest.mark.parametrize("correct_count, expected_ok", [(0, True), (1, True), (2, True), (3, False), (4, False)])
@pytest.mark.asyncio
async def test_more_than_half_is_the_failure_threshold(correct_count, expected_ok):
    story = opening_story()
    story["characters"][0]["secrets"] = []

    async def limited_solver(messages, **kwargs):
        response = await material_solver(messages, **kwargs)
        for question in story["ending"]["questions"][correct_count:]:
            response["answers"][question["id"]] = None
            response["evidence"].pop(question["id"])
        return response

    model = AsyncMock(side_effect=limited_solver)

    result = await checker.check_opening(story, complete=model)

    assert result["ok"] is expected_ok
    assert bool(result["problems"]) is not expected_ok


@pytest.mark.parametrize("reply", [
    None, [], {}, {"answers": {}},
    {"answers": {"q1": None, "q2": None, "q3": None}},
    {"answers": {"q1": None, "q2": None, "q3": None, "q4": None, "extra": None}},
    {"answers": {"q1": "INVALID", "q2": None, "q3": None, "q4": None}},
    {"answers": {"q1": True, "q2": None, "q3": None, "q4": None}},
    {"answers": {"q1": ["LEFT"], "q2": None, "q3": None, "q4": None}},
])
@pytest.mark.asyncio
async def test_invalid_answers_raise_format_error(reply):
    model = AsyncMock(return_value=reply)

    with pytest.raises(checker.ReplyFormatError, match="answers"):
        await checker.check_opening(opening_story(), complete=model)


@pytest.mark.asyncio
async def test_mock_opening_returns_all_null_without_a_model_client():
    assert await checker.check_opening(opening_story()) == {"ok": True, "problems": []}


@pytest.mark.asyncio
async def test_invalid_story_does_not_call_a_model():
    story = opening_story()
    story["characters"][0]["knows"].append("missing")
    model = AsyncMock()

    result = await checker.check_opening(story, complete=model)

    assert not result["ok"] and any("missing" in problem for problem in result["problems"])
    model.assert_not_awaited()


@pytest.mark.parametrize("trust_start", [0, 1, 2, 3])
@pytest.mark.asyncio
async def test_opening_material_matches_a_real_new_game(tmp_path, monkeypatch, trust_start):
    story = opening_story()
    story["characters"][1]["trust_start"] = trust_start
    story_path = tmp_path / f"{story['id']}.yaml"
    story_path.write_text(yaml.safe_dump(story, allow_unicode=True), encoding="utf-8")
    engine = GameEngine(stories_dir=tmp_path / "official", generated_stories_dir=tmp_path)
    initial_state = GameEngine.initial_state
    created_states = []

    def record_initial_state(loaded_story):
        state = initial_state(loaded_story)
        created_states.append(state)
        return state

    monkeypatch.setattr(GameEngine, "initial_state", staticmethod(record_initial_state))
    public_game = engine.new_game(story["id"])
    game_state = engine.games[public_game["game_id"]]
    model = AsyncMock(return_value=null_reply())

    await checker.check_opening(story, complete=model)

    assert len(created_states) == 2
    assert created_states[0] is game_state
    expected_state = asdict(game_state)
    expected_state["story"] = checker.Story.model_validate(game_state.story).model_dump()
    assert asdict(created_states[1]) == expected_state
    material = public_material(model.call_args.args[0])
    for character in material["characters"]:
        context = engine._context(game_state, character["id"], "")
        assert [fact["text"] for fact in character["facts"]] == [fact["text"] for fact in context["facts"]]
        assert [clue["text"] for clue in character["available_clues"]] == [f"{clue['title']}\n{clue['content']}" for clue in context["available_clues"]]
        assert character["statements"] == [statement["claim"] for statement in context["active_lies"]]
    visible_b = next(character for character in material["characters"] if character["id"] == "b")
    assert bool(visible_b["facts"]) is (trust_start >= 2)
    assert bool(visible_b["available_clues"]) is (trust_start >= 1)
    assert not game_state.acquired_clues and not game_state.triggered_events and not game_state.exposed_lies
    assert game_state.turns == 0 and len(engine.games) == 1


def test_initial_states_have_independent_mutable_data():
    story = checker.Story.model_validate(opening_story()).model_dump()
    before = deepcopy(story)
    first = GameEngine.initial_state(story)
    second = GameEngine.initial_state(story)

    first.story["characters"][0]["profile"] = "CHANGED"
    first.trust["a"] = 3
    first.histories["a"].append({"role": "user", "content": "changed"})
    first.shown["a"].add("c0")
    first.acquired_clues.add("c0")

    assert story == before and second.story == before
    assert second.trust["a"] == 0 and second.histories["a"] == []
    assert second.shown["a"] == set() and second.acquired_clues == set()


@pytest.mark.parametrize("mutation", [
    lambda response: response.pop("evidence"),
    lambda response: response.update(evidence=None),
    lambda response: response.update(evidence=[]),
    lambda response: response["evidence"].update(extra=[]),
    lambda response: response["evidence"].pop("q1"),
    lambda response: response["evidence"].update(q1=[]),
    lambda response: response["evidence"].update(q1={"source_id": "s1", "quote": "公开汤面"}),
    lambda response: response["evidence"]["q1"][0].update(source_id="f_zhenxiang"),
    lambda response: response["evidence"]["q1"][0].update(source_id="l1"),
    lambda response: response["evidence"]["q1"][0].update(source_id="UNKNOWN_PROVIDER_SECRET"),
    lambda response: response["evidence"]["q1"][0].update(source_id=[]),
    lambda response: response["evidence"]["q1"][0].update(quote="UNKNOWN_FACT_SECRET"),
    lambda response: response["evidence"]["q1"][0].update(quote="PUBLIC_GREETING"),
    lambda response: response["evidence"]["q1"][0].update(quote="q1 should be LEFT"),
    lambda response: response["evidence"]["q1"][0].update(quote=""),
    lambda response: response["evidence"]["q1"][0].update(quote=" "),
    lambda response: response["evidence"]["q1"][0].update(quote=None),
    lambda response: response["evidence"]["q1"][0].update(quote=["q1=LEFT"]),
    lambda response: response["evidence"]["q1"][0].update(truth=True),
    lambda response: response["evidence"]["q1"].append({"source_id": "missing", "quote": "q1=LEFT"}),
])
@pytest.mark.asyncio
async def test_missing_or_invalid_evidence_keeps_check_incomplete(mutation):
    story = opening_story()
    story["characters"][0]["secrets"] = []

    async def invalid_solver(messages, **kwargs):
        response = await material_solver(messages, **kwargs)
        mutation(response)
        return response

    with pytest.raises(checker.ReplyFormatError, match="公开证据") as error:
        await checker.check_opening(story, complete=invalid_solver)

    assert "UNKNOWN_PROVIDER_SECRET" not in str(error.value)
    assert "UNKNOWN_PROVIDER_SECRET" not in error.value.detail


@pytest.mark.asyncio
async def test_guessing_all_correct_without_citations_is_not_a_completed_leak_check():
    story = opening_story()
    model = AsyncMock(return_value={
        "answers": {question["id"]: question["answer"] for question in story["ending"]["questions"]},
        "evidence": {},
    })

    with pytest.raises(checker.ReplyFormatError, match="公开证据"):
        await checker.check_opening(story, complete=model)


@pytest.mark.asyncio
async def test_wrong_guesses_without_citations_cannot_count_as_a_pass():
    model = AsyncMock(return_value={
        "answers": {"q1": "RIGHT", "q2": "LEFT", "q3": "RIGHT", "q4": "LEFT"},
        "evidence": {},
    })

    with pytest.raises(checker.ReplyFormatError, match="公开证据"):
        await checker.check_opening(opening_story(), complete=model)


@pytest.mark.parametrize("evidence", [{}, {f"q{index}": [] for index in range(1, 5)}])
@pytest.mark.asyncio
async def test_null_answers_accept_empty_evidence(evidence):
    response = null_reply()
    response["evidence"] = evidence

    result = await checker.check_opening(opening_story(), complete=AsyncMock(return_value=response))

    assert result == {"ok": True, "problems": []}


@pytest.mark.parametrize("mutation", [
    lambda response: response.pop("evidence"),
    lambda response: response["evidence"].update(q1=[{"source_id": "s1", "quote": "公开汤面"}]),
])
@pytest.mark.asyncio
async def test_null_response_still_requires_a_consistent_evidence_object(mutation):
    response = null_reply()
    mutation(response)

    with pytest.raises(checker.ReplyFormatError, match="公开证据"):
        await checker.check_opening(opening_story(), complete=AsyncMock(return_value=response))


@pytest.mark.asyncio
async def test_sources_are_neutral_and_prompt_requires_every_option_assertion():
    model = AsyncMock(return_value=null_reply())

    await checker.check_opening(opening_story(), complete=model)

    material = public_material(model.call_args.args[0])
    sources = [material["intro"], material["greeting"]]
    for character in material["characters"]:
        sources.extend([character["profile"], *character["facts"], *character["available_clues"]])
    assert all(set(source) == {"source_id", "text"} for source in sources)
    assert [source["source_id"] for source in sources] == [f"s{index}" for index in range(1, len(sources) + 1)]
    system_prompt = model.call_args.args[0][0]["content"]
    assert "所选选项的每个额外断言都必须由所引证据支撑" in system_prompt
    assert "无法支撑完整选项时填 null" in system_prompt
    assert "不能单独作为已发生事实的证据" in system_prompt
    assert model.call_args.kwargs["mock_response"] == null_reply()


@pytest.mark.parametrize("location", ["intro", "greeting", "profile", "fact", "clue"])
@pytest.mark.asyncio
async def test_supported_public_text_types_allow_exact_quotes(location):
    story = opening_story()
    record = "公开记录 q1=LEFT"
    if location == "intro":
        story["intro"] = record
    elif location == "greeting":
        story["kanshan"]["greeting"] = record
    elif location == "profile":
        story["characters"][0]["profile"] = record
    elif location == "fact":
        story["facts"][0]["text"] = record
    else:
        story["clues"][0]["content"] = record

    async def solver(messages, **kwargs):
        material = public_material(messages)
        first_character = material["characters"][0]
        sources = [material["intro"], material["greeting"], first_character["profile"], *first_character["facts"], *first_character["available_clues"]]
        source = next(source for source in sources if record in source["text"])
        response = null_reply()
        response["answers"]["q1"] = "LEFT"
        response["evidence"]["q1"] = [{"source_id": source["source_id"], "quote": "q1=LEFT"}]
        return response

    assert await checker.check_opening(story, complete=solver) == {"ok": True, "problems": []}
