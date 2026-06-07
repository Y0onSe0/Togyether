import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import get_pool, close_pool
from app.routers import auth, agents, calls, acw, dashboard, categories, ws, disease_stats, stt, quarantine, vaccine, notice, history
from app.services.kdca_crawler import crawl_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()   # 앱 시작 시 DB 풀 생성
    crawler_task = asyncio.create_task(crawl_loop())  # 보도자료 크롤러 시작
    yield
    crawler_task.cancel()  # 앱 종료 시 크롤러 중지
    await close_pool()


app = FastAPI(
    title="KDCA 콜센터 AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(calls.router)
app.include_router(acw.router)
app.include_router(dashboard.router)
app.include_router(categories.router)
app.include_router(ws.router)
app.include_router(disease_stats.router)
app.include_router(stt.router)
app.include_router(quarantine.router)
app.include_router(vaccine.router)
app.include_router(notice.router)
app.include_router(history.router)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "KDCA 콜센터 AI v1.0"}
