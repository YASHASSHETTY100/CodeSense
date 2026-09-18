from contextlib import asynccontextmanager
import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings, validate_security_settings
from app.models.database import init_db
from app.api import auth, projects, qa, admin

logger = logging.getLogger("codesense.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    init_db()
    yield


app = FastAPI(
    title="CodeSense — AI Functional Application Assistant",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact the system administrator."},
    )


def _get_cors_origins() -> list[str]:
    raw_origins = [o.strip() for o in settings.FRONTEND_ORIGIN.split(",") if o.strip()]
    if os.getenv("ENV") != "production":
        for dev in ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]:
            if dev not in raw_origins:
                raw_origins.append(dev)
    return raw_origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(qa.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"ok": True, "service": "codesense-backend"}


@app.get("/")
def root():
    return {"service": "codesense", "docs": "/docs", "health": "/health"}
