# Veil

### Payments and payroll, without the unnecessary complexity.

Veil is a crypto-powered payment and payroll platform built on Solana. It simplifies how businesses collect payments and distribute funds by bringing essential financial workflows into one place.

From generating payment requests to scheduling payroll, Veil helps vendors manage their transactions without having to navigate complicated crypto payment processes manually.

---

## The Problem

Accepting cryptocurrency payments and managing payouts can be unnecessarily complicated for small businesses and independent vendors.

A vendor might need to:
- Manually generate and share wallet addresses.
- Explain payment instructions to customers.
- Track incoming transactions.
- Coordinate multiple transfers when paying employees or collaborators.
- Repeat these processes for every transaction or payment cycle.

Existing crypto infrastructure provides the underlying capabilities, but the experience isn't always convenient for everyday business operations.

## The Solution

Veil provides a unified interface for payment collection and payroll management.

Instead of manually coordinating individual transfers, vendors can generate payment requests, share payment links or QR codes, and manage scheduled payouts from a single platform.

The goal is to make crypto payment workflows more accessible, organised, and practical for businesses.

---

## Features

### 1. Payment Collection

Vendors can generate payment requests containing transaction details such as the description, amount, and preferred token.

Each request can be shared through a payment link or QR code.

Customers can open the link, connect their Solana wallet, and complete the payment.

**Planned integrations:**
- WhatsApp and Telegram bots for generating payment requests directly from messaging platforms.
- NFC-based payments, allowing compatible phones to function as payment terminals.

### 2. Multi-token Payments

Veil supports multiple tokens within its payment workflow.

The current prototype includes:
- USDC
- SOL
- USDG

The architecture is built around Solana-based transactions, with stablecoins providing an option for payments that are less exposed to cryptocurrency price fluctuations.

### 3. Payroll Management

Veil is designed to simplify recurring payments to employees, contractors, and other recipients.

Vendors can organise payouts by specifying:
- Recipient names.
- Wallet addresses or phone numbers.
- Payment amounts.
- Payment schedules.

Supported scheduling options are intended to include weekly, bi-weekly, and monthly payments.

CSV uploads are also supported in the payroll workflow to make managing multiple recipients easier.

### 4. Fund Management

Veil's payroll workflow incorporates a vault mechanism for holding funds until their scheduled release.

This provides a more organised way to prepare and manage multiple payouts rather than handling each transfer individually.

The prototype also aims to keep individual recipient payment amounts private from other recipients.

### 5. Privacy

Veil includes a private-mode interface intended to support more privacy-conscious payment workflows.

Privacy functionality is subject to the underlying integration and is not assumed to be available merely because the interface exposes the option.

---

## How It Works

### Payment Collection

1. A vendor connects their Solana wallet.
2. The vendor creates a payment request.
3. Veil generates a payment link and QR code.
4. The vendor shares the payment details with the customer.
5. The customer opens the payment link and connects their wallet.
6. The customer approves and signs the transaction.
7. Funds are transferred to the vendor's wallet.

### Payroll

1. A vendor prepares a payroll list.
2. Recipient details and payment amounts are added individually or imported through CSV.
3. The vendor configures the payout schedule.
4. Funds are prepared and managed through the vault workflow.
5. Payouts are released according to the configured schedule and authorization rules.

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

### Authentication

Veil uses wallet-based authentication.

Users authenticate by connecting their Solana wallet and signing a challenge message. The backend verifies the signature and issues a JSON Web Token (JWT) for subsequent authenticated requests.

This avoids requiring users to create a conventional password-based account.

---

## Architecture

Veil separates its frontend, backend, and blockchain responsibilities.

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

The project is organised into separate frontend and backend applications.

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

The frontend is responsible for the user interface, wallet interactions, transaction signing, and communication with the backend.

The backend handles authentication, data persistence, API operations, and server-side business logic.

Blockchain transactions are signed by users through their connected wallets.

---

## Getting Started

### Prerequisites

Before running Veil locally, ensure you have:

- Node.js
- pnpm
- Python 3.12+
- PostgreSQL
- A Solana-compatible wallet, such as Phantom or Solflare.

### 1. Clone the Repository

```bash
git clone veil-app
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

Configure the required environment variables in a `.env` file.

Consult `core/config.py` for the configuration fields required by the backend.

Ensure PostgreSQL is running and the database is configured.

Run database migrations:

```bash
uv run alembic upgrade head
```

Start the development server:

```bash
uv run uvicorn main:app --reload
```

The API should now be available at:

```text
http://localhost:8000
```

API documentation is available at:

```text
http://localhost:8000/docs
```

### 3. Set Up the Frontend

Open another terminal:

```bash
cd frontend
```

Install dependencies:

```bash
pnpm install
```

Configure the frontend environment variables, including the backend API URL.

Start the development server:

```bash
pnpm dev
```

Vite will provide the local development URL in the terminal.

---

## API

The backend exposes versioned API routes under `/v1`.

| Route | Purpose |
|---|---|
| `/v1/auth/challenge` | Generate a wallet authentication challenge |
| `/v1/auth/login` | Verify a wallet signature and issue a JWT |
| `/v1/payments` | Payment operations |
| `/v1/payroll` | Payroll operations |
| `/v1/webhook` | Webhook handling |

For the complete request and response specifications, see the automatically generated FastAPI documentation at `/docs`.

---

## Project Status

Veil is currently under active development.

| Component | Status |
|---|---|
| FastAPI backend | Implemented |
| Database models and migrations | Implemented |
| Wallet-based authentication | Implemented; undergoing integration |
| Frontend | Under development |
| Payment collection | Prototype implemented |
| Multi-token support | Prototype implemented |
| Payroll management | Prototype implemented |
| Scheduled payouts | Under development |
| WhatsApp integration | Planned |
| Telegram integration | Planned |
| NFC payments | Planned |
| Privacy integration | Requires implementation verification |

Feature availability may change as development progresses.

---

## Roadmap

- [ ] Complete frontend and backend integration.
- [ ] Finalise wallet authentication and session persistence.
- [ ] Complete payment request and transaction workflows.
- [ ] Integrate Tether USDT on Solana.
- [ ] Complete payroll scheduling and vault operations.
- [ ] Implement WhatsApp and Telegram payment-request bots.
- [ ] Explore NFC payment functionality.
- [ ] Verify and integrate privacy functionality.
- [ ] Improve transaction tracking and error handling.
- [ ] Prepare for production deployment.

---

## Built With

Veil is being developed for the **Cleva × Tether Future of Payments Hackathon — UNIUYO Edition**.

The project explores how blockchain infrastructure can be used to simplify practical financial workflows for businesses.

---

## License

License information will be added.
