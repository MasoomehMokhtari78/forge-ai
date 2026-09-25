import sys

# On Windows, psycopg v3 async mode requires SelectorEventLoop
if sys.platform == "win32":
    import asyncio
    import selectors
    try:
        import uvicorn.loops.asyncio
        import uvicorn.loops.auto

        def _selector_loop_factory(use_subprocess: bool = False):
            return lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())

        uvicorn.loops.asyncio.asyncio_loop_factory = _selector_loop_factory
        uvicorn.loops.auto.auto_loop_factory = _selector_loop_factory
    except ImportError:
        pass

    class _SelectorPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self):
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    asyncio.set_event_loop_policy(_SelectorPolicy())


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import health, repositories

app = FastAPI(title=settings.project_name, version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(repositories.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

