# Payment flow

## The cast

- **Merchant:** Logs in to Veil with a wallet signature and receives a JWT.
- **Payer:** Opens the payment link, which is a Veil page, and pays from their own wallet.
- **Backend:** Never moves money. It records intents and checks claims against the chain.
- **Solana:** The source of truth for whether money actually moved.

## End-to-end flow

### 1. Merchant logs in

`POST /auth/challenge` returns a nonce. The wallet signs the message
`Sign this message to login to Veil: nonce`, and `POST /auth/login` verifies
the signature and returns a JWT. The merchant includes that token in subsequent
authenticated requests.

### 2. Merchant creates an intent

The merchant calls `POST /payments/intents` with a merchant reference, mint,
amount (in atomic units, as a string), recipient address, receive mode, and
optional memo. The backend validates the request, stores the intent as
`created`, and returns it.

The recipient address is the merchant's wallet in public mode, or the
less-commonly used Umbra-side address in private mode.

### 3. Payer opens the link

The Veil payment page fetches the intent with `GET /payments/intents/{id}`.
Anyone can call this endpoint. Non-owners receive a trimmed view without the
user ID, signatures, or failure reason; the merchant sees the full intent.

### 4. Payer pays on-chain

The frontend has the payer's wallet send the token transfer directly to
`recipientAddress`. There is no escrow or backend involvement in the transfer,
so the money is in the merchant's hands as soon as the transaction lands. The
transfer remains publicly visible on Solana, including in private mode; private
mode here refers to the receiving address and later withdrawal flow, not a
hidden on-chain transfer.

### 5. Funding is confirmed

The frontend sends the transaction signature to
`POST /intents/{id}/confirm-fund`. The backend:

1. Locks the row so simultaneous calls cannot both pass.
2. Checks that the status is still `created`.
3. Rejects a signature already used on another intent.
4. Fetches the transaction and checks that it succeeded, happened after the
   intent was created, and increased the recipient's balance of that mint by
   at least the requested amount.
5. Sets the intent to `funded` and stores the signature.

### 6. Public mode completes at `funded`

In public mode the merchant already has the money, so no further claim step is
needed.

### 7. Private mode has a claim step

The funds sit at the private address. The merchant moves them to their main
wallet from the frontend, then calls `confirm-claim` with that transaction's
signature. The backend checks that:

- The caller owns the intent.
- The status is `funded`.
- The receive mode is `private`.
- The signature has not been used before.
- The transaction happened after funding and reduced the private address's
  balance by at least the requested amount.

If the checks pass, the backend sets the intent to `claimed`.

## Intent states

```text
created ──confirm-fund──▶ funded ──(public: done)
                             └──(private) confirm-claim──▶ claimed
```

`failed` exists in the model and the `failure_reason` column exists, but
nothing currently sets them.

## Gaps to address

1. **Payer closes the tab after paying.** The money moves, but
   `confirm-fund` never fires, so the intent stays `created`. Add the intent ID
   to the transfer's memo instruction and provide either a merchant
   **Check payment** button or a small background job that looks for
   transactions to the recipient with that memo. This also makes each payment
   match exactly one intent.
2. **Intents never expire.** An old `created` intent can be paid months later.
   Add `expires_at` and reject confirmation requests after expiry. This is also
   where `failed` could be used.
3. **`confirm-fund` is intentionally unauthenticated.** This is considered
   safe because the backend checks the payment on-chain. Anyone with a valid
   payment signature for the intent can trigger confirmation, but the outcome
   is the same.
4. **Overpayment is accepted.** The funding check uses `>=`. Change it to
   `==` if exact amounts are required.
5. **The Umbra assumption needs validation.** Private mode depends on Umbra
   crediting its address with a normal token balance. Test a private payment on
   devnet and inspect the transaction in the explorer before the demo.
