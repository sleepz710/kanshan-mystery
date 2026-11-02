"""纯技术样本验证 v2 状态协议，不依赖待编写的正式剧本。"""

import asyncio
from copy import deepcopy
import json

import pytest
import yaml

from backend import agents, kanshan
from backend.engine import GameEngine, GameError
from backend.llm import LLMError


def technical_story(story_id="protocol"):
    return {
        "id": story_id, "title": "协议测试样本", "intro": "公开说明", "source": "official",
        "facts": [{"id": fid, "text": text} for fid, text in [
            ("fa", "第一阶段事实"), ("fb", "第二阶段事实"), ("fc", "对质承认事实"), ("fs", "受信任条件保护的事实")
        ]],
        "characters": [
            {"id": "a", "name": "角色A", "avatar": "a.png", "profile": "公开A", "persona": "简短作答",
             "knows": ["fa", "fb", "fs"], "trust_start": 0,
             "secrets": [{"fact": "fa", "until": {"trust": 3}}, {"fact": "fs", "until": {"trust": 3}}],
             "lies": [
                 {"id": "la", "claim": "阶段一说法", "until": {"shown": "x"}, "admit": "fa"},
                 {"id": "lb", "claim": "阶段二说法", "until": {"exposed": "la", "shown": "y"}, "admit": "fb"},
             ]},
            {"id": "b", "name": "角色B", "avatar": "b.png", "profile": "公开B", "persona": "简短作答",
             "knows": ["fc"], "trust_start": 0, "secrets": [],
             "lies": [{"id": "lz", "claim": "事件前说法", "until": {"event": "e"}, "admit": "fc"}]},
        ],
        "clues": [
            {"id": "x", "title": "证据X", "content": "公开X", "holder": "b"},
            {"id": "y", "title": "证据Y", "content": "公开Y", "holder": "b", "requires": {"has": "x"}},
            {"id": "gate", "title": "组合条件证据", "content": "公开组合", "holder": "a",
             "requires": {"trust": 1, "shown": "x", "has": "y", "exposed": "la", "event": "e"}},
            {"id": "reward", "title": "事件奖励", "content": "公开奖励", "holder": "b", "requires": {"trust": 3}},
        ],
        "events": [{"id": "e", "when": {"shown": "x", "to": "a"}, "confront": ["a", "b"], "unlock": ["reward"]}],
        "kanshan": {"greeting": "公开开场白", "hints": [
            {"done": {"has": "x"}, "vague": "V1", "direct": "D1"},
            {"done": {"exposed": "la"}, "vague": "V2", "direct": "D2"},
            {"done": {"exposed": "lb"}, "vague": "V3", "direct": "D3"},
        ]},
        "ending": {
            "questions": [
                {"id": "q1", "text": "技术问题1", "options": ["a", "b"], "answer": "a"},
                {"id": "q2", "text": "技术问题2", "options": ["a", "b"], "answer": "a"},
            ],
            "endings": [
                {"id": "truth", "title": "完成", "when": {"correct": ["q2"]}, "text": "完成结果"},
                {"id": "wrong", "title": "待复查", "when": {"chose": {"q1": "b"}}, "text": "待复查结果", "retry": True},
                {"id": "half", "title": "未完成", "text": "未完成结果", "retry": True},
            ],
            "truth": "仅揭晓接口可返回的完整真相", "lessons": ["复盘材料"],
        },
    }


def write_story(directory, story):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (story["id"] + ".yaml")).write_text(yaml.safe_dump(story, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def controlled_agents(monkeypatch):
    calls = {"reply": [], "confront": [], "check": []}

    async def reply(context, *, retry_leaked=None):
        calls["reply"].append((deepcopy(context), deepcopy(retry_leaked)))
        return {"reply": "已说明当前可公开内容", "reveal": [c["id"] for c in context["available_clues"][:1]], "trust_delta": 1}

    async def check(context, candidate):
        calls["check"].append(deepcopy(context))
        return {"ok": True, "leaked": [], "contradiction": ""}

    async def confront(contexts, event):
        calls["confront"].append(deepcopy(contexts))
        return [{"speaker": ctx["character"]["id"], "text": "对质中的公开回答"} for ctx in contexts]

    async def answer(story, question):
        return "是"

    monkeypatch.setattr(agents, "reply", reply)
    monkeypatch.setattr(agents, "check_reply", check)
    monkeypatch.setattr(agents, "confront", confront)
    monkeypatch.setattr(kanshan, "answer", answer)
    return calls


@pytest.fixture
def setup_game(tmp_path, controlled_agents):
    official, generated = tmp_path / "official", tmp_path / "generated"
    write_story(official, technical_story())
    engine = GameEngine(official, generated)
    game_id = engine.new_game("protocol")["game_id"]
    return engine, game_id, controlled_agents


async def take_evidence(engine, game_id):
    await engine.talk(game_id, "b", "第一份材料")
    await engine.talk(game_id, "b", "第二份材料")


@pytest.mark.asyncio
async def test_staged_lies_and_event_admit_are_visible_in_correct_order(setup_game):
    engine, game_id, calls = setup_game
    await engine.talk(game_id, "a", "初次询问")
    first = calls["reply"][-1][0]
    assert [lie["id"] for lie in first["active_lies"]] == ["la"]
    assert [lie["id"] for lie in first["future_lies"]] == ["lb"]
    assert not {"fa", "fb", "fs"} & {fact["id"] for fact in first["facts"]}
    await take_evidence(engine, game_id)
    result = await engine.show(game_id, "a", "x")
    assert [(e["type"], e.get("lie")) for e in result["events"]] == [
        ("exposed", "la"), ("confront", None), ("exposed", "lz")
    ]
    exposed_context = calls["reply"][-1][0]
    assert [lie["id"] for lie in exposed_context["active_lies"]] == ["lb"]
    assert exposed_context["exposed_lies"][0]["admit"] == {"id": "fa", "text": "第一阶段事实"}
    assert "fa" in {f["id"] for f in exposed_context["facts"]}  # 拆穿优先于原 trust:3 秘密条件。
    projected_b = calls["confront"][-1][1]
    assert {f["id"] for f in projected_b["facts"]} == {"fc"}
    assert projected_b["active_lies"] == []
    assert projected_b["exposed_lies"][0]["id"] == "lz"
    assert "reward" in {c["id"] for c in result["new_clues"]}
    assert engine.games[game_id].trust["a"] == 3  # 初次+本轮+拆穿，封顶3。
    assert engine.games[game_id].trust["b"] == 3
    result = await engine.show(game_id, "a", "y")
    assert [(e["type"], e.get("lie")) for e in result["events"]] == [("exposed", "lb")]
    assert {f["id"] for f in calls["reply"][-1][0]["facts"]} >= {"fa", "fb"}
    assert "gate" in {c["id"] for c in result["new_clues"]}
    repeated = await engine.show(game_id, "a", "x")
    assert repeated["events"] == []
    assert "reward" not in {c["id"] for c in repeated["new_clues"]}


@pytest.mark.parametrize("missing", ["trust", "shown", "has", "exposed", "event"])
@pytest.mark.asyncio
async def test_every_and_requirement_matters(setup_game, missing):
    engine, game_id, _ = setup_game
    state = deepcopy(engine.games[game_id])
    state.trust["a"] = 1
    state.shown["a"].add("x")
    state.acquired_clues.update({"x", "y"})
    state.exposed_lies.add("la")
    state.triggered_events.add("e")
    condition = state.story["clues"][2]["requires"]
    assert engine._condition(state, "a", condition)
    if missing == "trust": state.trust["a"] = 0
    elif missing == "shown": state.shown["a"].clear()
    elif missing == "has": state.acquired_clues.remove("y")
    elif missing == "exposed": state.exposed_lies.clear()
    else: state.triggered_events.clear()
    assert not engine._condition(state, "a", condition)


@pytest.mark.asyncio
async def test_event_reward_ignores_holder_requires_and_is_given_once(setup_game):
    engine, game_id, calls = setup_game
    await engine.talk(game_id, "b", "材料")  # b信任仅1，奖励要求3尚未满足。
    assert engine.games[game_id].trust["b"] == 1
    result = await engine.show(game_id, "a", "x")
    assert [clue["id"] for clue in result["new_clues"]] == ["reward"]
    assert all("reward" not in {c["id"] for c in ctx["available_clues"]} for ctx in calls["confront"][-1])
    result = await engine.show(game_id, "a", "x")
    assert not result["new_clues"] and not result["events"]


@pytest.mark.asyncio
async def test_talk_floor_only_after_four_talks_and_upper_cap(setup_game, monkeypatch):
    engine, game_id, _ = setup_game
    await engine.talk(game_id, "b", "取X")
    delta = -100

    async def reply(context, *, retry_leaked=None):
        return {"reply": "继续", "reveal": [], "trust_delta": delta}

    monkeypatch.setattr(agents, "reply", reply)
    for _ in range(3):
        await engine.talk(game_id, "b", "继续")
    assert engine.games[game_id].trust["b"] == 1  # 包括取X，累计第四次talk。
    await engine.show(game_id, "b", "x")
    assert engine.games[game_id].talk_counts["b"] == 4
    assert engine.games[game_id].trust["b"] == 1
    assert engine.games[game_id].turns == 5
    delta = 100
    for _ in range(6):
        await engine.talk(game_id, "b", "继续")
    assert engine.games[game_id].trust["b"] == 3


@pytest.mark.asyncio
async def test_hint_stages_skip_done_then_escalate(setup_game, monkeypatch):
    engine, game_id, _ = setup_game

    async def quiet(context, *, retry_leaked=None):
        return {"reply": "继续", "reveal": [], "trust_delta": 0}

    original_reply = agents.reply
    monkeypatch.setattr(agents, "reply", quiet)
    hints = [(await engine.talk(game_id, "a", "继续"))["hint"] for _ in range(6)]
    assert hints == [None, None, "V1", None, None, "D1"]
    monkeypatch.setattr(agents, "reply", original_reply)
    await engine.talk(game_id, "b", "获取X")
    monkeypatch.setattr(agents, "reply", quiet)
    hints = [(await engine.talk(game_id, "a", "继续"))["hint"] for _ in range(6)]
    assert hints == [None, None, "V2", None, None, "D2"]
    await engine.show(game_id, "a", "x")  # 有事件新奖励，停滞计数归零。
    hints = [(await engine.talk(game_id, "a", "继续"))["hint"] for _ in range(3)]
    assert hints == [None, None, "V3"]


@pytest.mark.asyncio
async def test_retries_keep_progress_and_truth_requires_explicit_reveal(setup_game):
    engine, game_id, _ = setup_game
    with pytest.raises(GameError) as error:
        await engine.reveal(game_id)
    assert error.value.status_code == 409
    await engine.talk(game_id, "b", "取X")
    await engine.ask(game_id, "是吗？")
    wrong = await engine.accuse(game_id, {"q1": "b", "q2": "b"})
    assert wrong["ending"]["id"] == "wrong" and wrong["ending"]["retry"]
    assert "truth" not in wrong and "lessons" not in wrong
    assert not engine.games[game_id].finished
    await engine.talk(game_id, "b", "取Y")
    assert engine.games[game_id].acquired_clues == {"x", "y"}
    assert engine.games[game_id].asks_used == 1 and engine.games[game_id].turns == 2
    # 两个结局同时满足时按顺序选truth，而不是后面的wrong。
    final = await engine.accuse(game_id, {"q1": "b", "q2": "a"})
    assert final["ending"]["id"] == "truth"
    assert final["rating"] == "C"  # 题数是2，答对1题。
    assert engine.games[game_id].last_ending == final["ending"]
    final["ending"]["text"] = "外部修改"
    assert engine.games[game_id].last_ending["text"] != "外部修改"
    revealed = await engine.reveal(game_id)
    assert revealed == {"truth": "仅揭晓接口可返回的完整真相", "lessons": ["复盘材料"]}
    for operation in [lambda: engine.talk(game_id, "a", "继续"), lambda: engine.ask(game_id, "继续？"), lambda: engine.reveal(game_id)]:
        with pytest.raises(GameError) as error:
            await operation()
        assert error.value.status_code == 409


@pytest.mark.parametrize("score,total,turns,asks,rating", [
    (5, 5, 20, 2, "S"), (5, 5, 21, 2, "A"), (5, 5, 20, 3, "A"),
    (4, 5, 20, 2, "A"), (3, 5, 20, 2, "B"), (2, 5, 20, 2, "C"),
])
def test_rating_boundaries(score, total, turns, asks, rating):
    assert GameEngine._rating(score, total, turns, asks) == rating


@pytest.mark.asyncio
async def test_ask_quota_is_serialized_and_separate_from_turns(setup_game, monkeypatch):
    engine, game_id, _ = setup_game

    async def slow(story, question):
        await asyncio.sleep(0.005)
        return "不是"

    monkeypatch.setattr(kanshan, "answer", slow)
    results = await asyncio.gather(*(engine.ask(game_id, "是吗？") for _ in range(6)), return_exceptions=True)
    assert [result["asks_left"] for result in results if isinstance(result, dict)] == [4, 3, 2, 1, 0]
    assert [result.status_code for result in results if isinstance(result, GameError)] == [409]
    assert engine.games[game_id].asks_used == 5
    assert engine.games[game_id].turns == 0


@pytest.mark.parametrize("bad", [None, {}, "不知道", {"answer": "是"}])
@pytest.mark.asyncio
async def test_bad_ask_response_does_not_charge(setup_game, monkeypatch, bad):
    engine, game_id, _ = setup_game

    async def answer(story, question):
        story["facts"].clear()
        return bad

    monkeypatch.setattr(kanshan, "answer", answer)
    before = deepcopy(engine.games[game_id])
    with pytest.raises(GameError) as error:
        await engine.ask(game_id, "是吗？")
    assert error.value.status_code == 502
    assert engine.games[game_id] == before


@pytest.mark.asyncio
async def test_failed_ask_preserves_specific_model_error(setup_game, monkeypatch):
    engine, game_id, _ = setup_game

    async def answer(story, question):
        raise LLMError("暂未配置", status_code=503)

    monkeypatch.setattr(kanshan, "answer", answer)
    with pytest.raises(LLMError) as error:
        await engine.ask(game_id, "是吗？")
    assert error.value.status_code == 503
    assert engine.games[game_id].asks_used == 0


@pytest.mark.asyncio
async def test_contradiction_feedback_is_sent_to_single_rewrite(setup_game, monkeypatch):
    engine, game_id, calls = setup_game
    responses = iter([{"ok": False, "leaked": [], "contradiction": "已拆穿后不能否认"}, {"ok": True, "leaked": [], "contradiction": ""}])

    async def check(context, candidate):
        return next(responses)

    monkeypatch.setattr(agents, "check_reply", check)
    await engine.talk(game_id, "a", "询问")
    assert [retry for _, retry in calls["reply"]] == [None, []]
    assert "check_feedback" not in calls["reply"][0][0]
    assert calls["reply"][1][0]["check_feedback"] == "已拆穿后不能否认"
    assert len(engine.games[game_id].histories["a"]) == 2


@pytest.mark.asyncio
async def test_failure_rolls_back_exposure_and_queued_event(setup_game, monkeypatch):
    engine, game_id, _ = setup_game
    await engine.talk(game_id, "b", "取X")
    before = deepcopy(engine.games[game_id])

    async def reject(context, candidate):
        return {"ok": False, "leaked": [], "contradiction": "不一致"}

    monkeypatch.setattr(agents, "check_reply", reject)
    with pytest.raises(GameError):
        await engine.show(game_id, "a", "x")
    assert engine.games[game_id] == before
    assert not engine.games[game_id].exposed_lies
    assert not engine.games[game_id].triggered_events


def test_generated_listing_is_public_and_can_start(tmp_path, controlled_agents):
    official, generated = tmp_path / "official", tmp_path / "generated"
    write_story(official, technical_story())
    created = technical_story("created")
    created["source"] = "generated"
    write_story(generated, created)
    write_story(generated, technical_story())  # 同编号优先使用招牌目录。
    (generated / "bad.yaml").write_text("invalid", encoding="utf-8")
    engine = GameEngine(official, generated)
    listing = engine.list_stories()
    assert [story["id"] for story in listing] == ["protocol", "created"]
    assert all(set(story) == {"id", "title", "intro", "source", "characters"} for story in listing)
    assert listing[1]["source"] == "generated" and listing[1]["characters"] == 2
    public = engine.new_game("created")
    assert public["kanshan"] == {"greeting": "公开开场白", "asks_left": 5}
    serialized = json.dumps(public, ensure_ascii=False)
    for secret in ["仅揭晓接口", "阶段一说法", "受信任条件保护的事实", "答案"]:
        assert secret not in serialized
    for bad in ["../created", "..\\created", "created.yaml", "/created"]:
        with pytest.raises(GameError) as error:
            engine.new_game(bad)
        assert error.value.status_code == 400


@pytest.mark.parametrize("problem", ["duplicate_lie", "unknown_admit", "foreign_admit", "knows_string", "bad_condition", "unknown_exposed", "unknown_event", "trust4", "no_fallback", "bad_correct", "bad_chose", "scoped_hint"])
def test_v2_schema_rejects_bad_cross_references(tmp_path, controlled_agents, problem):
    story = technical_story()
    if problem == "duplicate_lie": story["characters"][1]["lies"][0]["id"] = "la"
    elif problem == "unknown_admit": story["characters"][0]["lies"][0]["admit"] = "missing"
    elif problem == "foreign_admit": story["characters"][0]["lies"][0]["admit"] = "fc"
    elif problem == "knows_string": story["characters"][0]["knows"] = "fa"
    elif problem == "bad_condition": story["clues"][0]["requires"] = {"has": "x", "unknown": "y"}
    elif problem == "unknown_exposed": story["clues"][0]["requires"] = {"exposed": "missing"}
    elif problem == "unknown_event": story["clues"][0]["requires"] = {"event": "missing"}
    elif problem == "trust4": story["clues"][0]["requires"] = {"trust": 4}
    elif problem == "no_fallback": story["ending"]["endings"].pop()
    elif problem == "bad_correct": story["ending"]["endings"][0]["when"] = {"correct": ["missing"]}
    elif problem == "bad_chose": story["ending"]["endings"][1]["when"] = {"chose": {"q1": "invalid"}}
    else: story["kanshan"]["hints"][0]["done"] = {"shown": "x"}
    write_story(tmp_path, story)
    with pytest.raises(GameError) as error:
        GameEngine(tmp_path, tmp_path / "generated").new_game("protocol")
    assert error.value.status_code == 500


@pytest.mark.asyncio
async def test_v2_states_do_not_cross_games(setup_game):
    engine, first, _ = setup_game
    second = engine.new_game("protocol")["game_id"]
    await engine.talk(first, "b", "取X")
    await engine.show(first, "a", "x")
    await engine.ask(first, "是吗？")
    other = engine.games[second]
    assert not other.exposed_lies and not other.triggered_events and not other.acquired_clues
    assert other.turns == other.asks_used == 0
    assert other.talk_counts == {"a": 0, "b": 0}
