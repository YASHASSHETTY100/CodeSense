from contextlib import asynccontextmanager
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
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
