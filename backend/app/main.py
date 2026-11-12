import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import (
    get_cors_origins,
    validate_runtime_config,
    validate_production_config,
)
from app.middleware import OAuthCallbackQueryRedactionMiddleware

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_config()
    validate_production_config()
    yield


app = FastAPI(
    title="AI Email Assistant API",
    version="0.1.0",
    description="Backend API foundation for the AI Email Assistant.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)
app.add_middleware(OAuthCallbackQueryRedactionMiddleware)

app.include_router(api_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled API error for %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred"},
    )
