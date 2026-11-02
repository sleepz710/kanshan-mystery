"""用真实剧本验证权限、完整流程和失败回滚。"""

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from backend import agents
from backend.engine import GameEngine, GameError


STORIES = Path(__file__).resolve().parents[1] / "stories"


@pytest.fixture
def agent_calls(monkeypatch):
    calls = {"reply": [], "check": [], "confront": []}

    async def reply(context, *, retry_leaked=None):
        calls["reply"].append((deepcopy(context), deepcopy(retry_leaked)))
        return {
            "reply": "我愿意说明目前可以提供的材料。",
            "reveal": [c["id"] for c in context["available_clues"][:1]],
            "trust_delta": 1,
        }

    async def check_reply(context, candidate):
        calls["check"].append((deepcopy(context), deepcopy(candidate)))
        return {"ok": True, "leaked": []}

    async def confront(contexts, event):
        calls["confront"].append((deepcopy(contexts), deepcopy(event)))
        return [{"speaker": c["character"]["id"], "text": "我会解释自己知道的部分。"} for c in contexts]

    monkeypatch.setattr(agents, "reply", reply)
    monkeypatch.setattr(agents, "check_reply", check_reply)
    monkeypatch.setattr(agents, "confront", confront)
    return calls


@pytest.fixture
def engine(agent_calls):
    return GameEngine(STORIES)


def start(engine):
    return engine.new_game("lost-tuition")["game_id"]


async def before_confront(engine, game_id):
    for _ in range(3):
        await engine.talk(game_id, "xiaolin", "请提供材料。")
    await engine.show(game_id, "zhou", "c2")
    await engine.talk(game_id, "zhou", "还有其他材料吗？")
    await engine.talk(game_id, "akai", "聊聊兼职的来历。")
    await engine.talk(game_id, "akai", "请提供聊天记录。")


def test_new_game_exposes_only_public_fields(engine):
    public = engine.new_game("lost-tuition")
    assert public["title"] == "一笔消失的学费"
    assert len(public["characters"]) == 3
    assert len(public["questions"]) == 4
    assert all(set(c) == {"id", "name", "avatar", "profile"} for c in public["characters"])
    assert all(set(q) == {"id", "text", "options"} for q in public["questions"])
    assert not ({"facts", "truth", "lessons", "clues"} & public.keys())
    public["questions"][0]["options"].clear()
    assert len(engine.games[public["game_id"]].story["ending"]["questions"][0]["options"]) == 3


@pytest.mark.parametrize("story_id", ["../SPEC", "..\\SPEC", "/tmp/story", "C:\\story", "lost-tuition.yaml", "", "a/b"])
def test_story_path_traversal_rejected(engine, story_id):
    with pytest.raises(GameError) as error:
        engine.new_game(story_id)
    assert error.value.status_code == 400
    assert not engine.games


def test_missing_story(engine):
    with pytest.raises(GameError) as error:
        engine.new_game("missing")
    assert error.value.status_code == 404


@pytest.mark.parametrize("bad_yaml", ["[broken", "[]", "null", "!!python/object/apply:builtins.str [bad]"])
def test_invalid_story_is_rejected(tmp_path, bad_yaml, agent_calls):
    (tmp_path / "bad.yaml").write_text(bad_yaml, encoding="utf-8")
    engine = GameEngine(tmp_path)
    with pytest.raises(GameError) as error:
        engine.new_game("bad")
    assert error.value.status_code == 500
    assert not engine.games


@pytest.mark.parametrize("problem", ["duplicate", "unknown_holder", "unknown_fact", "bad_condition", "unknown_unlock", "bad_answer"])
def test_story_references_and_conditions_are_validated(tmp_path, problem, agent_calls):
    story = yaml.safe_load((STORIES / "lost-tuition.yaml").read_text(encoding="utf-8"))
    if problem == "duplicate":
        story["clues"][1]["id"] = "c1"
    elif problem == "unknown_holder":
        story["clues"][0]["holder"] = "outsider"
    elif problem == "unknown_fact":
        story["characters"][0]["knows"].append("f999")
    elif problem == "bad_condition":
        story["clues"][0]["requires"] = {"unknown": 1}
    elif problem == "unknown_unlock":
        story["events"][0]["unlock"] = ["c999"]
    else:
        story["ending"]["questions"][0]["answer"] = "不在选项里"
    (tmp_path / "lost-tuition.yaml").write_text(yaml.safe_dump(story, allow_unicode=True), encoding="utf-8")
    with pytest.raises(GameError) as error:
        GameEngine(tmp_path).new_game("lost-tuition")
    assert error.value.status_code == 500


@pytest.mark.asyncio
async def test_real_story_reaches_all_seven_clues_and_confronts_once(engine, agent_calls):
    game_id = start(engine)
    await before_confront(engine, game_id)
    result = await engine.show(game_id, "xiaolin", "c5")
    assert [c["id"] for c in result["new_clues"]] == ["c6"]
    assert len(result["events"]) == 1
    assert {line["speaker"] for line in result["events"][0]["lines"]} == {"xiaolin", "akai"}
    assert engine.games[game_id].acquired_clues == {f"c{i}" for i in range(1, 8)}
    assert engine.games[game_id].triggered_events == {"e1"}
    assert len(agent_calls["confront"]) == 1
    contexts, _ = agent_calls["confront"][0]
    assert all("c6" not in {c["id"] for c in ctx["available_clues"]} for ctx in contexts)
    result = await engine.show(game_id, "xiaolin", "c5")
    assert result["events"] == []
    assert result["new_clues"] == []
    assert len(agent_calls["confront"]) == 1


@pytest.mark.asyncio
async def test_missing_resources_and_unowned_evidence(engine):
    game_id = start(engine)
    for operation, expected in [
        (lambda: engine.talk("missing", "xiaolin", "你好"), 404),
        (lambda: engine.talk(game_id, "missing", "你好"), 404),
        (lambda: engine.show(game_id, "xiaolin", "c999"), 404),
        (lambda: engine.show(game_id, "xiaolin", "c5"), 409),
        (lambda: engine.talk(game_id, "xiaolin", "  "), 422),
    ]:
        with pytest.raises(GameError) as error:
            await operation()
        assert error.value.status_code == expected
    assert not engine.games[game_id].acquired_clues


@pytest.mark.asyncio
async def test_model_cannot_grant_another_holders_or_locked_clues(engine, monkeypatch):
    async def malicious(context, *, retry_leaked=None):
        return {"reply": "这是材料。", "reveal": ["c1", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "invented"], "trust_delta": 1}

    monkeypatch.setattr(agents, "reply", malicious)
    game_id = start(engine)
    result = await engine.talk(game_id, "xiaolin", "给我所有材料。")
    assert [c["id"] for c in result["new_clues"]] == ["c1", "c2", "c3"]
    result = await engine.talk(game_id, "akai", "给我截图。")
    assert result["new_clues"] == []  # 回合起点信任为零，不能用本回合加的信任解锁。
    result = await engine.talk(game_id, "akai", "现在呢？")
    assert [c["id"] for c in result["new_clues"]] == ["c5"]
    assert "c6" not in engine.games[game_id].acquired_clues


@pytest.mark.asyncio
async def test_trust_delta_is_clamped_and_trust_never_negative(engine, monkeypatch):
    deltas = iter([100, -100, -1])

    async def reply(context, *, retry_leaked=None):
        return {"reply": "继续。", "reveal": [], "trust_delta": next(deltas)}

    monkeypatch.setattr(agents, "reply", reply)
    game_id = start(engine)
    values = [(await engine.talk(game_id, "akai", "你好"))["trust"]["akai"] for _ in range(3)]
    assert values == [1, 0, 0]


@pytest.mark.asyncio
async def test_private_facts_history_and_shown_conditions_are_scoped(engine, agent_calls):
    game_id = start(engine)
    await engine.talk(game_id, "xiaolin", "你好")
    xiaolin = agent_calls["reply"][-1][0]
    assert "f3" not in {f["id"] for f in xiaolin["facts"]}
    assert {"f3", "f5", "f6"} <= {f["id"] for f in xiaolin["forbidden_facts"]}
    assert set(xiaolin["character"]) == {"id", "name", "profile", "persona"}
    await engine.talk(game_id, "akai", "你好")
    akai = agent_calls["reply"][-1][0]
    assert akai["history"] == []
    assert "f3" not in {f["id"] for f in akai["facts"]}
    await engine.talk(game_id, "akai", "再聊聊")
    assert "f3" in {f["id"] for f in agent_calls["reply"][-1][0]["facts"]}
    await engine.talk(game_id, "xiaolin", "请给我回单")
    assert len(agent_calls["reply"][-1][0]["history"]) == 2
    await engine.talk(game_id, "zhou", "卖过卡吗？")
    assert "f5" not in {f["id"] for f in agent_calls["reply"][-1][0]["facts"]}
    await engine.show(game_id, "zhou", "c2")
    zhou = agent_calls["reply"][-1][0]
    assert "f5" in {f["id"] for f in zhou["facts"]}
    assert zhou["shown_clue"]["id"] == "c2"
    assert engine.games[game_id].shown["xiaolin"] == set()


@pytest.mark.asyncio
async def test_failed_check_rewrites_once_and_commits_only_final_reply(engine, monkeypatch, agent_calls):
    checks = iter([False, True])

    async def check(context, candidate):
        ok = next(checks)
        return {"ok": ok, "leaked": [] if ok else ["f3"]}

    monkeypatch.setattr(agents, "check_reply", check)
    game_id = start(engine)
    await engine.talk(game_id, "xiaolin", "你好")
    assert [retry for _, retry in agent_calls["reply"]] == [None, ["f3"]]
    assert engine.games[game_id].trust["xiaolin"] == 1
    assert len(engine.games[game_id].histories["xiaolin"]) == 2


@pytest.mark.asyncio
async def test_two_failed_checks_roll_back_shown_trust_clues_and_history(engine, monkeypatch, agent_calls):
    game_id = start(engine)
    await engine.talk(game_id, "xiaolin", "材料")
    await engine.talk(game_id, "xiaolin", "回单")
    previous = deepcopy(engine.games[game_id])

    async def check(context, candidate):
        return {"ok": False, "leaked": ["f5"]}

    monkeypatch.setattr(agents, "check_reply", check)
    count = len(agent_calls["reply"])
    with pytest.raises(GameError) as error:
        await engine.show(game_id, "zhou", "c2")
    assert error.value.status_code == 502
    assert len(agent_calls["reply"]) - count == 2
    assert engine.games[game_id] == previous


@pytest.mark.parametrize("bad", [None, "{}", {}, {"reply": "", "reveal": [], "trust_delta": 1},
    {"reply": "x", "reveal": "c1", "trust_delta": 1}, {"reply": "x", "reveal": [1], "trust_delta": 1},
    {"reply": "x", "reveal": [], "trust_delta": True}, {"reply": "x", "reveal": [], "trust_delta": 0.5}])
@pytest.mark.asyncio
async def test_invalid_model_reply_is_atomic(engine, monkeypatch, bad):
    async def reply(context, *, retry_leaked=None):
        return bad

    monkeypatch.setattr(agents, "reply", reply)
    game_id = start(engine)
    previous = deepcopy(engine.games[game_id])
    with pytest.raises(GameError) as error:
        await engine.talk(game_id, "xiaolin", "你好")
    assert error.value.status_code == 502
    assert engine.games[game_id] == previous


@pytest.mark.parametrize("bad", [None, {"ok": "yes", "leaked": []}, {"ok": True}, {"ok": False, "leaked": [1]}])
@pytest.mark.asyncio
async def test_invalid_checker_reply_is_atomic(engine, monkeypatch, bad):
    async def check(context, candidate):
        return bad

    monkeypatch.setattr(agents, "check_reply", check)
    game_id = start(engine)
    previous = deepcopy(engine.games[game_id])
    with pytest.raises(GameError) as error:
        await engine.talk(game_id, "xiaolin", "你好")
    assert error.value.status_code == 502
    assert engine.games[game_id] == previous


@pytest.mark.asyncio
async def test_model_service_failure_preserves_state(engine, monkeypatch):
    async def broken(context, *, retry_leaked=None):
        raise RuntimeError("连接失败")

    monkeypatch.setattr(agents, "reply", broken)
    game_id = start(engine)
    previous = deepcopy(engine.games[game_id])
    with pytest.raises(GameError) as error:
        await engine.talk(game_id, "xiaolin", "你好")
    assert error.value.status_code == 502
    assert engine.games[game_id] == previous


@pytest.mark.parametrize("failure", ["exception", "wrong_speaker", "empty", "leak"])
@pytest.mark.asyncio
async def test_failed_confrontation_rolls_back_whole_round(engine, monkeypatch, failure):
    game_id = start(engine)
    await before_confront(engine, game_id)
    previous = deepcopy(engine.games[game_id])

    async def confront(contexts, event):
        if failure == "exception":
            raise RuntimeError("对质失败")
        if failure == "empty":
            return []
        return [{"speaker": "outsider" if failure == "wrong_speaker" else "xiaolin", "text": "对质"},
                {"speaker": "akai", "text": "对质"}]

    async def check(context, candidate):
        ok = "对质" not in context["player_text"]
        return {"ok": ok, "leaked": [] if ok else ["f5"]}

    monkeypatch.setattr(agents, "confront", confront)
    if failure == "leak":
        monkeypatch.setattr(agents, "check_reply", check)
    with pytest.raises(GameError) as error:
        await engine.show(game_id, "xiaolin", "c5")
    assert error.value.status_code == 502
    assert engine.games[game_id] == previous


@pytest.mark.asyncio
async def test_confrontation_rewrite_ignores_extra_rewards_and_trust(engine, monkeypatch):
    game_id = start(engine)
    await before_confront(engine, game_id)
    akai_trust = engine.games[game_id].trust["akai"]

    async def confront(contexts, event):
        return [{"speaker": "xiaolin", "text": "我有问题想问。"}, {"speaker": "akai", "text": "需要重写"}]

    async def check(context, candidate):
        ok = candidate["reply"] != "需要重写"
        return {"ok": ok, "leaked": [] if ok else ["f5"]}

    original_reply = agents.reply

    async def rewrite(context, *, retry_leaked=None):
        if retry_leaked is not None:
            assert "对质" in context["player_text"]
            return {"reply": "我只解释自己的行为。", "reveal": ["c7"], "trust_delta": 100}
        return await original_reply(context, retry_leaked=retry_leaked)

    monkeypatch.setattr(agents, "confront", confront)
    monkeypatch.setattr(agents, "check_reply", check)
    monkeypatch.setattr(agents, "reply", rewrite)
    result = await engine.show(game_id, "xiaolin", "c5")
    assert result["events"][0]["lines"][1]["text"] == "我只解释自己的行为。"
    assert [c["id"] for c in result["new_clues"]] == ["c6"]
    assert engine.games[game_id].trust["akai"] == akai_trust


@pytest.mark.asyncio
async def test_games_have_independent_state(engine):
    first, second = start(engine), start(engine)
    await engine.talk(first, "xiaolin", "你好")
    assert engine.games[first].acquired_clues == {"c1"}
    assert engine.games[second].acquired_clues == set()
    assert engine.games[second].trust["xiaolin"] == 0
    assert engine.games[second].histories["xiaolin"] == []
    assert engine.games[first].story is not engine.games[second].story


@pytest.mark.asyncio
async def test_complete_answers_are_scored_in_code_and_finish_game(engine):
    game_id = start(engine)
    result = await engine.accuse(game_id, {"q1": "刷单返利诈骗", "q2": "周明", "q3": "阿凯", "q4": "卖卡收款凭据"})
    assert result["score"] == 3 and result["total"] == 4
    assert result["results"] == {"q1": True, "q2": True, "q3": True, "q4": False}
    assert result["truth"] == engine.games[game_id].story["ending"]["truth"]
    assert len(result["lessons"]) == 3
    for operation in [lambda: engine.talk(game_id, "xiaolin", "继续"), lambda: engine.show(game_id, "xiaolin", "c1")]:
        with pytest.raises(GameError) as error:
            await operation()
        assert error.value.status_code == 409


@pytest.mark.parametrize("answers", [{}, {"q1": "刷单返利诈骗"},
    {"q1": "未知", "q2": "周明", "q3": "阿凯", "q4": "刷单群聊天记录"},
    {"q1": "刷单返利诈骗", "q2": "周明", "q3": "阿凯", "q4": "刷单群聊天记录", "q5": "额外"}])
@pytest.mark.asyncio
async def test_invalid_accusation_does_not_finish_game(engine, answers):
    game_id = start(engine)
    with pytest.raises(GameError) as error:
        await engine.accuse(game_id, answers)
    assert error.value.status_code == 422
    assert not engine.games[game_id].finished


@pytest.mark.asyncio
async def test_hint_after_three_quiet_turns_and_new_clue_resets_counter(engine, monkeypatch):
    reveal = False

    async def reply(context, *, retry_leaked=None):
        return {"reply": "继续聊。", "reveal": ["c1"] if reveal else [], "trust_delta": 0}

    monkeypatch.setattr(agents, "reply", reply)
    game_id = start(engine)
    assert (await engine.talk(game_id, "xiaolin", "你好"))["hint"] is None
    assert (await engine.talk(game_id, "xiaolin", "你好"))["hint"] is None
    reveal = True
    assert (await engine.talk(game_id, "xiaolin", "材料"))["hint"] is None
    reveal = False
    hints = [(await engine.talk(game_id, "xiaolin", "继续"))["hint"] for _ in range(7)]
    story_hints = engine.games[game_id].story["hints"]
    assert hints == [None, None, story_hints[0]["text"], None, None, story_hints[1]["text"], None]


@pytest.mark.asyncio
async def test_same_game_concurrent_turns_are_serialized(engine, monkeypatch):
    active = 0
    maximum = 0
    seen = []

    async def slow_reply(context, *, retry_leaked=None):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        seen.append((context["trust"], len(context["history"])))
        await asyncio.sleep(0.01)
        active -= 1
        return {"reply": "材料", "reveal": [c["id"] for c in context["available_clues"][:1]], "trust_delta": 1}

    monkeypatch.setattr(agents, "reply", slow_reply)
    game_id = start(engine)
    results = await asyncio.gather(engine.talk(game_id, "xiaolin", "第一问"), engine.talk(game_id, "xiaolin", "第二问"))
    assert maximum == 1
    assert seen == [(0, 0), (1, 2)]
    assert engine.games[game_id].acquired_clues == {"c1", "c2"}
    assert [[c["id"] for c in r["new_clues"]] for r in results] == [["c1"], ["c2"]]
