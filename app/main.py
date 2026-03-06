from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine, Base
from app.routers.auth import router as auth_router
from app.routers.lists import router as lists_router
from app.routers.receipts import router as receipts_router
from app.routers.ws import router as ws_router, members_router
from app.routers.other import prices_router, expenses_router, budget_router, smart_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth_router,     prefix=API_PREFIX)
app.include_router(lists_router,    prefix=API_PREFIX)
app.include_router(receipts_router, prefix=API_PREFIX)
app.include_router(prices_router,   prefix=API_PREFIX)
app.include_router(expenses_router, prefix=API_PREFIX)
app.include_router(budget_router,   prefix=API_PREFIX)
app.include_router(smart_router,    prefix=API_PREFIX)
app.include_router(members_router,  prefix=API_PREFIX)
app.include_router(ws_router)  # WebSocket — /ws/lists/{list_id}


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}

@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "docs": "/docs"}
# Note: add these imports at top of main.py:
# from app.routers.users import router as users_router
# app.include_router(users_router, prefix=API_PREFIX)
