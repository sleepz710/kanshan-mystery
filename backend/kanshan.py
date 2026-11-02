"""任务 02 的汤主问答占位，任务 05 接入真实模型后替换。"""

from backend import llm


async def answer(story: dict, question: str) -> str:
    if not llm.is_mock_mode():
        raise llm.LLMError("刘看山问答待任务 05 接入，请先使用模拟模式联调。", status_code=503)
    return "不重要"
