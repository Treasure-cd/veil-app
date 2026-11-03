import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
from core.config import settings
from app import models
from core.session import engine
from app.routers import webhook, auth, payments, payroll
from core.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Veil API...")
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
