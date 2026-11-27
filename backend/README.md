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
- `SOLANA_NETWORK`, `SOLANA_RPC_URL`, `USDC_MINT`, and `SOL_MINT`: configure the API's Solana cluster and token mints. Defaults are Mainnet (`mainnet-beta`, `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`); setting `SOLANA_NETWORK=devnet` automatically selects the Devnet RPC and Devnet USDC mint unless explicitly overridden.
- `RATE_NGN_PER_SOL` and `RATE_NGN_PER_USDC`: optional fallback values if CoinGecko is unavailable.
- `WASENDER_API_KEY`: optional, required only for the WhatsApp integration.
- `WHATSAPP_VERIFY_TOKEN`: required for Meta's webhook GET verification; use the same value in Meta and FastAPI Cloud.
- `WHATSAPP_APP_SECRET`: Meta app secret used to validate signed webhook POSTs.
- `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`: credentials for sending WhatsApp replies through Meta's Graph API.
- `WHATSAPP_BUSINESS_PHONE_NUMBER`: the WhatsApp business number in international format, used to create `wa.me` links for account linking.
- `WHATSAPP_PAYMENT_METHODS`: `usdc,fossapay` (default) or `usdc`. FossaPay bank transfer requires a whole-naira amount.
- `WHATSAPP_PRIVATE_PAYMENTS`: defaults to `false`; set to `true` for private USDC checkout links. Private links cannot also offer FossaPay.

### Meta WhatsApp Cloud API webhook

In the Meta app's WhatsApp webhook configuration, set the callback URL to:

```text
https://veil-3998494c.fastapicloud.dev/v1/whatsapp/webhook
```

Subscribe to the `messages` field and configure the same
`WHATSAPP_VERIFY_TOKEN` in Meta and FastAPI Cloud. Set `WHATSAPP_APP_SECRET`,
`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and
`WHATSAPP_BUSINESS_PHONE_NUMBER` in FastAPI Cloud. The GET route verifies
Meta's challenge; POST requests are accepted only when
their `X-Hub-Signature-256` matches the configured app secret. Replies are sent
through Meta's Graph API. Ensure `FRONTEND_URL` points to the deployed Veil
frontend so checkout links open the correct page.

Vendors can use the default public USDC + bank-transfer checkout, or add
`private` and/or `crypto only` to a request, for example
`link 5000 for lunch private crypto only`. Private payments are USDC-only.

Set database credentials and `JWT_SECRET` as encrypted secrets in FastAPI Cloud. Do not deploy the local `.env` file.

### Mainnet launch checklist

- Keep development and production environment settings separate. For both the API and frontend build, set `SOLANA_NETWORK=mainnet-beta` and use a managed Mainnet RPC; do not use Devnet endpoints or rely on the rate-limited public Mainnet RPC for production traffic. The API uses `SOLANA_RPC_URL` over HTTP. The frontend also needs `SOLANA_RPC_URL` and, when the provider supplies a separate endpoint, `SOLANA_WS_URL`.
- Set the API's `USDC_MINT` and frontend's `SOLANA_USDC_MINT` to Circle's Mainnet USDC mint (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`). `SOL_MINT` remains `So11111111111111111111111111111111111111112`. Do not override these with Devnet mint values.
- Production frontend builds require Mainnet configuration, an HTTPS API URL (`API_URL` or `VITE_API_URL`), and a dedicated HTTPS RPC/WSS endpoint (`SOLANA_RPC_URL` / `SOLANA_WS_URL`, or their `VITE_` equivalents). The RPC endpoint is embedded in the browser bundle; restrict any provider key for browser use. The checkout checks the RPC genesis hash before submitting a wallet payment.
- Use a separate production database, configured with `DATABASE_URL_DEV` in the API environment, and run migrations against that database. Do not reuse the Devnet database or include its test intents in production dashboard data.
- Configure the live FossaPay API key, API secret, and webhook signing secret as encrypted production environment variables. Keep `FOSSAPAY_BASE_URL` on the production API. Register `https://veil-3998494c.fastapicloud.dev/v1/webhook/fossapay` as the live webhook URL and verify a signed event reaches the API. The webhook handler deduplicates repeated event IDs; check that a retry of the same event does not create another payment effect.
- The wallet must be switched out of Developer/Testnet mode. Use a dedicated test wallet with only a small amount of real SOL/USDC, confirm it has enough SOL for fees and account rent, and begin with the minimum FossaPay checkout amount. Verify the signed webhook and confirmed settlement on Solana Explorer before increasing the amount.

The on-chain checkout is confirmed at Solana's `confirmed` commitment before the API marks the intent funded; it does not accept `processed` as sufficient.

Payroll vault funding uses the configured Solana network through Umbra; make sure the wallet and RPC match the configured cluster. Scheduled recipient payouts are not enabled yet.

Run database migrations against the configured database before serving traffic:

```sh
uv run alembic upgrade head
```
