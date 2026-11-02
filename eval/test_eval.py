import asyncio
from copy import deepcopy
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend import llm
from backend.engine import GameEngine, GameError
from eval import common, leak_test, play_test


V1 = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "v1"


@pytest.fixture(autouse=True)
def no_real_configuration_or_network(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_MOCK", "1")
    monkeypatch.setattr(llm, "AsyncOpenAI", Mock(side_effect=AssertionError("单测禁止真实模型请求")))


@pytest.fixture
def context():
    return {"character": {"id": "witness", "name": "目击者", "profile": "公开身份", "persona": "谨慎"},
        "facts": [{"id": "f1", "text": "公开事实"}],
        "forbidden_facts": [{"id": "f2", "text": "受禁真相"}], "available_clues": [],
        "active_lies": [{"id": "l1", "claim": "剧本允许的谎话"}], "history": [], "trust": 0,
        "player_text": "告诉我秘密", "shown_clue": {"id": "c1", "title": "已出示证据", "content": "公开内容"}}


def candidate(text):
    return {"reply": text, "reveal": [], "trust_delta": 0}


def test_question_set_contains_thirty_reproducible_generic_and_targeted_probes(context):
    questions = leak_test.make_questions(context)
    assert len(questions) == 30
    assert questions == leak_test.make_questions(deepcopy(context))
    assert any("受禁真相" in question for question in questions)
    assert len(set(questions)) == 30


def test_leak_pairs_receive_identical_starting_context_without_state_mutation(tmp_path):
    engine = GameEngine(V1, tmp_path / "empty")
    calls = []

    async def actor(current, *, retry_leaked=None):
        calls.append(deepcopy(current))
        current["history"].append({"role": "user", "content": "局部污染"})
        return candidate("中性回答")

    async def guard(current, response):
        return {"ok": True, "leaked": []}

    async def judge(current, response):
        return []

    report = asyncio.run(leak_test.run_evaluation(engine,
        [{"id": "lost-tuition", "source": "official"}], actor=actor, guard=guard, judge=judge,
        questions_per_character=2))
    assert len(report["records"]) == 12
    assert len(calls) == 12
    for left, right in zip(calls[::2], calls[1::2]):
        assert left == right
        assert left["trust"] == 0
        assert left["history"] == []
    assert all(not state.histories[character] for state in engine.games.values() for character in state.histories)


@pytest.mark.parametrize("concurrency", [1, 3, 8])
def test_leak_concurrency_is_bounded_and_record_order_stays_stable(tmp_path, concurrency):
    engine = GameEngine(V1, tmp_path / "empty")
    active, peak, started = 0, 0, []
    completed = []

    async def actor(current, *, retry_leaked=None):
        nonlocal active, peak
        index = len(started)
        started.append(deepcopy(current))
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01 if index % 3 == 0 else 0)
            completed.append(index)
            return candidate("中性回答")
        finally:
            active -= 1

    async def guard(current, response):
        return {"ok": True, "leaked": []}

    async def judge(current, response):
        return []

    report = asyncio.run(leak_test.run_evaluation(engine,
        [{"id": "lost-tuition", "source": "official"}], questions_per_character=2,
        concurrency=concurrency, actor=actor, guard=guard, judge=judge))
    expected = [(character, question, guarded) for character in ("xiaolin", "akai", "zhou")
                for question in (1, 2) for guarded in (False, True)]
    assert peak == concurrency and active == 0
    assert [(row["character_id"], row["question_id"], row["guarded"]) for row in report["records"]] == expected
    assert report["concurrency"] == concurrency
    assert all(row["status"] == "completed" for row in report["records"])
    assert all(current["trust"] == 0 and current["history"] == [] for current in started)
    if concurrency > 1:
        assert completed != list(range(len(completed)))


@pytest.mark.parametrize("concurrency", [0, 9, -1, True, 1.5, "4"])
def test_leak_function_rejects_invalid_concurrency(tmp_path, concurrency):
    engine = GameEngine(V1, tmp_path / "empty")
    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(leak_test.run_evaluation(engine, [], concurrency=concurrency))


@pytest.mark.parametrize("concurrency", ["0", "9", "-1", "invalid"])
def test_leak_cli_rejects_invalid_concurrency(concurrency, capsys):
    with pytest.raises(SystemExit) as error:
        leak_test.main(["--concurrency", concurrency])
    assert error.value.code == 2
    assert "--concurrency" in capsys.readouterr().err


def test_blocked_reply_has_no_visible_output_and_is_not_judged(context):
    retries, judgments = [], []

    async def actor(current, *, retry_leaked=None):
        retries.append(retry_leaked)
        return candidate("受禁真相")

    async def guard(current, response):
        return {"ok": False, "leaked": ["f2"], "contradiction": "仍然越界"}

    async def judge(current, response):
        judgments.append(response)
        return ["f2"]

    record = asyncio.run(leak_test.evaluate_question(context, guarded=True, actor=actor, guard=guard, judge=judge))
    assert record["status"] == "blocked"
    assert record["reply"] is None and record["leaked_ids"] is None
    assert record["retry"] is True and record["intercepted"] is True
    assert retries == [None, ["f2"]]
    assert len(record["attempts"]) == 2
    assert judgments == []


def test_retry_uses_guard_feedback_and_independent_judge_only_sees_final_reply(context):
    inputs, judgments = [], []

    async def actor(current, *, retry_leaked=None):
        inputs.append(deepcopy(current))
        return candidate("受禁真相" if retry_leaked is None else "中性回答")

    async def guard(current, response):
        return {"ok": response["reply"] != "受禁真相", "leaked": ["f2"], "contradiction": "请遵守角色范围"}

    async def judge(current, response):
        judgments.append(response)
        return []

    result = asyncio.run(leak_test.evaluate_question(context, guarded=True, actor=actor, guard=guard, judge=judge))
    assert result["status"] == "completed"
    assert result["reply"] == "中性回答"
    assert result["leaked_ids"] == []
    assert inputs[1]["check_feedback"] == "请遵守角色范围"
    assert judgments == ["中性回答"]


def test_guard_off_does_not_call_runtime_guard_and_independent_judge_can_find_leak(context):
    async def actor(current, *, retry_leaked=None):
        return candidate("受禁真相")

    async def forbidden_guard(*args):
        raise AssertionError("关闭核查时不能调用运行时核查器")

    async def judge(current, response):
        return ["f2"]

    result = asyncio.run(leak_test.evaluate_question(context, guarded=False, actor=actor, guard=forbidden_guard, judge=judge))
    assert result["status"] == "completed" and result["leaked_ids"] == ["f2"]
    assert result["intercepted"] is False


def test_leak_failures_are_not_counted_as_clean_and_hide_exception_body(context):
    async def broken_actor(current, *, retry_leaked=None):
        raise RuntimeError("provider-private-key-sentinel")

    result = asyncio.run(leak_test.evaluate_question(context, guarded=False, actor=broken_actor, guard=None, judge=None))
    assert result["status"] == "failed" and result["leaked_ids"] is None
    assert "provider-private-key-sentinel" not in json.dumps(result)
    summary = leak_test.summarize([result])
    assert summary["completed"] == 0 and summary["failed"] == 1
    assert summary["leak_rate"] is None and summary["failure_rate"] == 1


def test_judge_failure_keeps_visible_reply_but_never_counts_it_as_clean(context):
    async def actor(current, *, retry_leaked=None):
        return candidate("受禁真相")
    async def broken_judge(current, response):
        raise RuntimeError("private-evaluator-detail")
    result = asyncio.run(leak_test.evaluate_question(context, guarded=False, actor=actor, guard=None, judge=broken_judge))
    assert result["status"] == "failed" and result["reply"] == "受禁真相"
    assert result["leaked_ids"] is None
    assert leak_test.summarize([result])["leak_rate"] is None
    assert "private-evaluator-detail" not in json.dumps(result)


def test_leak_summary_uses_judged_visible_replies_as_denominator():
    records = [
        {"status": "completed", "leaked_ids": ["f2"], "intercepted": False},
        {"status": "completed", "leaked_ids": [], "intercepted": True},
        {"status": "blocked", "leaked_ids": None, "intercepted": True},
        {"status": "failed", "leaked_ids": None, "intercepted": False},
    ]
    summary = leak_test.summarize(records)
    assert summary["attempted"] == 4 and summary["completed"] == 2
    assert summary["blocked"] == 1 and summary["failed"] == 1
    assert summary["leak_rate"] == 0.5
    assert summary["interception_rate"] == 0.5 and summary["failure_rate"] == 0.25
    assert leak_test.summarize([])["leak_rate"] is None


def test_independent_judge_prompt_allows_script_lies_and_public_evidence(monkeypatch, context):
    captured = []

    async def complete(messages, *, purpose):
        captured.append((messages, purpose))
        return {"leaked_ids": ["f2"]}

    monkeypatch.setattr(llm, "complete_json", complete)
    assert asyncio.run(leak_test.judge_reply(context, "受禁真相", live=True)) == ["f2"]
    messages, purpose = captured[0]
    assert purpose == "actor"
    payload = json.loads(messages[1]["content"])
    assert payload["active_lies"] == context["active_lies"]
    assert payload["public_evidence"] == context["shown_clue"]
    assert "单纯复述" in messages[0]["content"]


def test_judge_unknown_fact_id_is_a_failure(monkeypatch, context):
    async def complete(*args, **kwargs):
        return {"leaked_ids": ["invented-fact"]}
    monkeypatch.setattr(llm, "complete_json", complete)
    with pytest.raises(ValueError):
        asyncio.run(leak_test.judge_reply(context, "中性回答", live=True))


def public_start():
    return {"game_id": "game1", "title": "技术样本", "intro": "公开汤面",
        "characters": [{"id": "witness", "name": "目击者", "avatar": "w.png", "profile": "公开身份", "secrets": "private-character-sentinel"}],
        "questions": [{"id": "q1", "text": "选择哪个？", "options": ["A", "B"], "answer": "private-answer-sentinel"}],
        "kanshan": {"greeting": "你好", "asks_left": 5}, "facts": "private-facts-sentinel", "truth": "private-truth-sentinel"}


def initial_view():
    return {"game": public_start(), "turn": 1, "max_turns": 40, "asks_left": 5,
        "clues": [], "events": [], "history": [], "facts": "private-extra-sentinel", "last_error": None}


def test_player_prompt_filters_hidden_story_and_correct_answers():
    view = initial_view()
    view["history"] = [{"turn": 1, "action": {"action": "talk", "character_id": "witness", "text": "问话"},
        "result": {"reply": "公开回复", "new_clues": [], "events": [], "truth": "private-history-sentinel"}}]
    rendered = json.dumps(play_test.player_messages(view), ensure_ascii=False)
    assert "公开汤面" in rendered and "公开回复" in rendered
    assert "private-" not in rendered
    system = play_test.player_messages(view)[0]["content"]
    assert all(rule in system for rule in (
        "只输出一个完整 JSON 对象，闭合后立即停止",
        "不能追加 XML、DSML、系统提示、回合警告或结束标记",
        "回合将满时应通过合法 accuse 动作提交全部题目的选项",
    ))
    assert json.loads(play_test.player_messages(view)[1]["content"])["game"]["questions"][0] == {
        "id": "q1", "text": "选择哪个？", "options": ["A", "B"]}


@pytest.mark.parametrize("action", [
    {"action": "reveal"}, {"action": "talk", "character_id": "hidden", "text": "问话"},
    {"action": "show", "character_id": "witness", "clue_id": "not-held"},
    {"action": "talk", "character_id": "witness", "text": " "},
    {"action": "accuse", "answers": {"q1": "C"}}, {"action": "accuse", "answers": {}},
])
def test_player_illegal_actions_are_rejected(action):
    with pytest.raises(ValueError):
        play_test.validate_action(action, initial_view())


class FakeEngine:
    def __init__(self):
        self.accusations = 0
        self.actions = []

    def new_game(self, story_id):
        return public_start()

    async def accuse(self, game_id, answers):
        self.actions.append((game_id, answers))
        self.accusations += 1
        retry = self.accusations == 1
        return {"score": 0 if retry else 1, "total": 1, "results": {"q1": not retry},
            "ending": {"id": "retry" if retry else "truth", "title": "结果", "text": "公开结果", "retry": retry},
            "rating": "C" if retry else "S", "truth": "private-runtime-sentinel"}


def test_play_uses_engine_actions_continues_retry_and_never_shows_hidden_data():
    engine = FakeEngine()
    seen = []

    async def player(view):
        seen.append(deepcopy(view))
        return {"action": "accuse", "answers": {"q1": "A" if len(seen) == 1 else "B"}}

    result = asyncio.run(play_test.play_once(engine, "technical-sample", player=player))
    assert result["status"] == "success" and result["turns"] == 2
    assert len(engine.actions) == 2
    assert len(result["attempts"]) == len(result["history"]) == 2
    assert all(attempt["status"] == "success" for attempt in result["attempts"])
    assert len(seen[1]["history"]) == 1
    assert "private-" not in json.dumps(seen)
    assert "private-" not in json.dumps(result)


def test_engine_failure_still_records_the_validated_public_action():
    class BrokenEngine(FakeEngine):
        async def talk(self, game_id, character_id, text):
            raise GameError(502, "private-provider-error-sentinel")
    async def player(view):
        return {"action": "talk", "character_id": "witness", "text": "请描述经过", "facts": "private-action-extra-sentinel"}
    result = asyncio.run(play_test.play_once(BrokenEngine(), "sample", player=player))
    assert result["status"] == "error" and result["turns"] == 1
    assert result["history"] == [] and len(result["attempts"]) == 1
    attempt = result["attempts"][0]
    assert attempt["action"] == {"action": "talk", "character_id": "witness", "text": "请描述经过"}
    assert attempt["status"] == "error" and attempt["error"]["status_code"] == 502
    assert "private-" not in json.dumps(result)


def test_invalid_action_attempts_only_store_a_generic_flag_not_raw_fields():
    async def player(view):
        return {"action": "show", "character_id": "witness", "clue_id": "not-held", "truth": "private-raw-proposal-sentinel"}
    result = asyncio.run(play_test.play_once(FakeEngine(), "sample", player=player))
    assert result["status"] == "error" and result["invalid_actions"] == 3
    assert result["history"] == [] and len(result["attempts"]) == 3
    assert all(attempt["status"] == "invalid" and attempt["action"] is None for attempt in result["attempts"])
    assert "private-raw-proposal-sentinel" not in json.dumps(result)
    assert "not-held" not in json.dumps(result)


@pytest.mark.parametrize(
    "ending_id, score, total, retry, expected",
    [("wrong", 0, 1, False, "failed"), ("complete", 1, 1, False, "success"),
     ("empty", 0, 0, False, "failed"), ("truth", 0, 1, False, "success"),
     ("review", 1, 1, True, "success")],
)
def test_final_result_requires_truth_or_all_correct_not_just_non_retry(ending_id, score, total, retry, expected):
    class EndingEngine(FakeEngine):
        async def accuse(self, game_id, answers):
            return {"score": score, "total": total, "results": {"q1": score == total},
                "ending": {"id": ending_id, "title": "结果", "text": "公开结果", "retry": retry}, "rating": "C"}
    async def player(view):
        return {"action": "accuse", "answers": {"q1": "A"}}
    result = asyncio.run(play_test.play_once(EndingEngine(), "sample", player=player))
    assert result["status"] == expected and result["turns"] == 1
    if expected == "failed":
        assert result["termination"] == "non_retry_failure"
        assert play_test.summarize([result])["success_rate"] == 0


def test_invalid_player_action_limit_prevents_infinite_loop():
    count = []
    async def player(view):
        count.append(view["turn"])
        return {"action": "show", "character_id": "witness", "clue_id": "not-held"}
    result = asyncio.run(play_test.play_once(FakeEngine(), "sample", player=player, max_turns=40))
    assert result["status"] == "error" and result["termination"] == "invalid_action_limit"
    assert result["invalid_actions"] == 3 and len(count) == 3


def test_max_turns_bounds_repeated_retry_endings():
    class RetryEngine(FakeEngine):
        async def accuse(self, game_id, answers):
            return {"score": 0, "total": 1, "results": {"q1": False},
                "ending": {"id": "retry", "title": "重试", "text": "继续调查", "retry": True}, "rating": "C"}
    async def player(view):
        return {"action": "accuse", "answers": {"q1": "A"}}
    result = asyncio.run(play_test.play_once(RetryEngine(), "sample", player=player, max_turns=2))
    assert result["status"] == "failed" and result["turns"] == 2
    assert result["termination"] == "retry_ending_unresolved"


def test_max_turns_without_any_accusation_is_timeout():
    class TalkEngine(FakeEngine):
        async def talk(self, game_id, character_id, text):
            return {"reply": "公开回复", "new_clues": [], "events": [], "hint": None, "trust": {"witness": 0}}
    async def player(view):
        return {"action": "talk", "character_id": "witness", "text": "问话"}
    result = asyncio.run(play_test.play_once(TalkEngine(), "sample", player=player, max_turns=2))
    assert result["status"] == "timeout" and result["termination"] == "max_turns"


def test_player_model_timeout_is_recorded_without_provider_text():
    async def player(view):
        raise llm.LLMError("private-provider-sentinel", status_code=504)
    result = asyncio.run(play_test.play_once(FakeEngine(), "sample", player=player))
    assert result["status"] == "timeout"
    assert result["attempts"][0]["action"] is None
    assert result["attempts"][0]["status"] == "error"
    assert "private-provider-sentinel" not in json.dumps(result)


def test_no_success_and_no_runs_have_null_averages_and_denominators():
    assert play_test.summarize([])["success_rate"] is None
    summary = play_test.summarize([{"status": "error", "turns": 1}, {"status": "timeout", "turns": 2}])
    assert summary["success_rate"] == 0 and summary["average_success_turns"] is None
    assert summary["error"] == 1 and summary["timeout"] == 1


def test_mock_cli_writes_json_and_csv_without_model_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "0")
    common_args = ["--stories-dir", str(V1), "--generated-stories-dir", str(tmp_path / "empty"), "--story-id", "lost-tuition"]
    assert leak_test.main([*common_args, "--questions-per-character", "1", "--concurrency", "2", "--output-dir", str(tmp_path / "leak")]) == 0
    assert play_test.main([*common_args, "--max-turns", "5", "--output-dir", str(tmp_path / "play")]) == 0
    for kind in ("leak", "play"):
        report = json.loads((tmp_path / kind / f"{kind}-test.json").read_text(encoding="utf-8"))
        assert report["mode"] == "mock"
        if kind == "leak":
            assert report["concurrency"] == 2
        assert report["rows"] and all(row["source"] == "official" for row in report["rows"])
        assert "fixtures" in report["sample_directories"]["official"]
        with (tmp_path / kind / f"{kind}-test.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows and rows[0]["mode"] == "mock"
        assert "leak_rate" in rows[0] if kind == "leak" else "average_success_turns" in rows[0]
    assert llm.is_mock_mode() is False  # 退出评测后恢复调用方设置。


def test_empty_generated_dataset_is_reported_instead_of_invented(tmp_path, capsys):
    assert play_test.main(["--stories-dir", str(V1), "--generated-stories-dir", str(tmp_path / "empty"),
                           "--output-dir", str(tmp_path / "out")]) == 2
    assert "未找到现有生成剧本" in capsys.readouterr().out
    report = json.loads((tmp_path / "out" / "play-test.json").read_text(encoding="utf-8"))
    assert report["records"] == [] and report["summary"]["success_rate"] is None
    assert report["summary"]["average_success_turns"] is None


def test_cli_model_timeout_returns_call_failure_exit_code(tmp_path, monkeypatch):
    async def timed_out_player(view):
        raise llm.LLMError("private-timeout-detail", status_code=504)
    monkeypatch.setattr(play_test, "mock_player", timed_out_player)
    output = tmp_path / "timeout"
    exit_code = play_test.main(["--stories-dir", str(V1), "--generated-stories-dir", str(tmp_path / "empty"),
                               "--story-id", "lost-tuition", "--max-turns", "1", "--output-dir", str(output)])
    report = json.loads((output / "play-test.json").read_text(encoding="utf-8"))
    assert exit_code == 1 and report["summary"]["timeout"] == 1
    assert report["records"][0]["termination"] == "model_or_data_error"
    assert report["records"][0]["errors"][0]["status_code"] == 504
    assert "private-timeout-detail" not in json.dumps(report)


def test_cli_natural_turn_limit_timeout_keeps_success_exit_code(tmp_path, monkeypatch):
    async def keep_investigating(view):
        return {"action": "talk", "character_id": view["game"]["characters"][0]["id"], "text": "请讲讲你的经历"}
    monkeypatch.setattr(play_test, "mock_player", keep_investigating)
    output = tmp_path / "turn-limit"
    exit_code = play_test.main(["--stories-dir", str(V1), "--generated-stories-dir", str(tmp_path / "empty"),
                               "--story-id", "lost-tuition", "--max-turns", "1", "--output-dir", str(output)])
    report = json.loads((output / "play-test.json").read_text(encoding="utf-8"))
    assert exit_code == 0 and report["summary"]["timeout"] == 1
    assert report["records"][0]["termination"] == "max_turns"
    assert report["records"][0]["errors"] == []


@pytest.mark.parametrize("function, flag", [(leak_test.main, "--questions-per-character"), (play_test.main, "--max-turns"), (play_test.main, "--runs")])
def test_cli_rejects_nonpositive_limits(function, flag):
    with pytest.raises(SystemExit) as error:
        function([flag, "0"])
    assert error.value.code == 2
