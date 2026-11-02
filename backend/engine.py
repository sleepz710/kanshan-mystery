"""剧本加载、回合事务、线索权限与结局判分。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import yaml

from backend import agents
from backend.llm import LLMError


class GameError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class GameState:
    story: dict[str, Any]
    trust: dict[str, int]
    histories: dict[str, list[dict[str, str]]]
    shown: dict[str, set[str]]
    acquired_clues: set[str] = field(default_factory=set)
    triggered_events: set[str] = field(default_factory=set)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    idle_turns: int = 0
    hint_index: int = 0
    finished: bool = False


class GameEngine:
    def __init__(self, stories_dir: Path | None = None):
        self.stories_dir = (
            Path(stories_dir) if stories_dir is not None
            else Path(__file__).resolve().parents[1] / "stories"
        ).resolve()
        self.games: dict[str, GameState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def new_game(self, story_id: str) -> dict[str, Any]:
        story = self._load_story(story_id)
        characters = story["characters"]
        game_id = uuid4().hex
        self.games[game_id] = GameState(
            story=story,
            trust={c["id"]: c.get("trust_start", 0) for c in characters},
            histories={c["id"]: [] for c in characters},
            shown={c["id"]: set() for c in characters},
        )
        self._locks[game_id] = asyncio.Lock()
        return {
            "game_id": game_id,
            "title": story["title"],
            "intro": story["intro"],
            "characters": [
                {key: c[key] for key in ("id", "name", "avatar", "profile")}
                for c in characters
            ],
            "questions": [
                {key: deepcopy(q[key]) for key in ("id", "text", "options")}
                for q in story["ending"]["questions"]
            ],
        }

    async def talk(self, game_id: str, character_id: str, text: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise GameError(422, "请输入对话内容。")
        return await self._round(game_id, character_id, text, None)

    async def show(self, game_id: str, character_id: str, clue_id: str) -> dict[str, Any]:
        return await self._round(game_id, character_id, None, clue_id)

    async def accuse(self, game_id: str, answers: dict[str, str]) -> dict[str, Any]:
        self._game(game_id)
        async with self._locks[game_id]:
            state = self._game(game_id)
            self._require_open(state)
            ending = state.story["ending"]
            questions = ending["questions"]
            if not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions}:
                raise GameError(422, "请完整回答所有题目，不要添加额外题目。")
            if any(not isinstance(answers[q["id"]], str) or answers[q["id"]] not in q["options"] for q in questions):
                raise GameError(422, "提交的答案必须来自对应题目的选项。")
            results = {q["id"]: answers[q["id"]] == q["answer"] for q in questions}
            state.finished = True
            return {
                "score": sum(results.values()),
                "total": len(questions),
                "results": results,
                "truth": ending["truth"],
                "lessons": deepcopy(ending["lessons"]),
            }

    async def _round(self, game_id: str, character_id: str, text: str | None, clue_id: str | None) -> dict[str, Any]:
        self._game(game_id)
        async with self._locks[game_id]:
            original = self._game(game_id)
            self._require_open(original)
            characters = {c["id"]: c for c in original.story["characters"]}
            if character_id not in characters:
                raise GameError(404, "没有这个角色。")
            # 所有写入都发生在副本上；外部调用失败或被取消时保留原状态。
            state = deepcopy(original)
            shown_clue = None
            if clue_id is not None:
                clues = {c["id"]: c for c in state.story["clues"]}
                if clue_id not in clues:
                    raise GameError(404, "没有这条线索。")
                if clue_id not in state.acquired_clues:
                    raise GameError(409, "先取得这条线索，才能向角色出示。")
                shown_clue = self._public_clue(clues[clue_id])
                state.shown[character_id].add(clue_id)
                text = f"我向你出示线索《{shown_clue['title']}》：{shown_clue['content']}"
            context = self._context(state, character_id, text, shown_clue)
            candidate = await self._checked_reply(context)
            allowed = {c["id"] for c in context["available_clues"]}
            new_clues = self._grant(state, [c for c in candidate["reveal"] if c in allowed])
            state.trust[character_id] = max(0, state.trust[character_id] + max(-1, min(1, candidate["trust_delta"])))
            state.histories[character_id].extend([
                {"role": "user", "content": text},
                {"role": "assistant", "content": candidate["reply"]},
            ])

            events = []
            if shown_clue is not None:
                for event in state.story["events"]:
                    if event["id"] in state.triggered_events or event["when"] != {"shown": clue_id, "to": character_id}:
                        continue
                    public_event = await self._confront(state, event, shown_clue)
                    events.append(public_event)
                    state.event_log.append(public_event)
                    state.triggered_events.add(event["id"])
                    # 事件奖励只在对质完成后发放，并按持有人条件再次检查。
                    new_clues.extend(self._grant(state, event["unlock"]))

            hint = None
            state.idle_turns = 0 if new_clues else state.idle_turns + 1
            if state.idle_turns >= 3:
                hints = state.story["hints"]
                if state.hint_index < len(hints):
                    hint = hints[state.hint_index]["text"]
                    state.hint_index += 1
                state.idle_turns = 0
            self.games[game_id] = state
            return {
                "reply": candidate["reply"],
                "new_clues": new_clues,
                "events": deepcopy(events),
                "hint": hint,
                "trust": dict(state.trust),
            }

    def _context(self, state: GameState, character_id: str, player_text: str, shown_clue: dict | None = None) -> dict[str, Any]:
        character = next(c for c in state.story["characters"] if c["id"] == character_id)
        blocked = {s["fact"] for s in character.get("secrets", []) if not self._condition(state, character_id, s["until"])}
        allowed = set(character["knows"]) - blocked
        # 写在事件 unlock 中的线索，在事件完成前不允许角色提前交出。
        pending = {clue_id for e in state.story["events"] if e["id"] not in state.triggered_events for clue_id in e["unlock"]}
        return {
            "character": {key: character[key] for key in ("id", "name", "profile", "persona")},
            "facts": [deepcopy(f) for f in state.story["facts"] if f["id"] in allowed],
            "forbidden_facts": [deepcopy(f) for f in state.story["facts"] if f["id"] not in allowed],
            "available_clues": [
                self._public_clue(c) for c in state.story["clues"]
                if c["holder"] == character_id and c["id"] not in state.acquired_clues
                and c["id"] not in pending and self._condition(state, character_id, c.get("requires"))
            ],
            "history": deepcopy(state.histories[character_id]),
            "trust": state.trust[character_id],
            "player_text": player_text,
            "shown_clue": deepcopy(shown_clue),
        }

    async def _checked_reply(self, context: dict, initial: dict | None = None) -> dict:
        retry_leaked = None
        for attempt in range(2):
            if attempt == 0 and initial is not None:
                candidate = initial
            else:
                candidate = await self._call(agents.reply, deepcopy(context), retry_leaked=retry_leaked)
            if (
                not isinstance(candidate, dict)
                or not isinstance(candidate.get("reply"), str) or not candidate["reply"].strip()
                or not isinstance(candidate.get("reveal"), list)
                or any(not isinstance(c, str) for c in candidate["reveal"])
                or type(candidate.get("trust_delta")) is not int
            ):
                raise GameError(502, "角色返回的内容格式有误，请重试。")
            check = await self._call(agents.check_reply, deepcopy(context), deepcopy(candidate))
            if (
                not isinstance(check, dict) or type(check.get("ok")) is not bool
                or not isinstance(check.get("leaked"), list)
                or any(not isinstance(f, str) for f in check["leaked"])
            ):
                raise GameError(502, "核查返回的内容格式有误，请重试。")
            if check["ok"]:
                return candidate
            retry_leaked = check["leaked"]
        raise GameError(502, "角色回复未通过核查，请重新提问。")

    async def _confront(self, state: GameState, event: dict, shown_clue: dict) -> dict:
        contexts = [
            self._context(
                state, cid, "请以自己的身份回应这次对质，只谈自己知道且现在可以公开的事实。",
                shown_clue if shown_clue["id"] in state.shown[cid] else None,
            ) for cid in event["confront"]
        ]
        lines = await self._call(agents.confront, deepcopy(contexts), deepcopy(event))
        if (
            not isinstance(lines, list) or len(lines) != 2
            or any(not isinstance(line, dict) or line.get("speaker") not in event["confront"]
                   or not isinstance(line.get("text"), str) or not line["text"].strip() for line in lines)
            or {line["speaker"] for line in lines} != set(event["confront"])
        ):
            raise GameError(502, "对质返回的内容格式有误，请重试。")
        context_by_id = {c["character"]["id"]: c for c in contexts}
        checked_lines = []
        for line in lines:
            candidate = await self._checked_reply(context_by_id[line["speaker"]], {
                "reply": line["text"], "reveal": [], "trust_delta": 0,
            })
            checked_lines.append({"speaker": line["speaker"], "text": candidate["reply"]})
        names = {c["id"]: c["name"] for c in state.story["characters"]}
        for cid in event["confront"]:
            for line in checked_lines:
                state.histories[cid].append({
                    "role": "assistant" if cid == line["speaker"] else "user",
                    "content": f"【对质·{names[line['speaker']]}】{line['text']}",
                })
        return {
            "type": "confront",
            "text": f"{names[event['confront'][0]]}和{names[event['confront'][1]]}围绕证据展开对质。",
            "lines": checked_lines,
        }

    @staticmethod
    async def _call(function, *args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except LLMError:
            raise
        except Exception as exc:
            raise GameError(502, "角色服务暂时不可用，请稍后重试。") from exc

    @staticmethod
    def _condition(state: GameState, character_id: str, condition: dict | None) -> bool:
        if not condition:
            return True
        if "trust" in condition:
            return state.trust[character_id] >= condition["trust"]
        return condition["shown"] in state.shown[character_id]

    def _grant(self, state: GameState, clue_ids: list[str]) -> list[dict]:
        clues = {c["id"]: c for c in state.story["clues"]}
        granted = []
        for clue_id in clue_ids:
            clue = clues[clue_id]
            if clue_id not in state.acquired_clues and self._condition(state, clue["holder"], clue.get("requires")):
                state.acquired_clues.add(clue_id)
                granted.append(self._public_clue(clue))
        return granted

    @staticmethod
    def _public_clue(clue: dict) -> dict:
        return {key: clue[key] for key in ("id", "title", "content")}

    def _game(self, game_id: str) -> GameState:
        if game_id not in self.games:
            raise GameError(404, "找不到这局游戏，请重新开始。")
        return self.games[game_id]

    @staticmethod
    def _require_open(state: GameState):
        if state.finished:
            raise GameError(409, "这局游戏已经结束，请开始新的一局。")

    def _load_story(self, story_id: str) -> dict:
        if not isinstance(story_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", story_id) is None:
            raise GameError(400, "剧本编号格式有误。")
        path = (self.stories_dir / f"{story_id}.yaml").resolve()
        if not path.is_relative_to(self.stories_dir):
            raise GameError(400, "剧本路径有误。")
        try:
            story = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GameError(404, "没有这个剧本。") from exc
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise GameError(500, "剧本文件无法读取，请联系开发者。") from exc
        try:
            self._validate_story(story, story_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise GameError(500, "剧本数据格式有误，请联系开发者。") from exc
        return story

    @staticmethod
    def _validate_story(story: dict, story_id: str):
        def require(ok):
            if not ok:
                raise ValueError("剧本字段或引用不符合 SPEC")

        def texts(item, keys):
            require(isinstance(item, dict))
            require(all(isinstance(item.get(k), str) and item[k].strip() for k in keys))

        def records(items):
            require(isinstance(items, list))
            for item in items:
                texts(item, ("id",))
            ids = {item["id"] for item in items}
            require(len(ids) == len(items))
            return ids

        texts(story, ("id", "title", "intro"))
        require(story["id"] == story_id)
        fact_ids = records(story["facts"])
        char_ids = records(story["characters"])
        clue_ids = records(story["clues"])
        records(story["events"])
        questions = story["ending"]["questions"]
        records(questions)
        require(bool(char_ids) and bool(questions))

        def condition(value):
            require(isinstance(value, dict))
            require(set(value) in ({"trust"}, {"shown"}))
            if "trust" in value:
                require(type(value["trust"]) is int and value["trust"] >= 0)
            else:
                require(isinstance(value["shown"], str) and value["shown"] in clue_ids)

        for fact in story["facts"]:
            texts(fact, ("text",))
        for char in story["characters"]:
            texts(char, ("name", "avatar", "profile", "persona"))
            require(isinstance(char["knows"], list) and all(isinstance(f, str) and f in fact_ids for f in char["knows"]))
            require(type(char.get("trust_start", 0)) is int and char.get("trust_start", 0) >= 0)
            require(isinstance(char.get("secrets", []), list))
            for secret in char.get("secrets", []):
                require(isinstance(secret, dict) and isinstance(secret.get("fact"), str) and secret["fact"] in char["knows"])
                condition(secret["until"])
        for clue in story["clues"]:
            texts(clue, ("title", "content", "holder"))
            require(clue["holder"] in char_ids)
            if "requires" in clue:
                condition(clue["requires"])
        for event in story["events"]:
            require(isinstance(event["when"], dict) and set(event["when"]) == {"shown", "to"})
            require(event["when"]["shown"] in clue_ids and event["when"]["to"] in char_ids)
            require(isinstance(event["confront"], list) and len(event["confront"]) == 2)
            require(all(isinstance(c, str) and c in char_ids for c in event["confront"]))
            require(len(set(event["confront"])) == 2)
            require(isinstance(event["unlock"], list) and all(isinstance(c, str) and c in clue_ids for c in event["unlock"]))
        require(isinstance(story["hints"], list))
        for hint in story["hints"]:
            texts(hint, ("text",))
        texts(story["ending"], ("truth",))
        require(isinstance(story["ending"]["lessons"], list))
        require(all(isinstance(text, str) and text.strip() for text in story["ending"]["lessons"]))
        for question in questions:
            texts(question, ("text", "answer"))
            require(isinstance(question["options"], list) and len(question["options"]) >= 2)
            require(all(isinstance(option, str) and option.strip() for option in question["options"]))
            require(len(set(question["options"])) == len(question["options"]))
            require(question["answer"] in question["options"])
