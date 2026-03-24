from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.routes.auth import router as auth_router
from app.routes.lists import router as lists_router
from app.routes.tickers import router as tickers_router
from app.routes.presets import router as presets_router

import app.models  # noqa: F401

from app.routes.polygon import router as polygon_router

app = FastAPI()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(lists_router)
app.include_router(tickers_router)
app.include_router(presets_router)
app.include_router(polygon_router)

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    from app.services.cache_service import refresh_market_cache
    import asyncio

    # Schedule the first refresh to run after startup completes
    asyncio.create_task(refresh_market_cache())

    # Then run every 60 seconds
    scheduler.add_job(
        refresh_market_cache,
        trigger=IntervalTrigger(seconds=60),
        id="market_cache_refresh",
        replace_existing=True,
    )
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
