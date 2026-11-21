# Veil API

FastAPI API for Veil. The application entrypoint is `main:app`.

## Run locally

From this directory, create `.env` from `.env.example`, install dependencies, and start the API:

```sh
uv sync --locked
uv run fastapi dev
```

The API docs are at `http://127.0.0.1:8000/docs`.

## Deploy with FastAPI Cloud

The FastAPI Cloud project is linked to this directory. Run deployment commands from `backend/`:

```sh
uv sync --locked
uv run fastapi dev
uv run fastapi deploy
```

For a Git-based deployment from the repository root, set the FastAPI Cloud application directory to `backend`.

Configure these variables in the FastAPI Cloud app settings before deployment:

- `DATABASE_URL_DEV`: Neon/Postgres connection URL. Use an asyncpg-compatible URL or standard `postgresql://` URL; the app normalizes the latter.
- `JWT_SECRET`: random secret of at least 32 characters.
- `ALLOWED_ORIGINS`: comma-separated frontend origins, including the deployed Veil frontend.
- `SOLANA_NETWORK`, `SOLANA_RPC_URL`, and `USDC_MINT`: default to Solana devnet and Circle's devnet USDC mint.
- `RATE_NGN_PER_SOL` and `RATE_NGN_PER_USDC`: optional fallback values if CoinGecko is unavailable.
- `WASENDER_API_KEY`: optional, required only for the WhatsApp integration.

Set database credentials and `JWT_SECRET` as encrypted secrets in FastAPI Cloud. Do not deploy the local `.env` file.

Run database migrations against the configured database before serving traffic:

```sh
uv run alembic upgrade head
```
