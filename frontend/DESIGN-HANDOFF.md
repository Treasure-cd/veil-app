# Veil design and product handoff

This document describes the current frontend implementation as a reference for recreating or extending the Veil experience. It combines the design tokens, a code-based visual description, and behavior read from the app. It is not a screenshot: the repository does not include a capture of the live landing page, so the visual description below is derived from the components and styles.

## Design at a glance

Veil uses a light, polished fintech visual style built around deep violet and saturated purple accents. Most surfaces are near-white or white; text is a dark aubergine; panels use soft purple borders and restrained shadows. Rounded cards, pills, and dialog surfaces keep the interface approachable, while monospaced numerals make amounts and wallet-related data feel precise.

The landing page opens with a full-height hero: a faint 24-pixel grid sits behind oversized, soft purple/blue glows. The headline is dark, with its final phrase filled by a purple-to-electric-blue gradient. A WhatsApp conversation mockup anchors the opposite side, with small floating badges for a USDC settlement and shielded data. The page then moves through a proof strip, three illustrated steps, feature cards, a payroll showcase, and a dark-purple call to action. Content enters with subtle fades, movement, blur, and spring transitions; decorative glows drift slowly. The app opts for a calmer dashboard treatment, with white cards, thin purple-tinted borders, and a persistent navigation shell.

The wordmark has two treatments in the code:

- The landing-page `Logo` renders `VEIL.` in uppercase with tight tracking, heavy weight, and an `Orbitron` font-family declaration in the primary purple.
- The signed-in app header/sidebar render plain `Veil` text in the standard UI typeface rather than the stylized wordmark.

The shared interface uses **Geist** and **Geist Mono**, loaded from Google Fonts in `index.html`. The logo asks for Orbitron, but that font is not loaded in `index.html`; unless it is made available elsewhere, the browser may use the declared sans-serif fallback.

## Embedded stylesheet and design tokens

The following is the current contents of [`src/index.css`](./src/index.css), embedded here so the theme can be reused directly:

```css
@import "tailwindcss";

@theme {
  --font-sans: "Geist", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, SFMono-Regular, monospace;

  --color-background: #fefbfd;
  --color-foreground: #21081e;
  --color-primary: #5c049f;
  --color-secondary: #2e0042;
  --color-accent: #4806fe;

  --radius-tiny: 8px;
  --radius-card: 0.75rem;
  --radius-panel: 1.25rem;
  --radius-pill: 9999px;


  --shadow-veil-sm: 0 2px 8px -2px rgba(92, 4, 159, 0.08);
  --shadow-veil-md: 0 4px 16px -4px rgba(92, 4, 159, 0.12);
  --shadow-veil-lg: 0 8px 32px -8px rgba(92, 4, 159, 0.16);
  --shadow-veil-glow: 0 0 24px rgba(72, 6, 254, 0.25);
}

@layer base {
  :root {
    background-color: var(--color-background);
    color: var(--color-foreground);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
}
```

### Palette interpretation

| Token | Value | Use and character |
|---|---|---|
| Background | `#fefbfd` | Almost-white canvas with a faint warm/pink cast. |
| Foreground | `#21081e` | Near-black plum for primary text and high-contrast elements. |
| Primary | `#5c049f` | The core Veil violet: wordmark, headings, active navigation, controls, and key actions. |
| Secondary | `#2e0042` | Deeper aubergine for dark sections and supporting contrast. |
| Accent | `#4806fe` | Vivid blue-violet used for gradients, highlights, and focus treatment. |
| Small / card / panel radii | `8px` / `0.75rem` / `1.25rem` | Rounded inputs and buttons, soft cards, and larger dialogs or panels. |
| Pill radius | `9999px` | Fully rounded badges, toggles, and prominent landing-page actions. |

Shadows use low-opacity purple rather than neutral gray, reinforcing the brand without making the white cards feel heavy. The landing page also uses translucent white surfaces, blurred backdrops, a pale lavender WhatsApp mockup, and a dark CTA section. Green is used for success states; amber indicates a non-mainnet network in the app header.

## Layout and navigation

- **Landing page (`/`):** floating, translucent pill navbar with the `VEIL.` wordmark, in-page links for “How it works,” “Payroll,” and “Pricing,” and an “Open app” action. The component includes a Pricing link, though no pricing section is included in the current landing-page composition.
- **Desktop app:** fixed 15rem left sidebar with Dashboard, Payments, Payroll, and Settings; the active route is highlighted with a soft primary tint. A sticky top header shows the network badge, “New request,” and wallet control.
- **Mobile app:** the sidebar is hidden and replaced by a fixed four-item bottom tab bar. The header remains, with the brand name and wallet/network actions.
- **Responsive content:** app content is centered and width-limited. Payroll becomes a two-column form and summary on wide screens; recipient rows stack on small screens.
- **Motion and accessibility:** Framer Motion drives page/component transitions and active-nav indicators. The app sets `reducedMotion="user"` so motion preferences are respected. Navigation is labeled, and interactive controls use visible focus styles.

## Payments, tokens, and displayed amounts

The live “Request payment” form accepts a description/memo (up to 120 characters), an amount, and a currency/token. The selectable tokens are **USDC** and **SOL**; USDC is selected initially. Amount precision is validated against each token’s decimal places (6 for USDC and 9 for SOL), and the backend receives an integer atomic amount. The generated request is explicitly created with `receiveMode: 'public'`.

The UI displays amounts in the selected token, not as a dollar or naira conversion. There is no fiat exchange-rate display or dual-currency amount in the payment form. The settlement options show “Standard transfer” as visible on-chain and “Private settlement” as unavailable.

The landing-page WhatsApp mockup is illustrative and shows **both** currencies in different parts of its story: an invoice for **₦30,000** and a later wallet settlement of **18.50 USDC**. This is not a live conversion feature. Other landing-page examples show USDC. The payroll form also denominates payouts in USDC or SOL, not naira.

## Payroll form and recipient rows

The payroll screen supports manual entry and CSV import. Each recipient row contains:

1. **Full name**
2. **Solana wallet address**
3. **Amount** (in the payroll’s selected payout token)

The schedule is set once for the payroll group with a **release date** and **local time**. The form supports USDC or SOL, defaults to USDC, shows the recipient count and release date in a summary, and calculates a total funding amount in the selected token. A connected wallet is required to submit.

CSV import requires columns representing name, wallet/address, and amount. Headers are normalized case-insensitively; accepted name aliases are `Name` or `Employee`, wallet aliases are `Address` or `Wallet`, and amount aliases are `Amount` or `Salary`. Rows are checked for a name, a valid Solana address, and a positive amount before import. Invalid rows are previewed but not imported.

## Privacy view: what is and is not hidden

The landing-page payroll showcase has an **Employer / Public** switch. In Employer view, each recipient’s sample amount is visible; in Public view, those **per-recipient amounts** are replaced with bullets. Names, roles, initials, the total vault amount, and the release schedule remain visible in both views. The switch is a presentation in the landing-page mockup, not an app-wide privacy setting.

The actual payroll form shows a static “Private” label in its summary, but it does not currently have an Employer/Public viewing switch. The payment form, conversely, explicitly says private transfers are not available yet, and payment intents are created in public receive mode. The payroll submission path also still contains a placeholder/mock vault signature instead of a completed Umbra lock call. Treat privacy behavior and automatic disbursement shown in marketing copy as product intent, not confirmation that those flows are fully implemented in the current frontend.

## Useful source locations

- [`src/index.css`](./src/index.css) — global CSS theme and design tokens
- [`index.html`](./index.html) — Geist font loading and page shell
- [`src/components/landing/Logo.tsx`](./src/components/landing/Logo.tsx) — stylized landing-page wordmark
- [`src/components/landing/Hero.tsx`](./src/components/landing/Hero.tsx) — hero layout and visual treatment
- [`src/components/landing/PayrollSpotlight.tsx`](./src/components/landing/PayrollSpotlight.tsx) — sample payroll table and privacy-view toggle
- [`src/pages/Payments.tsx`](./src/pages/Payments.tsx) — payment link form and token options
- [`src/pages/Payroll.tsx`](./src/pages/Payroll.tsx) — payroll scheduling, recipient rows, and CSV import
- [`src/components/layout/Sidebar.tsx`](./src/components/layout/Sidebar.tsx), [`src/components/layout/BottomNav.tsx`](./src/components/layout/BottomNav.tsx), and [`src/components/layout/Header.tsx`](./src/components/layout/Header.tsx) — app navigation shell
