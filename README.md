# Veil

### Private payments and payroll on Solana.

Veil is a payment and payroll platform for vendors, freelancers and small businesses who get paid in stablecoins. It brings payment requests, checkout links, QR codes and scheduled payroll into one place, and is built around Umbra's privacy protocol so that what you earn doesn't have to sit on a public ledger.

**Landing page:** [yourveil.vercel.app](https://yourveil.vercel.app)

> **Status:** Veil is a prototype. Payment requests and payroll scheduling are implemented in early form. Private settlement is in progress, so payments currently settle as standard on-chain transfers. See [Project Status](#project-status) for the full breakdown.

---

## The Problem

**Getting paid is hard for small vendors.** For social commerce vendors and independent businesses, collecting payment often means switching between apps, waiting for delayed bank alerts, and dodging fake receipts.

**Crypto fixes speed, but adds friction.** Stablecoins on Solana are fast and resist inflation, but accepting them manually means:
- Generating and sharing long wallet addresses.
- Explaining payment instructions to customers.
- Tracking incoming transactions by hand.
- Coordinating multiple transfers when paying staff or collaborators.

**Public blockchains expose everything.** Every payment is recorded openly. A vendor who accepts crypto exposes their full transaction history, their customers and their balance to anyone who looks up their wallet. A team paid on-chain publishes everyone's salary. For people whose income is their livelihood, that is a real cost, and it keeps many from using crypto payments at all.

## The Solution

Veil provides one interface for collecting payments and paying people, designed so that financial details don't have to be public.

Vendors create payment requests, share a checkout link or QR code in any chat, and let customers pay from their own Solana wallet. For payroll, vendors prepare a list of recipients, import it from a CSV, and schedule a release date.

Veil is built around Umbra's privacy protocol, with the goal of keeping amounts and balances off the public ledger. Private settlement is in progress; today payments settle as standard on-chain transfers.

---

## Features

### 1. Privacy

Veil is built around Umbra's privacy protocol. The goal is for payment amounts and balances to stay hidden from the public ledger, and for payroll amounts to stay hidden from other recipients and outside observers.

**Status:** the private-mode interface exists. Private settlement is still being integrated, so payments currently settle as standard on-chain transfers. Privacy functionality is not assumed to be available merely because the interface exposes the option.

### 2. Payment Collection

Vendors generate payment requests containing a description, an amount and a preferred token. Each request is shared as a payment link or QR code. Customers open the link, connect their Solana wallet and complete the payment. Customers do not need a Veil account.

**Planned integrations:**
- WhatsApp and Telegram bots for generating payment requests directly from chat.
- NFC tap-to-pay, allowing compatible phones to act as payment terminals, a point of sale with no extra hardware.

### 3. Multi-token Payments

The current prototype supports:
- USDC
- SOL

Stablecoins give vendors a payment option that is less exposed to cryptocurrency price swings. Support for Tether USDT on Solana is planned.

### 4. Payroll Management

Veil is designed to simplify payments to employees, contractors and other recipients. Vendors specify:
- Recipient names.
- Solana wallet addresses.
- Payment amounts.
- A release date and time.

Recipients can be entered one by one or imported from a CSV file. Recurring schedules (weekly, bi-weekly and monthly) are planned.

### 5. Fund Management

Veil's payroll workflow is designed around a vault that holds funds until their scheduled release, so a payroll can be funded once instead of through many individual transfers. The aim is for individual recipient amounts to stay hidden from other recipients and from outside observers.

**Status:** under development. Vault funding is not yet connected to the Umbra integration.

---

## How It Works

### Payment Collection

1. A vendor connects their Solana wallet.
2. The vendor creates a payment request.
3. Veil generates a payment link and QR code.
4. The vendor shares it with the customer in any chat.
5. The customer opens the link and connects their wallet.
6. The customer approves and signs the transaction.
7. Funds are transferred to the vendor's wallet.

Private settlement, once integrated, will change step 7 so that the amount and the vendor's balance are not exposed on the public ledger.

### Payroll

1. A vendor prepares a payroll list.
2. Recipient details and amounts are added individually or imported through CSV.
3. The vendor chooses a release date and time.
4. Funds are prepared and held through the vault workflow.
5. Payouts are released on schedule.

---

## Technology Stack

### Frontend
- React
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Solana Wallet Adapter

### Backend
- Python
- FastAPI
- SQLModel
- SQLAlchemy (async)
- PostgreSQL
- Alembic

### Blockchain
- Solana
- Solana-compatible wallets
- SPL tokens
- Umbra privacy protocol (integration in progress)

### Authentication

Veil uses wallet-based authentication. Users connect their Solana wallet and sign a challenge message. The backend verifies the signature and issues a JSON Web Token (JWT) for subsequent requests. This avoids requiring a conventional password-based account.

---

## Architecture

Veil separates its frontend, backend and blockchain responsibilities.

```text
                 VEIL
                  |
       +----------+----------+
       |                     |
    FRONTEND               BACKEND
       |                     |
       |                 FastAPI
       |                     |
       |              Authentication
       |              Payment APIs
       |              Payroll APIs
       |              Webhooks
       |                     |
       |                 PostgreSQL
       |
       +-------- Solana --------+
                    |
              Wallets & Tokens
                    |
              Blockchain
```

### Repository Structure

```text
veil/
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...
│
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── models/
│   │   ├── routers/
│   │   └── services/
│   ├── core/
│   ├── main.py
│   ├── pyproject.toml
│   └── ...
│
└── README.md
```

The frontend handles the user interface, wallet interactions, transaction signing and communication with the backend. The backend handles authentication, data persistence, API operations and server-side business logic. Blockchain transactions are signed by users through their connected wallets.

---

## Getting Started

### Prerequisites

- Node.js
- pnpm
- Python 3.12+
- PostgreSQL
- A Solana-compatible wallet, such as Phantom or Solflare

### 1. Clone the Repository

```bash
git clone <repository-url>
cd veil
```

### 2. Set Up the Backend

```bash
cd backend
```

Install dependencies using uv:

```bash
uv sync
```

Configure the required environment variables in a `.env` file. Consult `core/config.py` for the fields the backend needs.

Ensure PostgreSQL is running and the database is configured, then run migrations:

```bash
uv run alembic upgrade head
```

Start the development server:

```bash
uv run uvicorn main:app --reload
```

The API is available at `http://localhost:8000`, with interactive documentation at `http://localhost:8000/docs`.

### 3. Set Up the Frontend

Open another terminal:

```bash
cd frontend
pnpm install
```

Configure the frontend environment variables, including the backend API URL, then start the development server:

```bash
pnpm dev
```

Vite prints the local development URL in the terminal.

---

## API

The backend exposes versioned routes under `/v1`.

| Route | Purpose |
|---|---|
| `/v1/auth/challenge` | Generate a wallet authentication challenge |
| `/v1/auth/login` | Verify a wallet signature and issue a JWT |
| `/v1/payments` | Payment operations |
| `/v1/payroll` | Payroll operations |
| `/v1/webhook` | Webhook handling |

For complete request and response specifications, see the generated FastAPI documentation at `/docs`.

---

## Project Status

Veil is under active development.

| Component | Status |
|---|---|
| FastAPI backend | Implemented |
| Database models and migrations | Implemented |
| Wallet-based authentication | Implemented; undergoing integration |
| Frontend | Under development |
| Payment requests, links and QR | Prototype implemented |
| USDC and SOL payments | Prototype implemented |
| Payroll entry and CSV import | Prototype implemented |
| Payroll vault funding | Under development |
| Private settlement (Umbra) | In progress |
| Recurring payroll schedules | Planned |
| USDT support | Planned |
| WhatsApp and Telegram bots | Planned |
| Naira cash-out | Planned |
| NFC tap-to-pay | Planned |

Feature availability may change as development progresses.

---

## Roadmap

- [ ] Integrate Tether USDT on Solana.
- [ ] Complete private settlement with Umbra.
- [ ] Complete frontend and backend integration.
- [ ] Finalise wallet authentication and session persistence.
- [ ] Complete payment request and transaction workflows.
- [ ] Complete payroll vault funding and scheduled releases.
- [ ] Add recurring payroll schedules.
- [ ] Build WhatsApp and Telegram payment-request bots.
- [ ] Add naira cash-out for vendors.
- [ ] Explore NFC tap-to-pay.
- [ ] Improve transaction tracking and error handling.
- [ ] Prepare for production deployment.

---

## Built With

Veil is being developed for the **Cleva × Tether Future of Payments Hackathon — UNIUYO Edition**.

The project explores how blockchain infrastructure can simplify everyday financial workflows for vendors and small businesses, without making them give up their financial privacy.

---

## License

License information will be added.
