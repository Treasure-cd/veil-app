import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from loguru import logger
from core.config import settings
from app import models
from core.session import engine
from app.routers import webhook, auth, payments, payroll, dashboard, rates, whatsapp, whatsapp_accounts


def run_migrations() -> None:
    logger.info("Checking for pending Alembic migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "heads"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    )
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    if result.returncode != 0:
        logger.error("Alembic migration failed:\n{}", output)
        raise RuntimeError("Database migration failed on startup")
    if output:
        logger.info("Alembic output:\n{}", output)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Veil API...")
    run_migrations()
    yield
    logger.info("Shutting down Veil API...")
    await engine.dispose()

app = FastAPI(
    title="Veil API",
    description="""Seamless payment and automated payroll solution for SMEs and corporate clients.
    Veil transforms everyday mobile devices into complete payment terminals (Invoicing & Tap-to-Pay)
    and replaces exposed corporate ledgers with confidential, cross-border-ready payroll — all settled
    instantly in local fiat.""",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    if request.url.path == "/v1/whatsapp/webhook":
        logger.exception("Unhandled WhatsApp webhook error", exc_info=exc)
        return Response(
            content='{"status":"ok"}',
            status_code=200,
            media_type="application/json",
        )
    logger.exception("Unhandled API error", exc_info=exc)
    return Response(content='{"detail":"Internal server error"}', status_code=500, media_type="application/json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_origin_regex=r"https://veil-sol.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(payments.router, prefix="/v1")
app.include_router(payroll.router, prefix="/v1")
app.include_router(dashboard.router, prefix="/v1")
app.include_router(rates.router, prefix="/v1")
app.include_router(whatsapp.router, prefix="/v1")
app.include_router(whatsapp_accounts.router, prefix="/v1")

@app.get("/")
async def root():
    """Root Endpoint"""
    logger.info("Reading root...")
    return {
        "message": "Veil API running...",
        "status": "healthy"
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.PORT,
    )
