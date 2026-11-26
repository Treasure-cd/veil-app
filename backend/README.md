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
- `SOLANA_NETWORK`, `SOLANA_RPC_URL`, `USDC_MINT`, and `SOL_MINT`: configure the API's Solana cluster and token mints together. Defaults are Devnet.
- `RATE_NGN_PER_SOL` and `RATE_NGN_PER_USDC`: optional fallback values if CoinGecko is unavailable.
- `WASENDER_API_KEY`: optional, required only for the WhatsApp integration.

Set database credentials and `JWT_SECRET` as encrypted secrets in FastAPI Cloud. Do not deploy the local `.env` file.

### Mainnet launch checklist

- Keep development and production environment settings separate. For both the API and frontend build, set `SOLANA_NETWORK=mainnet-beta` and use a managed Mainnet RPC; do not use Devnet endpoints or rely on the rate-limited public Mainnet RPC for production traffic. The API uses `SOLANA_RPC_URL` over HTTP. The frontend also needs `SOLANA_RPC_URL` and, when the provider supplies a separate endpoint, `SOLANA_WS_URL`.
- Set the API's `USDC_MINT` and frontend's `SOLANA_USDC_MINT` to Circle's Mainnet USDC mint (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`). `SOL_MINT` remains `So11111111111111111111111111111111111111112`. Do not override these with Devnet mint values.
- Production frontend builds require explicit `SOLANA_NETWORK`, HTTPS `SOLANA_RPC_URL`, and HTTPS `API_URL`. The RPC endpoint is embedded in the browser bundle; restrict any provider key for browser use. The checkout checks the RPC genesis hash before submitting a wallet payment.
- Use a separate production database, configured with `DATABASE_URL_DEV` in the API environment, and run migrations against that database. Do not reuse the Devnet database or include its test intents in production dashboard data.
- Configure the live FossaPay API key, API secret, and webhook signing secret as encrypted production environment variables. Keep `FOSSAPAY_BASE_URL` on the production API. Register `https://veil-3998494c.fastapicloud.dev/v1/webhook/fossapay` as the live webhook URL and verify a signed event reaches the API. The webhook handler deduplicates repeated event IDs; check that a retry of the same event does not create another payment effect.
- The wallet must be switched out of Developer/Testnet mode. Use a dedicated test wallet with only a small amount of real SOL/USDC, confirm it has enough SOL for fees and account rent, and begin with the minimum FossaPay checkout amount. Verify the signed webhook and confirmed settlement on Solana Explorer before increasing the amount.

The on-chain checkout is confirmed at Solana's `confirmed` commitment before the API marks the intent funded; it does not accept `processed` as sufficient.

Payroll vault funding is not Mainnet-ready: the current Umbra integration is Devnet-only, so the frontend blocks this action on Mainnet. Scheduled recipient payouts are also not enabled. Do not advertise Mainnet payroll until both are implemented and tested on Mainnet.

Run database migrations against the configured database before serving traffic:

```sh
uv run alembic upgrade head
```
