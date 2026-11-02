"""生成剧场路由在静态文件之前挂载。"""

from contextlib import asynccontextmanager

from backend.studio.service import StudioService


def mount_studio(application):
    from backend.studio.api import router

    application.state.studio = StudioService()
    previous_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with previous_lifespan(app):
            try:
                yield
            finally:
                await app.state.studio.close()

    application.router.lifespan_context = lifespan
    application.include_router(router)
