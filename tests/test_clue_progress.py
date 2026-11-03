"""已获准线索交付与生成案件行动提示的离线回归。"""

from copy import deepcopy

import pytest
import yaml

from backend import agents
from backend.engine import GameEngine
from backend.llm import LLMError
from backend.studio.mock import mock_story


def progress_story():
    story = mock_story()
    story.update(id="progress", title="线索协议样本")
    story["characters"] = [
        {"id": character_id, "name": name, "avatar": f"{character_id}.png",
         "profile": "公开身份", "persona": "简短作答", "knows": ["f1", "f2", "f3"],
         "secrets": [], "lies": [], "trust_start": 0}
        for character_id, name in [("s", "角色甲"), ("l", "角色乙"), ("g", "角色丙")]
    ]
    story["characters"][1]["lies"] = [{"id": "l1", "claim": "待核对说法一", "until": {"shown": "c1"}, "admit": "f1"}]
    story["characters"][2]["lies"] = [{"id": "l2", "claim": "待核对说法二", "until": {"shown": "c4"}, "admit": "f2"}]
    story["clues"] = [
        {"id": f"c{index}", "title": f"证据{index}", "content": f"已获准的材料{index}",
         "holder": holder, "requires": condition}
        for index, holder, condition in [
            (1, "s", {}), (2, "l", {"shown": "c1"}),
            (3, "g", {"exposed": "l2"}), (4, "g", {"trust": 1}),
            (5, "s", {"shown": "c1"}), (6, "g", {"shown": "c4"}),
            (7, "g", {"shown": "c3"}), (8, "s", {"event": "e1"}),
        ]
    ]
    story["events"] = [{"id": "e1", "when": {"shown": "c5", "to": "s"}, "confront": ["s", "l"], "unlock": ["c8"]}]
    story["kanshan"]["hints"] = [
        {"done": {}, "vague": "STATIC_UNAVAILABLE_HINT", "direct": "直接出示尚未取得的证据5"},
        {"done": {"exposed": "l1"}, "vague": "STATIC_FINISHED_HINT", "direct": "STATIC_FINISHED_HINT"},
    ]
    story["ending"]["truth"] = "PRIVATE_ENDING_TRUTH"
    return story


@pytest.fixture
def game_factory(tmp_path):
    def create(story=None, *, source="generated"):
        story = deepcopy(story) if story is not None else progress_story()
        directory = tmp_path / source
        directory.mkdir(exist_ok=True)
        (directory / f"{story['id']}.yaml").write_text(yaml.safe_dump(story, allow_unicode=True), encoding="utf-8")
        engine = GameEngine(tmp_path / "official", tmp_path / "generated")
        game_id = engine.new_game(story["id"])["game_id"]
        return engine, game_id

    return create


@pytest.fixture(autouse=True)
def offline_actors(monkeypatch):
    async def reply(context, **kwargs):
        return {"reply": "我先说明现在可以公开的情况。", "reveal": [], "trust_delta": 0}

    async def check(context, candidate):
        return {"ok": True, "leaked": [], "contradiction": ""}

    async def confront(contexts, event):
        return [{"speaker": context["character"]["id"], "text": "我说明已经公开的材料。"} for context in contexts]

    monkeypatch.setattr(agents, "reply", reply)
    monkeypatch.setattr(agents, "check_reply", check)
    monkeypatch.setattr(agents, "confront", confront)


@pytest.mark.asyncio
async def test_empty_reveal_delivers_one_authorized_clue_and_never_repeats(game_factory):
    story = progress_story()
    story["clues"][4]["requires"] = {}
    engine, game_id = game_factory(story)

    first = await engine.talk(game_id, "s", "有什么可以公开的材料？")
    second = await engine.talk(game_id, "s", "还有吗？")
    third = await engine.talk(game_id, "s", "继续")

    assert [clue["id"] for clue in first["new_clues"]] == ["c1"]
    assert [clue["id"] for clue in second["new_clues"]] == ["c5"]
    assert third["new_clues"] == []
    assert "我先说明" in first["reply"] and "我先说明" in second["reply"]
    assert "证据1" in first["reply"] and "证据5" in second["reply"]
    history = engine.games[game_id].histories["s"][1]["content"]
    assert history.startswith(first["reply"]) and "已获准的材料1" in history


@pytest.mark.asyncio
async def test_checked_answer_is_preserved_when_empty_reveal_is_supplemented(game_factory, monkeypatch):
    engine, game_id = game_factory()
    answer = "关于你刚才的问题，我能确认已经公开的情况。"

    async def reply(context, **kwargs):
        return {"reply": answer, "reveal": [], "trust_delta": 0}

    monkeypatch.setattr(agents, "reply", reply)
    result = await engine.talk(game_id, "s", "请回答问题，再把材料交给我")
    assert result["reply"].startswith(answer)
    assert "证据1" in result["reply"] and "交给你" in result["reply"]
    assert [clue["id"] for clue in result["new_clues"]] == ["c1"]


@pytest.mark.asyncio
async def test_fallback_delivery_records_only_authorized_material_in_own_history(game_factory, monkeypatch):
    story = progress_story()
    story["clues"][0]["content"] = "AUTHORIZED_DELIVERED_BODY"
    story["clues"][1]["content"] = "OTHER_ROLE_BODY"
    story["clues"][4]["content"] = "LOCKED_CLUE_BODY"
    story["clues"][7]["content"] = "PENDING_EVENT_BODY"
    story["facts"].append({"id": "private", "text": "PRIVATE_FACT_BODY"})
    story["characters"][0]["knows"].append("private")
    story["characters"][0]["secrets"].append({"fact": "private", "until": {"trust": 3}})
    engine, game_id = game_factory(story)

    async def rejected_reply(context, **kwargs):
        return {"reply": "REJECTED_MODEL_TEXT", "reveal": [], "trust_delta": 1}

    async def reject(context, candidate):
        return {"ok": False, "leaked": [], "contradiction": "测试拒绝"}

    monkeypatch.setattr(agents, "reply", rejected_reply)
    monkeypatch.setattr(agents, "check_reply", reject)
    result = await engine.talk(game_id, "s", "有什么材料？")
    assert "交给你" in result["reply"] and "REJECTED_MODEL_TEXT" not in result["reply"]
    assert "AUTHORIZED_DELIVERED_BODY" not in result["reply"]
    assert result["trust"]["s"] == 0
    contexts = []

    async def next_reply(context, **kwargs):
        contexts.append(deepcopy(context))
        return {"reply": "我可以解释刚才公开的材料。", "reveal": [], "trust_delta": 0}

    async def accept(context, candidate):
        return {"ok": True, "leaked": [], "contradiction": ""}

    monkeypatch.setattr(agents, "reply", next_reply)
    monkeypatch.setattr(agents, "check_reply", accept)
    await engine.talk(game_id, "s", "刚才交给我的材料是什么意思？")
    history = str(contexts[0]["history"])
    assert "AUTHORIZED_DELIVERED_BODY" in history and "证据1" in history
    for forbidden in ("REJECTED_MODEL_TEXT", "OTHER_ROLE_BODY", "LOCKED_CLUE_BODY", "PENDING_EVENT_BODY", "PRIVATE_FACT_BODY"):
        assert forbidden not in history
    assert contexts[0]["available_clues"] == []
    state = engine.games[game_id]
    assert state.histories["l"] == [] and state.histories["g"] == []


@pytest.mark.asyncio
async def test_valid_actor_choice_and_dialogue_are_preserved(game_factory, monkeypatch):
    story = progress_story()
    story["clues"][4]["requires"] = {}
    engine, game_id = game_factory(story)

    async def reply(context, **kwargs):
        return {"reply": "我先把这份证据交给你。", "reveal": ["c5"], "trust_delta": 1}

    monkeypatch.setattr(agents, "reply", reply)
    result = await engine.talk(game_id, "s", "想看看证据5")
    assert [clue["id"] for clue in result["new_clues"]] == ["c5"]
    assert result["reply"] == "我先把这份证据交给你。"
    assert result["trust"]["s"] == 1
    assert engine.games[game_id].acquired_clues == {"c5"}


@pytest.mark.asyncio
async def test_foreign_locked_and_event_clues_cannot_be_delivered(game_factory, monkeypatch):
    engine, game_id = game_factory()

    async def reply(context, **kwargs):
        return {"reply": "错误编号请求", "reveal": ["c2", "c4", "c8", "invented"], "trust_delta": 0}

    monkeypatch.setattr(agents, "reply", reply)
    result = await engine.talk(game_id, "s", "索要其他人的材料")
    assert [clue["id"] for clue in result["new_clues"]] == ["c1"]
    result = await engine.talk(game_id, "l", "把角色甲的证据5给我")
    assert result["new_clues"] == []
    assert engine.games[game_id].acquired_clues == {"c1"}


@pytest.mark.asyncio
async def test_new_trust_unlock_is_delivered_only_on_next_turn(game_factory, monkeypatch):
    engine, game_id = game_factory()

    async def reply(context, **kwargs):
        return {"reply": "继续交流。", "reveal": [], "trust_delta": 1}

    monkeypatch.setattr(agents, "reply", reply)
    first = await engine.talk(game_id, "g", "你好")
    assert first["trust"]["g"] == 1 and first["new_clues"] == []
    second = await engine.talk(game_id, "g", "还有什么材料？")
    assert [clue["id"] for clue in second["new_clues"]] == ["c4"]


@pytest.mark.asyncio
@pytest.mark.parametrize("character_id, expected_clues", [("s", ["c1"]), ("l", [])])
async def test_rejected_reply_uses_safe_delivery_or_evasion_without_trust(game_factory, monkeypatch, character_id, expected_clues):
    engine, game_id = game_factory()
    calls = 0

    async def reply(context, **kwargs):
        nonlocal calls
        calls += 1
        return {"reply": "REJECTED_MODEL_TEXT", "reveal": [], "trust_delta": 1}

    async def reject(context, candidate):
        return {"ok": False, "leaked": [], "contradiction": "测试拒绝"}

    monkeypatch.setattr(agents, "reply", reply)
    monkeypatch.setattr(agents, "check_reply", reject)
    result = await engine.talk(game_id, character_id, "可以给我材料吗？")
    state = engine.games[game_id]
    assert calls == 2
    assert [clue["id"] for clue in result["new_clues"]] == expected_clues
    assert result["trust"][character_id] == 0
    assert "REJECTED_MODEL_TEXT" not in str(state.histories)
    if expected_clues:
        assert "交给你" in result["reply"]
    else:
        assert result["reply"] == agents.evasive_reply(engine._context(state, character_id, ""))["reply"]


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["reply", "check_reply", "confront"])
async def test_service_failure_rolls_back_delivery_and_progress(game_factory, monkeypatch, step):
    engine, game_id = game_factory()
    state = engine.games[game_id]
    if step == "confront":
        state.acquired_clues.update({"c1", "c5"})
        state.shown["s"].add("c1")
    before = deepcopy(state)

    async def fail(*args, **kwargs):
        raise LLMError("模拟服务失败")

    monkeypatch.setattr(agents, step, fail)
    with pytest.raises(LLMError):
        if step == "confront":
            await engine.show(game_id, "s", "c5")
        else:
            await engine.talk(game_id, "s", "询问")
    assert engine.games[game_id] == before


@pytest.mark.asyncio
async def test_event_reward_waits_for_confrontation_and_is_delivered_once(game_factory, monkeypatch):
    engine, game_id = game_factory()
    state = engine.games[game_id]
    state.acquired_clues.update({"c1", "c5"})
    state.shown["s"].add("c1")
    assert (await engine.talk(game_id, "s", "还有材料吗？"))["new_clues"] == []
    confronted = []

    async def confront(contexts, event):
        confronted.append(event["id"])
        assert "c8" not in engine.games[game_id].acquired_clues
        assert all("c8" not in {clue["id"] for clue in context["available_clues"]} for context in contexts)
        return [{"speaker": context["character"]["id"], "text": "对质公开台词"} for context in contexts]

    monkeypatch.setattr(agents, "confront", confront)
    result = await engine.show(game_id, "s", "c5")
    assert [clue["id"] for clue in result["new_clues"]] == ["c8"]
    assert confronted == ["e1"]
    assert (await engine.show(game_id, "s", "c5"))["new_clues"] == []
    assert confronted == ["e1"]


@pytest.mark.asyncio
async def test_stuck_screenshot_state_gets_clues_then_owned_evidence_hint(game_factory):
    engine, game_id = game_factory()
    state = engine.games[game_id]
    state.acquired_clues.add("c1")
    state.shown["l"].add("c1")
    state.exposed_lies.add("l1")
    state.trust.update(l=1, g=1, s=0)
    state.turns = 12
    assert "证据2" in engine._next_hint(state) and "角色乙" in engine._next_hint(state)
    assert "出示" not in engine._next_hint(state)

    assert [clue["id"] for clue in (await engine.talk(game_id, "l", "继续"))["new_clues"]] == ["c2"]
    state = engine.games[game_id]
    assert "证据4" in engine._next_hint(state)
    await engine.talk(game_id, "g", "继续")
    state = engine.games[game_id]
    hint = engine._next_hint(state)
    assert "证据1" in hint and "角色甲" in hint and "出示" in hint
    assert "证据5" not in hint
    result = await engine.show(game_id, "s", "c1")
    assert [clue["id"] for clue in result["new_clues"]] == ["c5"]


@pytest.mark.asyncio
async def test_empty_actor_reveals_can_complete_generated_clue_chain(game_factory):
    engine, game_id = game_factory()
    await engine.talk(game_id, "s", "询问材料")
    await engine.show(game_id, "l", "c1")
    await engine.show(game_id, "s", "c1")
    await engine.show(game_id, "s", "c5")
    for _ in range(5):
        await engine.talk(game_id, "g", "继续交流并询问材料")
    await engine.show(game_id, "g", "c4")
    await engine.show(game_id, "g", "c3")
    await engine.talk(game_id, "g", "还有材料吗？")

    state = engine.games[game_id]
    assert state.turns == 12
    assert state.acquired_clues == {f"c{index}" for index in range(1, 9)}
    assert state.exposed_lies == {"l1", "l2"} and state.triggered_events == {"e1"}
    assert "提交推理" in engine._next_hint(state)


@pytest.mark.parametrize("done", [{}, {"has": "c1"}])
def test_generated_hints_continue_after_empty_or_finished_author_hint(game_factory, done):
    story = progress_story()
    story["kanshan"]["hints"] = [{"done": done, "vague": "STATIC_UNAVAILABLE_HINT", "direct": "STATIC_UNAVAILABLE_HINT"}]
    engine, game_id = game_factory(story)
    state = engine.games[game_id]
    state.acquired_clues.add("c1")
    state.shown["l"].add("c1")
    hint = engine._next_hint(state)
    assert "角色乙" in hint and "证据2" in hint
    assert "STATIC" not in hint and "PRIVATE_ENDING_TRUTH" not in hint


@pytest.mark.parametrize("source", ["lie", "event"])
def test_generated_show_hints_cover_lies_and_events(game_factory, source):
    engine, game_id = game_factory()
    state = engine.games[game_id]
    state.acquired_clues.update(f"c{index}" for index in range(1, 8))
    state.exposed_lies.add("l1")
    if source == "event":
        state.exposed_lies.add("l2")
    hint = engine._next_hint(state)
    assert "出示" in hint
    if source == "lie":
        assert "证据4" in hint and "角色丙" in hint
    else:
        assert "证据5" in hint and "角色甲" in hint
    assert "证据8" not in hint


def test_generated_trust_hint_waits_for_other_requirements(game_factory):
    story = progress_story()
    story["clues"][3]["requires"] = {"trust": 1, "shown": "c2"}
    engine, game_id = game_factory(story)
    state = engine.games[game_id]
    state.acquired_clues.update({"c1", "c2", "c3", "c5", "c6", "c7", "c8"})
    state.exposed_lies.update({"l1", "l2"})
    state.triggered_events.add("e1")
    assert "出示" in engine._next_hint(state) and "证据2" in engine._next_hint(state)
    state.shown["g"].add("c2")
    hint = engine._next_hint(state)
    assert "角色丙" in hint and "信任" in hint and "出示" not in hint


def test_all_clues_collected_hint_invites_reasoning_without_truth(game_factory):
    engine, game_id = game_factory()
    state = engine.games[game_id]
    state.acquired_clues.update(clue["id"] for clue in state.story["clues"])
    hint = engine._next_hint(state)
    assert "整理证据" in hint and "提交推理" in hint
    assert "PRIVATE_ENDING_TRUTH" not in hint


def test_official_authored_vague_and_direct_hints_are_preserved(game_factory):
    story = progress_story()
    story["kanshan"]["hints"] = [{"done": {"has": "c1"}, "vague": "V1", "direct": "D1"}]
    engine, game_id = game_factory(story, source="official")
    state = engine.games[game_id]
    assert engine._next_hint(state) == "V1"
    assert engine._next_hint(state) == "D1"
    state.acquired_clues.add("c1")
    assert engine._next_hint(state) is None


@pytest.mark.parametrize("source", ["official", "generated"])
def test_legacy_handwritten_hints_keep_original_order(game_factory, source):
    story = progress_story()
    story.pop("kanshan")
    story["hints"] = [{"text": "旧版提示一"}, {"text": "旧版提示二"}]
    engine, game_id = game_factory(story, source=source)
    state = engine.games[game_id]
    assert engine._next_hint(state) == "旧版提示一"
    assert engine._next_hint(state) == "旧版提示二"
    assert engine._next_hint(state) is None
