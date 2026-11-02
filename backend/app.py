"""任务 02：游戏接口与前端静态文件入口。"""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.engine import GameEngine, GameError
from backend.llm import LLMError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewGameRequest(InputModel):
    story_id: str = Field(
        default="lost-tuition", min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )


class TalkRequest(InputModel):
    character_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)


class ShowRequest(InputModel):
    character_id: str = Field(min_length=1, max_length=80)
    clue_id: str = Field(min_length=1, max_length=80)


class AccuseRequest(InputModel):
    answers: dict[str, str] = Field(min_length=1, max_length=50)


class AskRequest(InputModel):
    question: str = Field(min_length=1, max_length=4000)


class StoryInfo(BaseModel):
    id: str
    title: str
    intro: str
    source: Literal["official", "generated"]
    characters: int


class KanshanInfo(BaseModel):
    greeting: str
    asks_left: int


class CharacterInfo(BaseModel):
    id: str
    name: str
    avatar: str
    profile: str


class QuestionInfo(BaseModel):
    id: str
    text: str
    options: list[str]


class NewGameResponse(BaseModel):
    game_id: str
    title: str
    intro: str
    characters: list[CharacterInfo]
    questions: list[QuestionInfo]
    kanshan: KanshanInfo


class ClueInfo(BaseModel):
    id: str
    title: str
    content: str


class EventLine(BaseModel):
    speaker: str
    text: str


class ConfrontEvent(BaseModel):
    type: Literal["confront"]
    text: str
    lines: list[EventLine]


class ExposedEvent(BaseModel):
    type: Literal["exposed"]
    character: str
    lie: str
    text: str


EventInfo = Annotated[ConfrontEvent | ExposedEvent, Field(discriminator="type")]


class TurnResponse(BaseModel):
    reply: str
    new_clues: list[ClueInfo]
    events: list[EventInfo]
    hint: str | None
    trust: dict[str, int]


class EndingInfo(BaseModel):
    id: str
    title: str
    text: str
    retry: bool


class EndingResponse(BaseModel):
    score: int
    total: int
    results: dict[str, bool]
    ending: EndingInfo
    rating: str


class RevealResponse(BaseModel):
    truth: str
    lessons: list[str]


class AskResponse(BaseModel):
    answer: Literal["是", "不是", "不重要"]
    asks_left: int


def create_app(
    *, stories_dir: Path | None = None, generated_stories_dir: Path | None = None,
    frontend_dir: Path | None = None
) -> FastAPI:
    """每个应用实例有独立的内存游戏；前端文件只从 frontend 目录提供。"""
    application = FastAPI(
        title="看山谜案馆 API",
        description="模拟模式可直接联调；游戏进度保存在当前服务进程内。",
        version="0.2.0",
    )
    engine = GameEngine(
        stories_dir=stories_dir or PROJECT_ROOT / "stories",
        generated_stories_dir=generated_stories_dir or PROJECT_ROOT / "data" / "stories",
    )
    application.state.engine = engine

    @application.exception_handler(GameError)
    async def game_error_handler(request: Request, error: GameError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": error.message})

    @application.exception_handler(LLMError)
    async def model_error_handler(request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    @application.get("/api/stories", response_model=list[StoryInfo])
    async def list_stories() -> list[dict]:
        return engine.list_stories()

    @application.post("/api/games", response_model=NewGameResponse, status_code=201)
    async def new_game(body: NewGameRequest) -> dict:
        return engine.new_game(body.story_id)

    @application.post("/api/games/{game_id}/talk", response_model=TurnResponse)
    async def talk(game_id: str, body: TalkRequest) -> dict:
        return await engine.talk(game_id, body.character_id, body.text)

    @application.post("/api/games/{game_id}/show", response_model=TurnResponse)
    async def show(game_id: str, body: ShowRequest) -> dict:
        return await engine.show(game_id, body.character_id, body.clue_id)

    @application.post("/api/games/{game_id}/accuse", response_model=EndingResponse)
    async def accuse(game_id: str, body: AccuseRequest) -> dict:
        return await engine.accuse(game_id, body.answers)

    @application.post("/api/games/{game_id}/ask", response_model=AskResponse)
    async def ask(game_id: str, body: AskRequest) -> dict:
        return await engine.ask(game_id, body.question)

    @application.post("/api/games/{game_id}/reveal", response_model=RevealResponse)
    async def reveal(game_id: str) -> dict:
        return await engine.reveal(game_id)

    static_dir = frontend_dir if frontend_dir is not None else PROJECT_ROOT / "frontend"
    static_files = StaticFiles(directory=static_dir, html=True, check_dir=False)

    @application.middleware("http")
    async def frontend_files(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        # API 始终交给路由；06 在应用创建后挂载生成剧场路由也能正常响应。
        if (
            response.status_code == 404 and request.method in {"GET", "HEAD"}
            and path != "/api" and not path.startswith("/api/")
            and static_dir.is_dir()
        ):
            try:
                return await static_files.get_response(path.lstrip("/"), request.scope)
            except StarletteHTTPException as error:
                if error.status_code != 404:
                    raise
        if response.status_code == 404 and path == "/" and request.method == "GET":
            return JSONResponse({
                "name": "看山谜案馆",
                "message": "后端已启动，可在 /docs 调试接口。前端接入后在此显示游戏。",
                "docs": "/docs",
            })
        return response

    return application


app = create_app()
