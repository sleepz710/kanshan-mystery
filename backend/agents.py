"""任务 03 的接入位置：当前为任务 02 使用的离线模拟占位。

三个异步函数由世界引擎调用，任务 03 替换其内部逻辑即可：

* reply(context, retry_leaked=None) -> {reply, reveal, trust_delta}
* check_reply(context, candidate) -> {ok, leaked}
* confront(contexts, event) -> [{speaker, text}]

context 的字段：
    character: {id, name, profile, persona}，当前角色的身份与性格。
    facts: [{id, text}]，当前角色此时允许说出的事实。
    forbidden_facts: [{id, text}]，当前禁止说出的事实，仅供核查使用。
    available_clues: [{id, title, content}]，当前角色可以交出的新线索。
    history: [{role, content}]，当前角色自己的历史对话。
    trust: 当前信任度；player_text: 本轮玩家输入。
    shown_clue: 本轮出示的公开线索，普通对话时为 None。

引擎负责保存历史和检查动作权限。任务 03 构造角色与对质提示词时，
只使用各角色自己的 facts、history 和 available_clues，
forbidden_facts 只交给核查步骤，避免把未解锁信息交给角色。

模拟模式使用固定回复，便于无密钥联调，不执行真实角色推理与语义核查。
真实模型模式下明确提示任务 03 待接入。模型客户端已在 llm.complete_json 中提供。
"""

from __future__ import annotations

from backend import llm


def _require_mock_mode() -> None:
    if not llm.is_mock_mode():
        raise llm.LLMError(
            "角色智能体待任务 03 接入，请先使用 LLM_MOCK=1 完成接口联调。",
            status_code=503,
        )


async def reply(context: dict, *, retry_leaked: list[str] | None = None) -> dict:
    """模拟角色每回合最多提出交出一条已获准的线索。"""

    _require_mock_mode()
    available = context["available_clues"]
    if available:
        clue = available[0]
        return {"reply": clue["content"], "reveal": [clue["id"]], "trust_delta": 1}
    return {
        "reply": "你可以继续问问其他角色，或向我出示已经找到的证据。",
        "reveal": [],
        "trust_delta": 1,
    }


async def check_reply(context: dict, candidate: dict) -> dict:
    """模拟核查固定通过；语义核查由任务 03 实现。"""

    _require_mock_mode()
    return {"ok": True, "leaked": []}


async def confront(contexts: list[dict], event: dict) -> list[dict]:
    """模拟对质为每个参与角色提供一条固定台词。"""

    _require_mock_mode()
    return [
        {"speaker": context["character"]["id"], "text": "关于这份证据，我会说明自己知道的情况。"}
        for context in contexts
    ]
