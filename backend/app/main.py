from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import api
from .alerts import AlertEvaluator
from .config import DATABASE_PATH, SAMPLE_LOG_PATH
from .ingestion import LogIngestor
from .parser import parse_line
from .repository import SQLiteRepository
from .websocket import EventHub


def create_app(database_path=DATABASE_PATH) -> FastAPI:
    repository = SQLiteRepository(database_path)
    hub = EventHub()
    alerts = AlertEvaluator(repository)
    ingestor = LogIngestor(repository, alerts, hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        if repository.count_logs() == 0 and SAMPLE_LOG_PATH.exists():
            samples = SAMPLE_LOG_PATH.read_text(encoding="utf-8").splitlines()
            seeded_at = datetime.now(timezone.utc)
            for index, line in enumerate(samples):
                event = parse_line(line)
                event["timestamp"] = seeded_at - timedelta(seconds=len(samples) - index)
                repository.insert_log(event)
        yield

    app = FastAPI(title="SignalDesk Log Analyzer", version="1.0.0", lifespan=lifespan)
    app.state.repository = repository
    app.state.hub = hub
    app.state.ingestor = ingestor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(api.router)

    @app.websocket("/ws/logs")
    async def logs_socket(websocket: WebSocket):
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(websocket)

    return app


app = create_app()
