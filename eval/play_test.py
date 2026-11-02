"""只读取玩家可见信息、通过世界引擎执行动作的完整试玩评测。

默认评测已有生成案件；没有样本时明确退出，不创建剧本。
python -m eval.play_test --story-id lost-tuition --max-turns 10
只有加 --live 才会调用真实玩家、角色和汤主模型。
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

from backend import llm
from backend.engine import GameEngine, GameError
from eval.common import base_report, common_parser, evaluation_mode, positive_int, ratio, safe_error, select_samples, write_reports


MAX_INVALID_ACTIONS = 3
SUCCESS_RULE = "只检查公开结果：ending.id == truth，或全题正确（score == total 且 total > 0）"


def _fields(value: dict, names: tuple[str, ...]) -> dict:
    return {name: deepcopy(value[name]) for name in names if name in value}


def public_game(game: dict) -> dict:
    result = _fields(game, ("game_id", "title", "intro"))
    result["characters"] = [_fields(character, ("id", "name", "avatar", "profile")) for character in game["characters"]]
    result["questions"] = [_fields(question, ("id", "text", "options")) for question in game["questions"]]
    result["kanshan"] = _fields(game.get("kanshan", {}), ("greeting", "asks_left"))
    return result


def public_action(action: dict) -> dict:
    name = action.get("action")
    keys = {"talk": ("action", "character_id", "text"), "show": ("action", "character_id", "clue_id"),
            "ask": ("action", "question"), "accuse": ("action", "answers")}
    return _fields(action, keys.get(name, ("action",)))


def public_event(event: dict) -> dict:
    result = _fields(event, ("type", "character", "lie", "text"))
    if "lines" in event:
        result["lines"] = [_fields(line, ("speaker", "text")) for line in event["lines"]]
    return result


def public_result(action: str, result: dict) -> dict:
    if action in ("talk", "show"):
        visible = _fields(result, ("reply", "hint", "trust"))
        visible["new_clues"] = [_fields(clue, ("id", "title", "content")) for clue in result.get("new_clues", [])]
        visible["events"] = [public_event(event) for event in result.get("events", [])]
        return visible
    if action == "ask":
        return _fields(result, ("answer", "asks_left"))
    visible = _fields(result, ("score", "total", "results", "rating"))
    visible["ending"] = _fields(result["ending"], ("id", "title", "text", "retry"))
    return visible


def player_messages(view: dict) -> list[dict]:
    payload = {"game": public_game(view["game"]), "turn": view["turn"], "max_turns": view["max_turns"],
        "asks_left": view["asks_left"], "clues": [_fields(c, ("id", "title", "content")) for c in view["clues"]],
        "events": [public_event(event) for event in view["events"]],
        "history": [{"turn": item["turn"], "action": public_action(item["action"]),
                     "result": public_result(item["action"]["action"], item["result"])} for item in view["history"]],
        "last_error": view.get("last_error")}
    return [
        {"role": "system", "content": (
            "你是推理游戏的玩家，要通过调查查清案子。你只能使用这里给出的公开案情、角色、线索、事件和历史。"
            "每次只选一个动作，输出 JSON 对象。可选格式："
            '{"action":"talk","character_id":"角色id","text":"问题"}；'
            '{"action":"show","character_id":"角色id","clue_id":"已获得的线索id"}；'
            '{"action":"ask","question":"向汤主问的是非题"}；'
            '{"action":"accuse","answers":{"题目id":"该题选项"}}。'
            "出示证据前必须已获得该线索；汤主剩余次数为0时不可再问。提交时回答全部题目，使用原样选项。"
            "如果结局允许重试，可以继续调查并再次提交。不要凭空捏造角色或线索编号。"
            "只输出一个完整 JSON 对象，闭合后立即停止。"
            "不能追加 XML、DSML、系统提示、回合警告或结束标记，也不要 Markdown 或解释。"
            "回合将满时应通过合法 accuse 动作提交全部题目的选项，不能用文字警告、总结或告别。"
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def model_player(view: dict) -> dict:
    return await llm.complete_json(player_messages(view), purpose="actor")


async def mock_player(view: dict) -> dict:
    """确定性管线策略：轮流问话、出示公开证据，最后依据公开判分尝试选项。"""
    characters = [character["id"] for character in view["game"]["characters"]]
    questions = view["game"]["questions"]
    accusations = [item for item in view["history"] if item["action"]["action"] == "accuse"]
    if accusations or view["turn"] >= view["max_turns"] - 3:
        previous = accusations[-1] if accusations else None
        answers = {}
        for question in questions:
            selected = question["options"][0]
            if previous:
                selected = previous["action"]["answers"][question["id"]]
                if not previous["result"]["results"][question["id"]]:
                    selected = question["options"][(question["options"].index(selected) + 1) % len(question["options"])]
            answers[question["id"]] = selected
        return {"action": "accuse", "answers": answers}
    if view["turn"] <= len(characters) * 4:
        return {"action": "talk", "character_id": characters[(view["turn"] - 1) % len(characters)], "text": "请说说你的经历，可以给我看看相关证据吗？"}
    shown = {(item["action"]["character_id"], item["action"]["clue_id"])
             for item in view["history"] if item["action"]["action"] == "show"}
    for clue in view["clues"]:
        for character_id in characters:
            if (character_id, clue["id"]) not in shown:
                return {"action": "show", "character_id": character_id, "clue_id": clue["id"]}
    return {"action": "accuse", "answers": {q["id"]: q["options"][0] for q in questions}}


def validate_action(action: dict, view: dict) -> dict:
    if not isinstance(action, dict) or action.get("action") not in ("talk", "show", "ask", "accuse"):
        raise ValueError("动作必须是 talk、show、ask 或 accuse")
    name = action["action"]
    if name in ("talk", "show"):
        if action.get("character_id") not in {c["id"] for c in view["game"]["characters"]}:
            raise ValueError("只能选择公开角色")
        if name == "talk" and (not isinstance(action.get("text"), str) or not 0 < len(action["text"].strip()) <= 4000):
            raise ValueError("对话问题需要是1到4000字的文本")
        if name == "show" and action.get("clue_id") not in {c["id"] for c in view["clues"]}:
            raise ValueError("只能出示已经获得的线索")
    elif name == "ask":
        if view["asks_left"] <= 0 or not isinstance(action.get("question"), str) or not 0 < len(action["question"].strip()) <= 4000:
            raise ValueError("汤主提问需要有效问题和剩余次数")
    else:
        answers = action.get("answers")
        questions = view["game"]["questions"]
        if (not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions}
            or any(not isinstance(answers[q["id"]], str) or answers[q["id"]] not in q["options"] for q in questions)):
            raise ValueError("提交推理必须完整使用公开题目的选项")
    return public_action(action)


async def play_once(engine, story_id: str, *, live=False, max_turns=40, player=None) -> dict:
    if type(max_turns) is not int or max_turns <= 0:
        raise ValueError("max_turns 必须是正整数")
    record = {"story_id": story_id, "mode": "live" if live else "mock", "status": "timeout", "turns": 0,
              "invalid_actions": 0, "ending": None, "history": [], "attempts": [], "errors": [], "termination": "max_turns"}
    player = player or (model_player if live else mock_player)
    with evaluation_mode(live):
        try:
            game = public_game(engine.new_game(story_id))
        except Exception as error:
            return {**record, "status": "error", "termination": "new_game", "errors": [safe_error(error)]}
        view = {"game": game, "turn": 0, "max_turns": max_turns, "clues": [], "events": [],
                "asks_left": game["kanshan"].get("asks_left", 5), "history": [], "last_error": None}
        for turn in range(1, max_turns + 1):
            view["turn"] = record["turns"] = turn
            attempt = None
            try:
                proposed = await player(deepcopy(view))
                try:
                    action = validate_action(proposed, view)
                except (ValueError, TypeError, KeyError):
                    record["attempts"].append({"turn": turn, "action": None, "status": "invalid"})
                    record["invalid_actions"] += 1
                    view["last_error"] = "动作无效，请只选择公开角色、已获证据和合法选项。"
                    if record["invalid_actions"] >= MAX_INVALID_ACTIONS:
                        record.update(status="error", termination="invalid_action_limit")
                        break
                    continue
                attempt = {"turn": turn, "action": deepcopy(action), "status": "pending"}
                record["attempts"].append(attempt)
                kind, game_id = action["action"], game["game_id"]
                if kind == "talk":
                    response = await engine.talk(game_id, action["character_id"], action["text"])
                elif kind == "show":
                    response = await engine.show(game_id, action["character_id"], action["clue_id"])
                elif kind == "ask":
                    response = await engine.ask(game_id, action["question"])
                else:
                    response = await engine.accuse(game_id, action["answers"])
                visible = public_result(kind, response)
                attempt["status"] = "success"
                entry = {"turn": turn, "action": action, "result": visible}
                record["history"].append(deepcopy(entry))
                view["history"].append(entry)
                view["last_error"] = None
                if kind in ("talk", "show"):
                    held = {clue["id"]: clue for clue in view["clues"]}
                    held.update({clue["id"]: clue for clue in visible["new_clues"]})
                    view["clues"] = list(held.values())
                    view["events"].extend(visible["events"])
                elif kind == "ask":
                    view["asks_left"] = visible["asks_left"]
                else:
                    record["ending"] = visible["ending"]
                    total, score = visible.get("total"), visible.get("score")
                    all_correct = type(total) is int and total > 0 and type(score) is int and score == total
                    if visible["ending"]["id"] == "truth" or all_correct:
                        record.update(status="success", termination="ending")
                        break
                    if visible["ending"]["retry"] is False:
                        record.update(status="failed", termination="non_retry_failure")
                        break
            except GameError as error:
                error_info = safe_error(error)
                record["errors"].append(error_info)
                if attempt is None:
                    attempt = {"turn": turn, "action": None}
                    record["attempts"].append(attempt)
                attempt.update(status="error", error=error_info)
                if error.status_code < 500:
                    record["invalid_actions"] += 1
                    view["last_error"] = "动作未被引擎接受，请根据现有信息换一个动作。"
                    if record["invalid_actions"] >= MAX_INVALID_ACTIONS:
                        record.update(status="error", termination="invalid_action_limit")
                        break
                else:
                    record.update(status="error", termination="engine_error")
                    break
            except Exception as error:
                error_info = safe_error(error)
                record["errors"].append(error_info)
                if attempt is None:
                    attempt = {"turn": turn, "action": None}
                    record["attempts"].append(attempt)
                attempt.update(status="error", error=error_info)
                record.update(status="timeout" if getattr(error, "status_code", None) == 504 else "error", termination="model_or_data_error")
                break
    if record["termination"] == "max_turns" and record["ending"] is not None:
        record.update(status="failed", termination="retry_ending_unresolved")
    return record


def summarize(records: list[dict]) -> dict:
    successful = [record for record in records if record["status"] == "success"]
    return {"runs": len(records), "success": len(successful),
        "failed": sum(record["status"] == "failed" for record in records),
        "error": sum(record["status"] == "error" for record in records),
        "timeout": sum(record["status"] == "timeout" for record in records),
        "success_rate": ratio(len(successful), len(records)),
        "average_success_turns": ratio(sum(record["turns"] for record in successful), len(successful))}


async def run_evaluation(engine, samples: list[dict], *, live=False, runs=1, max_turns=40, player=None) -> dict:
    if type(runs) is not int or runs <= 0:
        raise ValueError("runs 必须是正整数")
    if type(max_turns) is not int or max_turns <= 0:
        raise ValueError("max_turns 必须是正整数")
    report = base_report("play", live, engine)
    report.update({"max_turns": max_turns, "max_invalid_actions": MAX_INVALID_ACTIONS,
        "player": "actor_model_public_view" if live else "deterministic_public_strategy",
        "success_rule": SUCCESS_RULE,
        "failure_rule": "不可重试的非成功结局，或回合耗尽且仍是可重试结局记 failed；未提交过推理或模型超时记 timeout；接口与动作持续错误记 error",
        "denominators": {"success_rate": "success / runs；错误与超时保留在分母中",
        "average_success_turns": "成功对局回合数之和 / success；无成功时为 null"}, "records": [], "rows": []})
    for sample in samples:
        current = []
        for index in range(runs):
            record = await play_once(engine, sample["id"], live=live, max_turns=max_turns, player=player)
            current.append({"run": index + 1, "source": sample["source"], **record})
        report["records"].extend(current)
        report["rows"].append({"mode": report["mode"], "story_id": sample["id"], "source": sample["source"], **summarize(current)})
    report["summary"] = summarize(report["records"])
    return report


def main(argv=None) -> int:
    parser = common_parser("AI 玩家只用公开信息试玩已有生成剧本；默认模拟，真实调用需 --live。")
    parser.add_argument("--runs", type=positive_int, default=1)
    parser.add_argument("--max-turns", type=positive_int, default=40)
    args = parser.parse_args(argv)
    engine = GameEngine(args.stories_dir, args.generated_stories_dir)
    samples = select_samples(engine, args.story_id, generated_only=True)
    report = asyncio.run(run_evaluation(engine, samples, live=args.live, runs=args.runs, max_turns=args.max_turns))
    if not samples:
        report["message"] = "未找到现有生成剧本；请先由生成剧场产出样本，或用 --story-id 指定现有案件作验证。评测不会代写剧本。"
    paths = write_reports(report, args.output_dir, "play-test", ["mode", "story_id", "source", "runs", "success", "failed", "error", "timeout", "success_rate", "average_success_turns"])
    print(report.get("message", f"{report['mode']} 试玩评测完成，模拟策略结果只用于管线验证。" if not args.live else "live 试玩评测完成。"))
    print(f"JSON: {paths[0]}\nCSV: {paths[1]}")
    model_timeout = any(
        (record["status"] == "timeout" and record["termination"] == "model_or_data_error")
        or any(error.get("status_code") == 504 for error in record["errors"])
        for record in report["records"]
    )
    return 2 if not samples else (1 if report["summary"]["error"] or model_timeout else 0)


if __name__ == "__main__":
    raise SystemExit(main())
