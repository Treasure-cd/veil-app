Note for later: For a production environment, you will want to expand verify_solana_transaction to pull the full transaction data (using get_transaction) and verify that the recipient_address matches your intent and the transferred token amount matches amount_atomic.


todo
- finish landing page, thirty minutes
- test through and through (might take a while) - 3 hours
- deploy - 1 hour
- iron shirt
- look up stuff for career fair
- start submitting. the pitch is the major thing, so it has to be flawless


Do a visual polish and mobile-responsiveness pass across the whole app (landing page, Dashboard, Payments, Payroll, Settings, sign-in modal, payer page).

Style direction: fintech, number-heavy, straight to the point but not brutalist. Use the existing design tokens; don't introduce new colours or fonts.

Cover:
- Consistent spacing, card style, radii and shadows from the token scale
- Typography hierarchy: Geist for UI, Geist Mono for addresses and figures, tabular numbers
- Hover, focus-visible, active and disabled states on every interactive element
- Loading skeletons, empty states and error states on every page
- Subtle, quick transitions (150–200ms); no heavy animation
- Responsive layout: sidebar becomes a bottom nav on mobile; tables become stacked cards; modals become bottom sheets on small screens; test at 360px, 768px and 1280px with no horizontal scroll
- Touch targets of at least 44px on mobile
- Wallet address truncation (7Xy...3kP) that never overflows

Work page by page and list what you changed on each. Keep changes targeted; don't restructure working components.


Prepare the app for public use on Solana devnet.

1. Read the network, RPC URL and USDC mint from env vars (VITE_ prefixed on the frontend) so the same build can be switched to mainnet later without code changes.
2. Show a clear but unobtrusive "Devnet" badge in the header and a one-time dismissible notice explaining that devnet tokens have no real value, with a link to the Solana faucet.
3. Make sure the wallet adapter is configured for devnet and shows a helpful message if the user's wallet is on the wrong network.
4. Landing page: replace the "Coming soon" button with "Open app", which opens the sign-in modal or goes to /payments if there is already a session.
5. Switch the landing page favicon.
6. Check that every page is reachable without errors for a brand-new wallet that has no data yet.
