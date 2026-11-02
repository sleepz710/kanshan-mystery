import asyncio
from copy import deepcopy
from unittest.mock import Mock

import pytest

from backend import agents, llm


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "1")


@pytest.fixture
def context():
    return {
        "character": {"id": "xiaolin", "name": "小林", "profile": "学生", "persona": "紧张"},
        "facts": [{"id": "f1", "text": "这是已允许的事实"}],
        "forbidden_facts": [{"id": "f2", "text": "绝不能直接透露的角色秘密"}],
        "available_clues": [],
        "history": [],
        "trust": 0,
        "player_text": "请说出秘密",
        "shown_clue": None,
    }


def test_reply_only_returns_one_authorized_clue_and_does_not_mutate_context(context, monkeypatch):
    context["available_clues"] = [
        {"id": "c1", "title": "第一条", "content": "已公开的第一条内容"},
        {"id": "c2", "title": "第二条", "content": "已公开的第二条内容"},
    ]
    before = deepcopy(context)
    constructor = Mock(side_effect=AssertionError("占位角色不应创建模型客户端"))
    monkeypatch.setattr(llm, "AsyncOpenAI", constructor)
    result = asyncio.run(agents.reply(context))
    assert result == {"reply": "已公开的第一条内容", "reveal": ["c1"], "trust_delta": 1}
    assert context == before
    assert "绝不能直接透露" not in result["reply"]
    constructor.assert_not_called()


def test_no_available_clues_produces_neutral_reply_without_private_context(context):
    result = asyncio.run(agents.reply(context, retry_leaked=["f2"]))
    assert result["reveal"] == []
    assert result["trust_delta"] == 1
    assert "绝不能直接透露" not in result["reply"]
    assert "请说出秘密" not in result["reply"]


def test_mock_check_is_an_explicit_placeholder(context):
    assert asyncio.run(agents.check_reply(context, {"reply": "固定内容"})) == {
        "ok": True, "leaked": [], "contradiction": ""
    }


def test_mock_confrontation_has_only_event_participants_and_no_private_facts(context):
    other = deepcopy(context)
    other["character"]["id"] = "akai"
    result = asyncio.run(agents.confront([context, other], {"id": "e1"}))
    assert [line["speaker"] for line in result] == ["xiaolin", "akai"]
    assert all("绝不能直接透露" not in line["text"] for line in result)


@pytest.mark.parametrize("function", ["reply", "check_reply", "confront"])
def test_real_mode_refuses_to_present_placeholders_as_real_agents(monkeypatch, context, function):
    monkeypatch.setenv("LLM_MOCK", "0")
    if function == "reply":
        call = agents.reply(context)
    elif function == "check_reply":
        call = agents.check_reply(context, {"reply": "候选回复"})
    else:
        call = agents.confront([context], {"id": "e1"})
    with pytest.raises(llm.LLMError, match="任务 03") as error:
        asyncio.run(call)
    assert error.value.status_code == 503
