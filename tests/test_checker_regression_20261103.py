"""离线复现盲答边界，并对照检查器与真实引擎的条件/结局行为。"""

from copy import deepcopy
from itertools import product

import pytest
import yaml

from backend import agents, llm
from backend.engine import GameEngine, GameError
from backend.studio import check as checker
from backend.studio.mock import mock_story


@pytest.fixture(autouse=True)
def forbid_both_model_clients(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "absent-model-config.env")
    monkeypatch.setenv("LLM_MOCK", "1")

    def forbidden_client(*args, **kwargs):
        pytest.fail("本回归测试不允许创建模型客户端")

    monkeypatch.setattr(llm, "AsyncOpenAI", forbidden_client)
    monkeypatch.setattr(checker, "AsyncOpenAI", forbidden_client)


def open_technical_story(tmp_path, story, *, normalize=True):
    candidate = checker.Story.model_validate(story).model_dump() if normalize else deepcopy(story)
    directory = tmp_path / "generated"
    directory.mkdir(exist_ok=True)
    (directory / f"{candidate['id']}.yaml").write_text(
        yaml.safe_dump(candidate, allow_unicode=True), encoding="utf-8"
    )
    engine = GameEngine(tmp_path / "official", directory)
    game = engine.new_game(candidate["id"])
    return engine, game["game_id"]


@pytest.fixture
def deterministic_agents(monkeypatch):
    async def reply(context, *, retry_leaked=None):
        return {"reply": "测试回复", "reveal": [c["id"] for c in context["available_clues"]], "trust_delta": 1}

    async def guard(context, candidate):
        return {"ok": True, "leaked": [], "contradiction": ""}

    async def confront(contexts, event):
        return [{"speaker": context["character"]["id"], "text": "测试对质"} for context in contexts]

    monkeypatch.setattr(agents, "reply", reply)
    monkeypatch.setattr(agents, "check_reply", guard)
    monkeypatch.setattr(agents, "confront", confront)


def answer_maps(story):
    correct = {q["id"]: q["answer"] for q in story["ending"]["questions"]}
    unknown = dict.fromkeys(correct, None)
    return correct, unknown


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_intro", [
    {},
    {"ghost": "不存在的选项"},
    {"q1": "不在选项内", "q2": "不在选项内", "q3": "不在选项内"},
    {"q1": None},
])
async def test_invalid_intro_answer_map_is_a_format_error_not_a_clean_check(bad_intro):
    story = mock_story()
    correct, _ = answer_maps(story)

    async def fake_complete(messages, *, role, mock_response):
        return {"answers": deepcopy(bad_intro if role == "writer" else correct)}

    # 无法推断应显式返回每题 null，不能把漏题或非法选项当作成功的汤面盲答。
    with pytest.raises(checker.ReplyFormatError):
        await checker.check(story, complete=fake_complete)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["extra_id", "missing_id", "invalid_option"])
async def test_invalid_clue_answer_map_is_a_format_error_not_missing_evidence(mutation):
    story = mock_story()
    correct, unknown = answer_maps(story)
    malformed = dict(correct)
    if mutation == "extra_id":
        malformed["ghost"] = "不存在的选项"
    elif mutation == "missing_id":
        malformed.pop("q2")
    else:
        malformed["q2"] = "不在选项内"

    async def fake_complete(messages, *, role, mock_response):
        return {"answers": deepcopy(unknown if role == "writer" else malformed)}

    with pytest.raises(checker.ReplyFormatError):
        await checker.check(story, complete=fake_complete)


@pytest.mark.asyncio
@pytest.mark.parametrize("clue_unknown", [False, True])
async def test_complete_valid_answer_maps_keep_unknown_distinct_from_format_failure(clue_unknown):
    story = mock_story()
    correct, unknown = answer_maps(story)

    async def fake_complete(messages, *, role, mock_response):
        return {"answers": deepcopy(unknown if role == "writer" or clue_unknown else correct)}

    result = await checker.check(story, complete=fake_complete)
    assert result["ok"] is (not clue_unknown)
    assert len(result["problems"]) == (3 if clue_unknown else 0)


@pytest.mark.parametrize("when", [
    {"shown": "c2", "to": "chen"},
    {"has": "c2", "to": "chen"},
    {"exposed": "l2", "to": "chen"},
    {"trust": 3, "to": "chen"},
])
def test_structure_approved_event_conditions_open_in_engine(tmp_path, when):
    story = mock_story()
    story["events"][0]["when"] = when
    assert checker.check_structure(story) == {"ok": True, "problems": []}
    engine, game_id = open_technical_story(tmp_path, story)
    assert engine.games[game_id].story["events"][0]["when"] == when


@pytest.mark.asyncio
@pytest.mark.parametrize("graph", ["ordinary", "clue_lie_cycle", "event_reward_cycle", "event_chain"])
async def test_reachability_matches_engine_actions_with_optimistic_actor(tmp_path, deterministic_agents, graph):
    story = mock_story()
    if graph == "clue_lie_cycle":
        story["clues"][0]["requires"] = {"exposed": "l1"}
    elif graph == "event_reward_cycle":
        story["events"][0]["when"] = {"has": "c8", "to": "chen"}
    elif graph == "event_chain":
        story["events"].append({
            "id": "e2", "when": {"event": "e1", "to": "lin"},
            "confront": ["lin", "wang"], "unlock": ["c7"],
        })
    checked = checker.check_structure(story)
    engine, game_id = open_technical_story(tmp_path, story)
    for _ in range(12):
        state = engine.games[game_id]
        before = (set(state.acquired_clues), set(state.exposed_lies), set(state.triggered_events), dict(state.trust))
        for character in story["characters"]:
            await engine.talk(game_id, character["id"], "测试询问")
        for clue_id in sorted(engine.games[game_id].acquired_clues):
            for character in story["characters"]:
                if clue_id not in engine.games[game_id].shown[character["id"]]:
                    await engine.show(game_id, character["id"], clue_id)
        state = engine.games[game_id]
        after = (set(state.acquired_clues), set(state.exposed_lies), set(state.triggered_events), dict(state.trust))
        if before == after:
            break
    all_clues = {c["id"] for c in story["clues"]}
    all_lies = {lie["id"] for char in story["characters"] for lie in char["lies"]}
    all_events = {event["id"] for event in story["events"]}
    engine_reaches_all = (
        state.acquired_clues == all_clues
        and state.exposed_lies == all_lies
        and state.triggered_events == all_events
    )
    assert checked["ok"] is engine_reaches_all
    assert engine_reaches_all is (graph in {"ordinary", "event_chain"})


@pytest.mark.parametrize("order", ["ordinary", "partial_overlap", "shadowed_truth", "early_fallback"])
def test_ending_coverage_matches_exhaustive_runtime_matching(order):
    story = mock_story()
    outcomes = story["ending"]["endings"]
    if order == "partial_overlap":
        outcomes.insert(1, {"id": "partial", "title": "部分", "when": {"correct": ["q1"]}, "text": "部分结果"})
    elif order == "shadowed_truth":
        outcomes.insert(0, {"id": "early", "title": "提前", "when": {"correct": ["q1"]}, "text": "提前结果"})
    elif order == "early_fallback":
        outcomes.insert(0, {"id": "early", "title": "提前", "text": "提前结果"})
    questions = story["ending"]["questions"]
    reachable = set()
    for chosen in product(*(q["options"] for q in questions)):
        answers = dict(zip((q["id"] for q in questions), chosen))
        results = {q["id"]: answers[q["id"]] == q["answer"] for q in questions}
        reached = next(e for e in outcomes if GameEngine._ending_matches(e, answers, results))
        reachable.add(reached["id"])
    checked = checker.check_structure(story)
    assert checked["ok"] is (reachable == {e["id"] for e in outcomes})
    if order in {"shadowed_truth", "early_fallback"}:
        assert "truth" not in reachable
        assert any("truth" in p and "覆盖" in p for p in checked["problems"])


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [0, 1, 2, 3])
async def test_secret_trust_threshold_matches_actual_contexts(tmp_path, deterministic_agents, threshold):
    story = mock_story()
    story["characters"][2]["secrets"] = [{"fact": "f3", "until": {"trust": threshold}}]
    assert checker.check_structure(story)["ok"]
    engine, game_id = open_technical_story(tmp_path, story)
    for count in range(4):
        context = engine._context(engine.games[game_id], "wang", "测试")
        assert ("f3" in {f["id"] for f in context["facts"]}) is (count >= threshold)
        if count != 3:
            await engine.talk(game_id, "wang", "测试询问")


@pytest.mark.asyncio
async def test_admitted_lie_intentionally_overrides_other_trust_lock(tmp_path, deterministic_agents):
    story = mock_story()
    story["characters"][0]["secrets"] = [{"fact": "f1", "until": {"trust": 3}}]
    engine, game_id = open_technical_story(tmp_path, story)
    await engine.talk(game_id, "wang", "测试取证")
    await engine.show(game_id, "lin", "c1")
    state = engine.games[game_id]
    assert state.trust["lin"] < 3 and "l1" in state.exposed_lies
    assert "f1" in {f["id"] for f in engine._context(state, "lin", "测试")["facts"]}


def test_whitespace_normalization_is_required_before_loading_external_yaml(tmp_path):
    story = mock_story()
    story["ending"]["questions"][0]["answer"] = " 林青 "
    assert checker.check_structure(story)["ok"]
    with pytest.raises(GameError) as invalid:
        open_technical_story(tmp_path, story, normalize=False)
    assert invalid.value.status_code == 500
    engine, game_id = open_technical_story(tmp_path, story)
    assert engine.games[game_id].story["ending"]["questions"][0]["answer"] == "林青"
