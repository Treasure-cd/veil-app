import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import text
from core.config import settings
from app import models
from core.session import engine
from app.routers import webhook, auth, payments, payroll, dashboard, rates, whatsapp, whatsapp_accounts, admin
from app.services.trace import SEED_ADMIN_ADDRESSES


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


async def _ensure_postgres_schema() -> None:
    """Idempotently ensure schema additions and seed admin exist on Postgres startup."""
    if (
        engine.dialect.name != "postgresql"
        or "unittest" in sys.modules
        or "pytest" in sys.modules
    ):
        return
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(73290411)"))
        await conn.execute(
            text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE')
        )
        await conn.execute(
            text("ALTER TABLE payment_intents ADD COLUMN IF NOT EXISTS paid_via VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS reply_text TEXT")
        )
        await conn.execute(
            text("ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ")
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS whatsapp_setup_tokens ("
                "token VARCHAR(64) PRIMARY KEY, "
                "phone_e164 VARCHAR NOT NULL, "
                "expires_at TIMESTAMPTZ NOT NULL, "
                "used_at TIMESTAMPTZ)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_whatsapp_setup_tokens_phone_e164 "
                "ON whatsapp_setup_tokens (phone_e164)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS whatsapp_auth_challenges ("
                "token VARCHAR(64) PRIMARY KEY, "
                "code VARCHAR(12) NOT NULL UNIQUE, "
                "phone_e164 VARCHAR, "
                'user_id UUID REFERENCES "user"(id), '
                "expires_at TIMESTAMPTZ NOT NULL, "
                "verified_at TIMESTAMPTZ, "
                "consumed_at TIMESTAMPTZ)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_whatsapp_auth_challenges_phone_e164 "
                "ON whatsapp_auth_challenges (phone_e164)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_whatsapp_auth_challenges_user_id "
                "ON whatsapp_auth_challenges (user_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS payment_trace_events ("
                "id UUID PRIMARY KEY, "
                "payment_intent_id UUID REFERENCES payment_intents(id), "
                "fiat_payment_id UUID REFERENCES fiat_payments(id), "
                "paj_order_id UUID REFERENCES paj_offramp_orders(id), "
                "payroll_group_id UUID REFERENCES payroll_groups(id), "
                "source VARCHAR NOT NULL, "
                "event_type VARCHAR NOT NULL, "
                "status VARCHAR NOT NULL DEFAULT 'info', "
                "summary VARCHAR NOT NULL, "
                "details_json TEXT, "
                "actor_address VARCHAR, "
                "created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL)"
            )
        )
        for idx_col in (
            "payment_intent_id",
            "fiat_payment_id",
            "paj_order_id",
            "payroll_group_id",
            "source",
            "event_type",
            "status",
            "actor_address",
            "created_at",
        ):
            await conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_payment_trace_events_{idx_col} "
                    f"ON payment_trace_events ({idx_col})"
                )
            )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for admin_address in SEED_ADMIN_ADDRESSES:
            await conn.execute(
                text(
                    'INSERT INTO "user" (id, address, is_admin, created_at, updated_at) '
                    "VALUES (:id, :address, true, :created_at, :updated_at) "
                    "ON CONFLICT (address) DO UPDATE SET is_admin = true, updated_at = :updated_at"
                ).bindparams(
                    id=uuid4(),
                    address=admin_address,
                    created_at=now,
                    updated_at=now,
                )
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Veil API...")
    run_migrations()
    await _ensure_postgres_schema()
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
app.include_router(admin.router, prefix="/v1")

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
