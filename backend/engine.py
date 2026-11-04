"""剧本加载、事务回合、线索与谎话状态、结局判分。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import yaml
from backend import agents, kanshan
from backend.llm import LLMError
from backend.paths import data_root


class GameError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code, self.message = status_code, message


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
    turns: int = 0
    talk_counts: dict[str, int] = field(default_factory=dict)
    exposed_lies: set[str] = field(default_factory=set)
    asks_used: int = 0
    last_ending: dict[str, Any] | None = None
    revealed: bool = False
    hint_counts: dict[int, int] = field(default_factory=dict)

    @property
    def exposed(self) -> set[str]:
        """任务 13 读取的公开进度字段。"""
        return self.exposed_lies

    @property
    def ending(self) -> dict[str, Any] | None:
        """最近一次公开结局，供出题人进度页读取。"""
        return self.last_ending


class GameEngine:
    def __init__(self, stories_dir: Path | None = None, generated_stories_dir: Path | None = None):
        root = Path(__file__).resolve().parents[1]
        self.stories_dir = (Path(stories_dir) if stories_dir is not None else root / "stories").resolve()
        self.generated_stories_dir = (Path(generated_stories_dir) if generated_stories_dir is not None else data_root() / "stories").resolve()
        self.games: dict[str, GameState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def list_stories(self) -> list[dict]:
        result, seen = [], set()
        for directory, source in ((self.stories_dir, "official"), (self.generated_stories_dir, "generated")):
            for path in sorted(directory.glob("*.yaml")):
                if path.stem in seen or not self._valid_id(path.stem) or not path.resolve().is_relative_to(directory):
                    continue
                # 与开局的目录优先级一致，坏的招牌文件也不能被同编号生成文件遮盖。
                seen.add(path.stem)
                try:
                    story = self._read_story(path, path.stem, source)
                except GameError:
                    logging.getLogger(__name__).warning("跳过无法加载的剧本：%s", path.name)
                    continue
                quality = {"checked": story["checked"]} if type(story.get("checked")) is bool else {}
                # 首页「我的剧场」按生成时间排序，生成的剧本写完后不再改，修改时间就是生成时间。
                created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
                result.append({"id": story["id"], "title": story["title"], "intro": story["intro"], "source": story["source"],
                               "characters": len(story["characters"]), "created_at": created_at, **quality})
        return result

    def new_game(self, story_id: str) -> dict:
        story = self._load_story(story_id)
        game_id = uuid4().hex
        characters = story["characters"]
        self.games[game_id] = GameState(story=story,
            trust={c["id"]: c["trust_start"] for c in characters},
            histories={c["id"]: [] for c in characters}, shown={c["id"]: set() for c in characters},
            talk_counts={c["id"]: 0 for c in characters})
        self._locks[game_id] = asyncio.Lock()
        quality = {"checked": story["checked"]} if type(story.get("checked")) is bool else {}
        return {"game_id": game_id, "title": story["title"], "intro": story["intro"], **quality,
            "characters": [{k: c[k] for k in ("id", "name", "avatar", "profile")} for c in characters],
            "questions": [{k: deepcopy(q[k]) for k in ("id", "text", "options")} for q in story["ending"]["questions"]],
            "kanshan": {"greeting": story["kanshan"]["greeting"], "asks_left": 5}}

    async def talk(self, game_id: str, character_id: str, text: str) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise GameError(422, "请输入对话内容。")
        return await self._round(game_id, character_id, text, None)

    async def show(self, game_id: str, character_id: str, clue_id: str) -> dict:
        return await self._round(game_id, character_id, None, clue_id)

    async def ask(self, game_id: str, question: str) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise GameError(422, "请输入是非问题。")
        self._game(game_id)
        async with self._locks[game_id]:
            state = self._game(game_id)
            self._require_open(state)
            if state.asks_used >= 5:
                raise GameError(409, "本局的五次汤主问答已经用完。")
            answer = await self._call(kanshan.answer, deepcopy(state.story), question)
            if answer not in ("是", "不是", "不重要"):
                raise GameError(502, "汤主返回的内容格式有误，请重试。")
            state.asks_used += 1
            return {"answer": answer, "asks_left": 5 - state.asks_used}

    async def accuse(self, game_id: str, answers: dict[str, str]) -> dict:
        self._game(game_id)
        async with self._locks[game_id]:
            state = self._game(game_id)
            self._require_open(state)
            questions = state.story["ending"]["questions"]
            if not isinstance(answers, dict) or set(answers) != {q["id"] for q in questions}:
                raise GameError(422, "请完整回答所有题目，不要添加额外题目。")
            if any(not isinstance(answers[q["id"]], str) or answers[q["id"]] not in q["options"] for q in questions):
                raise GameError(422, "提交的答案必须来自对应题目的选项。")
            results = {q["id"]: answers[q["id"]] == q["answer"] for q in questions}
            chosen = next(e for e in state.story["ending"]["endings"] if self._ending_matches(e, answers, results))
            ending = {k: deepcopy(chosen[k]) for k in ("id", "title", "text", "retry")}
            score, total = sum(results.values()), len(questions)
            state.last_ending = deepcopy(ending)
            state.finished = not ending["retry"]
            return {"score": score, "total": total, "results": results, "ending": ending,
                "rating": self._rating(score, total, state.turns, state.asks_used)}

    async def reveal(self, game_id: str) -> dict:
        self._game(game_id)
        async with self._locks[game_id]:
            state = self._game(game_id)
            if state.last_ending is None:
                raise GameError(409, "请先提交一次推理，再揭晓汤底。")
            if state.revealed:
                raise GameError(409, "本局汤底已经揭晓。")
            state.revealed = state.finished = True
            return {"truth": state.story["ending"]["truth"], "lessons": deepcopy(state.story["ending"]["lessons"])}

    @staticmethod
    def _ending_matches(ending, answers, results):
        when = ending.get("when")
        if not when:
            return True
        if "correct" in when:
            return all(results[q] for q in when["correct"])
        return all(answers[q] == option for q, option in when["chose"].items())

    @staticmethod
    def _rating(score, total, turns, asks_used):
        if score == total and turns <= 20 and asks_used <= 2:
            return "S"
        if score * 100 >= total * 80:
            return "A"
        return "B" if score * 100 >= total * 60 else "C"

    async def _round(self, game_id, character_id, text, clue_id):
        self._game(game_id)
        async with self._locks[game_id]:
            original = self._game(game_id)
            self._require_open(original)
            if character_id not in original.trust:
                raise GameError(404, "没有这个角色。")
            state = deepcopy(original)
            exposed_before = set(state.exposed_lies)
            shown_clue, events, pending, queued = None, [], [], set()
            if clue_id is not None:
                clues = {c["id"]: c for c in state.story["clues"]}
                if clue_id not in clues:
                    raise GameError(404, "没有这条线索。")
                if clue_id not in state.acquired_clues:
                    raise GameError(409, "先取得这条线索，才能向角色出示。")
                shown_clue = self._public_clue(clues[clue_id])
                state.shown[character_id].add(clue_id)
                text = f"我向你出示线索《{shown_clue['title']}》：{shown_clue['content']}"
                events.extend(self._expose(state))
                pending.extend(self._queue_events(state, queued))
            context = self._context(state, character_id, text, shown_clue)
            candidate = await self._checked_reply(context)
            allowed = {c["id"] for c in context["available_clues"]}
            reveal = [cid for cid in candidate["reveal"] if cid in allowed]
            if not reveal and context["available_clues"]:
                clue = context["available_clues"][0]
                reveal = [clue["id"]]
                handoff = f"这份《{clue['title']}》可以交给你，请收好。"
                reply = handoff if candidate.get("_fallback") else f"{candidate['reply']}\n{handoff}"
                candidate = {**candidate, "reply": reply, "reveal": reveal}
            new_clues = self._grant(state, reveal, force=False)
            state.trust[character_id] = max(0, min(3, state.trust[character_id] + max(-1, min(1, candidate["trust_delta"]))))
            history_reply = candidate["reply"]
            if new_clues:
                evidence = "\n".join(f"《{clue['title']}》：{clue['content']}" for clue in new_clues)
                history_reply += "\n已交付证据：\n" + evidence
            state.histories[character_id].extend([{"role": "user", "content": text}, {"role": "assistant", "content": history_reply}])
            state.turns += 1
            if clue_id is None:
                state.talk_counts[character_id] += 1
            events.extend(self._expose(state))
            pending.extend(self._queue_events(state, queued))
            # 对质上下文临时开放事件将解锁的承认事实；公开拆穿反馈在对质之后。
            for event in pending:
                projected = deepcopy(state)
                projected.triggered_events.add(event["id"])
                self._expose(projected)
                public_event = await self._confront(state, event, shown_clue, context_state=projected)
                events.append(public_event)
                state.triggered_events.add(event["id"])
                new_clues.extend(self._grant(state, event["unlock"], force=True))
                events.extend(self._expose(state))
                pending.extend(self._queue_events(state, queued))
            events.extend(self._expose(state))
            newly_exposed = state.exposed_lies - exposed_before
            for character in state.story["characters"]:
                cid = character["id"]
                if cid == character_id and candidate.get("_fallback"):
                    continue
                state.trust[cid] = min(3, state.trust[cid] + sum(l["id"] in newly_exposed for l in character["lies"]))
                if state.talk_counts[cid] >= 4:
                    state.trust[cid] = max(1, state.trust[cid])
            state.event_log.extend(deepcopy(events))
            state.idle_turns = 0 if new_clues else state.idle_turns + 1
            hint = None
            if state.idle_turns >= 3:
                hint = self._next_hint(state)
                state.idle_turns = 0
            self.games[game_id] = state
            return {"reply": candidate["reply"], "new_clues": new_clues, "events": events, "hint": hint, "trust": dict(state.trust)}

    def _expose(self, state):
        events, changed = [], True
        while changed:
            changed = False
            for character in state.story["characters"]:
                for lie in character["lies"]:
                    if lie["id"] not in state.exposed_lies and self._condition(state, character["id"], lie["until"]):
                        state.exposed_lies.add(lie["id"])
                        admission = next(f["text"] for f in state.story["facts"] if f["id"] == lie["admit"])
                        events.append({"type": "exposed", "character": character["id"], "lie": lie["id"], "text": f"{character['name']}的说法被拆穿了。已确认：{admission}"})
                        changed = True
        return events

    def _queue_events(self, state, queued):
        result = []
        for event in state.story["events"]:
            if event["id"] in state.triggered_events or event["id"] in queued:
                continue
            when = event["when"]
            if self._condition(state, when["to"], {k: v for k, v in when.items() if k != "to"}):
                queued.add(event["id"])
                result.append(event)
        return result

    def _next_hint(self, state):
        if state.story.get("source") == "generated" and not state.story.get("hints"):
            return self._generated_hint(state)
        stages = state.story["kanshan"]["hints"]
        for index, stage in enumerate(stages):
            if self._condition(state, None, stage["done"]):
                continue
            count = state.hint_counts.get(index, 0)
            state.hint_counts[index] = count + 1
            return stage["vague"] if count == 0 else stage["direct"]
        if stages:
            return None
        legacy = state.story.get("hints", [])
        if state.hint_index < len(legacy):
            text = legacy[state.hint_index]["text"]
            state.hint_index += 1
            return text
        return None

    def _generated_hint(self, state):
        characters = {c["id"]: c["name"] for c in state.story["characters"]}
        clues = {c["id"]: c for c in state.story["clues"]}
        if set(clues) <= state.acquired_clues:
            return "线索已经收齐，可以整理证据并提交推理。"
        for character_id, name in characters.items():
            available = self._context(state, character_id, "")["available_clues"]
            if available:
                return f"向{name}询问《{available[0]['title']}》，这份材料现在可以交给你。"

        event_rewards = {cid for event in state.story["events"] for cid in event["unlock"]}
        conditions = [(c["holder"], c.get("requires", {})) for c in clues.values()
                      if c["id"] not in state.acquired_clues and c["id"] not in event_rewards]
        conditions.extend((c["id"], lie["until"]) for c in state.story["characters"]
                          for lie in c["lies"] if lie["id"] not in state.exposed_lies)
        conditions.extend((event["when"]["to"], {k: v for k, v in event["when"].items() if k != "to"})
                          for event in state.story["events"] if event["id"] not in state.triggered_events)
        for character_id, condition in conditions:
            clue_id = condition.get("shown")
            if clue_id in state.acquired_clues and clue_id not in state.shown[character_id]:
                return f"把已获得的《{clues[clue_id]['title']}》出示给{characters[character_id]}，再听听对方的说明。"
        for character_id, condition in conditions:
            if "trust" in condition and state.trust[character_id] < condition["trust"]:
                remaining = {k: v for k, v in condition.items() if k != "trust"}
                if self._condition(state, character_id, remaining):
                    return f"继续和{characters[character_id]}交流，建立信任后再询问可公开的材料。"
        return "可以继续询问其他角色，把已经获得的证据和各人的说法对照起来。"

    def _context(self, state, character_id, player_text, shown_clue=None):
        character = next(c for c in state.story["characters"] if c["id"] == character_id)
        blocked = {s["fact"] for s in character["secrets"] if not self._condition(state, character_id, s["until"])}
        blocked.update(l["admit"] for l in character["lies"] if l["id"] not in state.exposed_lies)
        admitted = {l["admit"] for l in character["lies"] if l["id"] in state.exposed_lies}
        allowed = (set(character["knows"]) - blocked) | admitted
        facts = {f["id"]: deepcopy(f) for f in state.story["facts"]}
        admit_owners = {}
        for owner in state.story["characters"]:
            for lie in owner["lies"]:
                admit_owners.setdefault(lie["admit"], {})[owner["id"]] = {
                    "id": owner["id"], "name": owner["name"],
                }
        for fact_id, fact in facts.items():
            owners = admit_owners.get(fact_id, {})
            if "我" in fact["text"] and len(owners) == 1 and not any(mark in fact["text"] for mark in "“”‘’\"'"):
                fact["first_person_subject"] = deepcopy(next(iter(owners.values())))
        active, exposed, future = [], [], []
        for lie in character["lies"]:
            public = {k: lie[k] for k in ("id", "claim")}
            if lie["id"] in state.exposed_lies:
                exposed.append({**public, "admit": deepcopy(facts[lie["admit"]])})
            elif "exposed" in lie["until"] and lie["until"]["exposed"] not in state.exposed_lies:
                future.append(public)
            else:
                active.append(public)
        event_rewards = {cid for event in state.story["events"] for cid in event["unlock"]}
        return {"character": {k: character[k] for k in ("id", "name", "profile", "persona")},
            "facts": [deepcopy(f) for f in facts.values() if f["id"] in allowed],
            "forbidden_facts": [deepcopy(f) for f in facts.values() if f["id"] not in allowed],
            "available_clues": [self._public_clue(c) for c in state.story["clues"] if c["holder"] == character_id and c["id"] not in state.acquired_clues and c["id"] not in event_rewards and self._condition(state, character_id, c.get("requires"))],
            "active_lies": active, "exposed_lies": exposed, "future_lies": future,
            "history": deepcopy(state.histories[character_id]), "trust": state.trust[character_id],
            "player_text": player_text, "shown_clue": deepcopy(shown_clue)}

    async def _checked_reply(self, context, initial=None):
        if initial == agents.evasive_reply(context):
            return initial
        retry_leaked = None
        context = deepcopy(context)
        for attempt in range(2):
            candidate = initial if attempt == 0 and initial is not None else await self._call(agents.reply, deepcopy(context), retry_leaked=retry_leaked)
            if (not isinstance(candidate, dict) or not isinstance(candidate.get("reply"), str) or not candidate["reply"].strip()
                or not isinstance(candidate.get("reveal"), list) or any(not isinstance(c, str) for c in candidate["reveal"])
                or type(candidate.get("trust_delta")) is not int):
                raise GameError(502, "角色返回的内容格式有误，请重试。")
            check = await self._call(agents.check_reply, deepcopy(context), deepcopy(candidate))
            if (not isinstance(check, dict) or type(check.get("ok")) is not bool or not isinstance(check.get("leaked"), list)
                or any(not isinstance(f, str) for f in check["leaked"]) or not isinstance(check.get("contradiction", ""), str)):
                raise GameError(502, "核查返回的内容格式有误，请重试。")
            if check["ok"]:
                return candidate
            retry_leaked = check["leaked"]
            context["check_feedback"] = check.get("contradiction", "")
        return {**agents.evasive_reply(context), "_fallback": True}

    async def _confront(self, state, event, shown_clue, *, context_state=None):
        source = context_state if context_state is not None else state
        contexts = [self._context(source, cid, "请以自己的身份回应这次对质，只谈自己知道且现在可以公开的事实。", shown_clue if shown_clue is not None and shown_clue["id"] in source.shown[cid] else None) for cid in event["confront"]]
        lines = await self._call(agents.confront, deepcopy(contexts), deepcopy(event))
        if (not isinstance(lines, list) or len(lines) != 2
            or any(not isinstance(line, dict) or line.get("speaker") not in event["confront"] or not isinstance(line.get("text"), str) or not line["text"].strip() for line in lines)
            or {line["speaker"] for line in lines} != set(event["confront"])):
            raise GameError(502, "对质返回的内容格式有误，请重试。")
        contexts = {c["character"]["id"]: c for c in contexts}
        checked = []
        for line in lines:
            candidate = await self._checked_reply(contexts[line["speaker"]], {"reply": line["text"], "reveal": [], "trust_delta": 0})
            checked.append({"speaker": line["speaker"], "text": candidate["reply"]})
        names = {c["id"]: c["name"] for c in state.story["characters"]}
        for cid in event["confront"]:
            for line in checked:
                state.histories[cid].append({"role": "assistant" if cid == line["speaker"] else "user", "content": f"【对质·{names[line['speaker']]}】{line['text']}"})
        return {"type": "confront", "text": f"{names[event['confront'][0]]}和{names[event['confront'][1]]}围绕证据展开对质。", "lines": checked}

    @staticmethod
    async def _call(function, *args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except LLMError:
            raise
        except Exception as exc:
            raise GameError(502, "角色服务暂时不可用，请稍后重试。") from exc

    @staticmethod
    def _condition(state, character_id, condition):
        for key, value in (condition or {}).items():
            if key == "trust" and (character_id is None or state.trust[character_id] < value):
                return False
            if key == "shown" and (character_id is None or value not in state.shown[character_id]):
                return False
            if key == "has" and value not in state.acquired_clues:
                return False
            if key == "exposed" and value not in state.exposed_lies:
                return False
            if key == "event" and value not in state.triggered_events:
                return False
        return True

    def _grant(self, state, clue_ids, *, force=False):
        clues = {c["id"]: c for c in state.story["clues"]}
        granted = []
        for clue_id in clue_ids:
            clue = clues[clue_id]
            if clue_id not in state.acquired_clues and (force or self._condition(state, clue["holder"], clue.get("requires"))):
                state.acquired_clues.add(clue_id)
                granted.append(self._public_clue(clue))
        return granted

    @staticmethod
    def _public_clue(clue):
        return {key: clue[key] for key in ("id", "title", "content")}

    def _game(self, game_id):
        if game_id not in self.games:
            raise GameError(404, "找不到这局游戏，请重新开始。")
        return self.games[game_id]

    @staticmethod
    def _require_open(state):
        if state.finished:
            raise GameError(409, "这局游戏已经结束，请开始新的一局。")

    @staticmethod
    def _valid_id(value):
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value) is not None

    def _load_story(self, story_id):
        if not self._valid_id(story_id):
            raise GameError(400, "剧本编号格式有误。")
        for directory, source in ((self.stories_dir, "official"), (self.generated_stories_dir, "generated")):
            path = (directory / f"{story_id}.yaml").resolve()
            if not path.is_relative_to(directory):
                raise GameError(400, "剧本路径有误。")
            if path.is_file():
                return self._read_story(path, story_id, source)
        raise GameError(404, "没有这个剧本。")

    def _read_story(self, path, story_id, source):
        try:
            story = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise GameError(500, "剧本文件无法读取，请联系开发者。") from exc
        try:
            self._validate_story(story, story_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise GameError(500, "剧本数据格式有误，请联系开发者。") from exc
        story["source"] = source
        for character in story["characters"]:
            character.setdefault("secrets", [])
            character.setdefault("lies", [])
            character.setdefault("trust_start", 0)
        story.setdefault("kanshan", {"greeting": "我是看山，你的调查搭档。", "hints": []})
        ending = story["ending"]
        ending.setdefault("lessons", [])
        ending.setdefault("endings", [{"id": "complete", "title": "调查结束", "text": "调查结果已记录，可以揭晓汤底查看完整真相。", "retry": False}])
        for outcome in ending["endings"]:
            outcome.setdefault("retry", False)
        return story

    @staticmethod
    def _validate_story(story, story_id):
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
            result = {item["id"] for item in items}
            require(len(result) == len(items))
            return result

        texts(story, ("id", "title", "intro"))
        require(story["id"] == story_id)
        require(story.get("source", "official") in ("official", "generated"))
        fact_ids, char_ids = records(story["facts"]), records(story["characters"])
        clue_ids, event_ids = records(story["clues"]), records(story["events"])
        lies = [lie for character in story["characters"] for lie in character.get("lies", [])]
        lie_ids = records(lies)
        ending = story["ending"]
        questions = ending["questions"]
        question_ids = records(questions)
        require(bool(char_ids) and bool(questions))

        def condition(value, *, scoped=True):
            require(isinstance(value, dict))
            require(set(value) <= {"trust", "shown", "has", "exposed", "event"})
            if not scoped:
                require(not ({"trust", "shown"} & set(value)))
            for key, target in value.items():
                if key == "trust":
                    require(type(target) is int and 0 <= target <= 3)
                else:
                    refs = {"shown": clue_ids, "has": clue_ids, "exposed": lie_ids, "event": event_ids}[key]
                    require(isinstance(target, str) and target in refs)

        for fact in story["facts"]:
            texts(fact, ("text",))
        for character in story["characters"]:
            texts(character, ("name", "avatar", "profile", "persona"))
            require(isinstance(character["knows"], list) and all(isinstance(f, str) and f in fact_ids for f in character["knows"]))
            require(type(character.get("trust_start", 0)) is int and 0 <= character.get("trust_start", 0) <= 3)
            require(isinstance(character.get("secrets", []), list) and isinstance(character.get("lies", []), list))
            for secret in character.get("secrets", []):
                require(isinstance(secret, dict) and isinstance(secret.get("fact"), str) and secret["fact"] in character["knows"])
                condition(secret["until"])
            for lie in character.get("lies", []):
                texts(lie, ("claim", "admit"))
                require(lie["admit"] in character["knows"])
                condition(lie["until"])
        for clue in story["clues"]:
            texts(clue, ("title", "content", "holder"))
            require(clue["holder"] in char_ids)
            if "requires" in clue:
                condition(clue["requires"])
        for event in story["events"]:
            require(isinstance(event["when"], dict) and isinstance(event["when"].get("to"), str))
            require(event["when"]["to"] in char_ids)
            condition({k: v for k, v in event["when"].items() if k != "to"})
            require(isinstance(event["confront"], list) and len(event["confront"]) == 2)
            require(all(isinstance(cid, str) and cid in char_ids for cid in event["confront"]))
            require(len(set(event["confront"])) == 2)
            require(isinstance(event["unlock"], list) and all(isinstance(cid, str) and cid in clue_ids for cid in event["unlock"]))
        if "kanshan" in story:
            texts(story["kanshan"], ("greeting",))
            require(isinstance(story["kanshan"]["hints"], list))
            for hint in story["kanshan"]["hints"]:
                texts(hint, ("vague", "direct"))
                condition(hint["done"], scoped=False)
        else:
            require(isinstance(story.get("hints", []), list))
            for hint in story.get("hints", []):
                texts(hint, ("text",))
        texts(ending, ("truth",))
        require(isinstance(ending.get("lessons", []), list))
        require(all(isinstance(text, str) and text.strip() for text in ending.get("lessons", [])))
        for question in questions:
            texts(question, ("text", "answer"))
            require(isinstance(question["options"], list) and len(question["options"]) >= 2)
            require(all(isinstance(option, str) and option.strip() for option in question["options"]))
            require(len(set(question["options"])) == len(question["options"]))
            require(question["answer"] in question["options"])
        if "endings" in ending:
            records(ending["endings"])
            require(bool(ending["endings"]) and any(not outcome.get("when") for outcome in ending["endings"]))
            for outcome in ending["endings"]:
                texts(outcome, ("title", "text"))
                require(type(outcome.get("retry", False)) is bool)
                when = outcome.get("when", {})
                require(isinstance(when, dict) and set(when) in (set(), {"correct"}, {"chose"}))
                if "correct" in when:
                    require(isinstance(when["correct"], list) and bool(when["correct"]))
                    require(all(isinstance(qid, str) and qid in question_ids for qid in when["correct"]))
                if "chose" in when:
                    require(isinstance(when["chose"], dict) and bool(when["chose"]))
                    by_id = {question["id"]: question for question in questions}
                    require(all(qid in question_ids and isinstance(option, str) and option in by_id[qid]["options"] for qid, option in when["chose"].items()))
