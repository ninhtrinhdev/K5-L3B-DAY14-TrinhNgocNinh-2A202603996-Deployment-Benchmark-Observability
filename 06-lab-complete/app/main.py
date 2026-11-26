"""
Production AI Agent — Part 6 Final Project.

Chạy:   uvicorn app.main:app --workers 2
Kiểm:   python check_production_ready.py
"""
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log là 1 JSON object ──────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers = [handler]
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logging()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ── Lifespan: khởi động / tắt an toàn ──────────────────────────────────────
# Uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` và thoát với exit code 0. Không tự đăng ký signal
# handler để khỏi chặn mất handler của uvicorn.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, port=settings.port,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              redis_ok=redis_healthy())
    yield
    log_event("shutdown", reason="SIGTERM or server stop")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Không lộ stack trace cho client; log lại để debug
        logger.exception("unhandled_error", extra={"fields": {
            "request_id": request_id, "path": request.url.path}})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    log_event("request", request_id=request_id, method=request.method,
              path=request.url.path, status=response.status_code, ms=ms)
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.get("/")
def root():
    return {"service": "production-ai-agent", "endpoints": ["/health", "/ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness: process còn sống là 200, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis kết nối được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "down"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    log_event("llm_call", user_id=body.user_id, q_chars=len(body.question),
              a_chars=len(answer), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
