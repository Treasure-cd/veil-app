import { useEffect, useState, type ReactNode } from 'react'
import { WalletReadyState } from '@solana/wallet-adapter-base'
import { useConnection, useWallet } from '@solana/wallet-adapter-react'
import {
  PublicKey,
  SystemProgram,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js'
import { CheckCircle, GlobeHemisphereWest, ShieldCheck, Wallet, WarningCircle } from '@phosphor-icons/react'
import { useParams } from 'react-router'
import { truncateAddress } from '../lib/format'
import { api } from '../services/api'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'

const TOKEN_PROGRAM_ID = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
const ASSOCIATED_PROGRAM_ID = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
const TOKENS: Record<string, { symbol: string; decimals: number; native?: boolean }> = {
  '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU': { symbol: 'USDC', decimals: 6 },
  'So11111111111111111111111111111111111111112': { symbol: 'SOL', decimals: 9, native: true },
}

interface InvoiceData {
  id: string
  userId?: string
  merchantRef: string
  mint: string
  amountAtomic: string
  recipientAddress: string
  receiveMode: string
  memo: string | null
  status: string
}

async function associatedTokenAddress(owner: PublicKey, mint: PublicKey) {
  const [address] = await PublicKey.findProgramAddress(
    [owner.toBytes(), TOKEN_PROGRAM_ID.toBytes(), mint.toBytes()],
    ASSOCIATED_PROGRAM_ID,
  )
  return address
}

function createAssociatedTokenAccountInstruction(
  payer: PublicKey,
  owner: PublicKey,
  mint: PublicKey,
  account: PublicKey,
) {
  return new TransactionInstruction({
    programId: ASSOCIATED_PROGRAM_ID,
    keys: [
      { pubkey: payer, isSigner: true, isWritable: true },
      { pubkey: account, isSigner: false, isWritable: true },
      { pubkey: owner, isSigner: false, isWritable: false },
      { pubkey: mint, isSigner: false, isWritable: false },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      { pubkey: TOKEN_PROGRAM_ID, isSigner: false, isWritable: false },
    ],
    data: new Uint8Array(),
  })
}

function transferCheckedInstruction(
  source: PublicKey,
  destination: PublicKey,
  mint: PublicKey,
  owner: PublicKey,
  amount: bigint,
  decimals: number,
) {
  const data = new Uint8Array(10)
  data[0] = 12
  for (let index = 0; index < 8; index += 1) {
    data[index + 1] = Number((amount >> BigInt(index * 8)) & 0xffn)
  }
  data[9] = decimals
  return new TransactionInstruction({
    programId: TOKEN_PROGRAM_ID,
    keys: [
      { pubkey: source, isSigner: false, isWritable: true },
      { pubkey: mint, isSigner: false, isWritable: false },
      { pubkey: destination, isSigner: false, isWritable: true },
      { pubkey: owner, isSigner: true, isWritable: false },
    ],
    data,
  })
}

function formatAmount(amountAtomic: string, decimals: number) {
  const amount = BigInt(amountAtomic)
  const scale = 10n ** BigInt(decimals)
  const whole = (amount / scale).toLocaleString('en-US')
  const fraction = (amount % scale).toString().padStart(decimals, '0')
  const trimmedFraction = fraction.replace(/0+$/, '')
  return `${whole}${trimmedFraction ? `.${trimmedFraction}` : ''}`
}

export default function Checkout() {
  const { id } = useParams()
  const { connection } = useConnection()
  const {
    wallets,
    wallet,
    publicKey,
    connected,
    connecting,
    select,
    connect,
    sendTransaction,
  } = useWallet()
  const { user } = useAuth()

  const [invoice, setInvoice] = useState<InvoiceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [paying, setPaying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [paymentError, setPaymentError] = useState<string | null>(null)
  const [claimSignature, setClaimSignature] = useState('')
  const [claimError, setClaimError] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)
  const [pendingSignature, setPendingSignature] = useState<string | null>(null)
  const [pendingConnect, setPendingConnect] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    if (!id) {
      setError('This payment link is missing its request ID.')
      setLoading(false)
      return
    }

    setLoading(true)
    void api<InvoiceData>(`/v1/payments/intents/${encodeURIComponent(id)}`)
      .then((data) => {
        if (active) setInvoice(data)
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'We could not load this payment request.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [id])

  useEffect(() => {
    if (!pendingConnect || !wallet || connected || connecting) return
    setPendingConnect(false)
    void connect().catch((err: unknown) => {
      const cancelled = err instanceof Error && /reject|denied|cancel/i.test(err.message)
      setConnectError(cancelled ? 'Wallet connection cancelled.' : 'Could not connect to this wallet. Try again.')
    })
  }, [pendingConnect, wallet, connected, connecting, connect])

  function chooseWallet(name: (typeof wallets)[number]['adapter']['name']) {
    setConnectError(null)
    select(name)
    setPendingConnect(true)
  }

  async function handlePay() {
    if (!invoice || !publicKey || !connected) return
    setPaymentError(null)
    setPaying(true)
    try {
      let signature = pendingSignature
      if (!signature) {
        const token = TOKENS[invoice.mint]
        if (!token) throw new Error('This checkout uses a token that is not supported on this network.')
        const amount = BigInt(invoice.amountAtomic)
        if (amount <= 0n || amount > 18_446_744_073_709_551_615n) {
          throw new Error('This payment amount is invalid.')
        }
        const recipient = new PublicKey(invoice.recipientAddress)
        const transaction = new Transaction()

        if (token.native) {
          transaction.add(
            SystemProgram.transfer({ fromPubkey: publicKey, toPubkey: recipient, lamports: amount }),
          )
        } else {
          const mint = new PublicKey(invoice.mint)
          const source = await associatedTokenAddress(publicKey, mint)
          const destination = await associatedTokenAddress(recipient, mint)
          const sourceAccount = await connection.getAccountInfo(source, 'confirmed')
          if (!sourceAccount) {
            throw new Error(`Your wallet does not have a ${token.symbol} token account.`)
          }
          const destinationAccount = await connection.getAccountInfo(destination, 'confirmed')
          if (!destinationAccount) {
            transaction.add(createAssociatedTokenAccountInstruction(publicKey, recipient, mint, destination))
          }
          transaction.add(
            transferCheckedInstruction(source, destination, mint, publicKey, amount, token.decimals),
          )
        }

        const blockhash = await connection.getLatestBlockhash('confirmed')
        transaction.feePayer = publicKey
        transaction.recentBlockhash = blockhash.blockhash
        signature = await sendTransaction(transaction, connection)
        setPendingSignature(signature)

        const confirmation = await connection.confirmTransaction(
          { ...blockhash, signature },
          'confirmed',
        )
        if (confirmation.value.err) throw new Error('The transfer failed on the Solana network.')
      }

      await api<InvoiceData>(`/v1/payments/intents/${invoice.id}/confirm-fund`, {
        method: 'POST',
        body: JSON.stringify({ signature }),
      })
      setInvoice({ ...invoice, status: 'funded' })
      setPendingSignature(null)
    } catch (err) {
      setPaymentError(err instanceof Error ? err.message : 'Payment failed. Please try again.')
    } finally {
      setPaying(false)
    }
  }

  async function handleClaim() {
    if (!invoice || !claimSignature.trim()) return
    setClaimError(null)
    setClaiming(true)
    try {
      const updatedInvoice = await api<InvoiceData>(`/v1/payments/intents/${invoice.id}/confirm-claim`, {
        method: 'POST',
        body: JSON.stringify({ signature: claimSignature.trim() }),
      })
      setInvoice(updatedInvoice)
      setClaimSignature('')
    } catch (err) {
      setClaimError(err instanceof Error ? err.message : 'Could not verify the withdrawal transaction.')
    } finally {
      setClaiming(false)
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-background" role="status" aria-label="Loading checkout">
        <div className="size-8 animate-spin rounded-full border-4 border-primary/20 border-t-primary" />
      </main>
    )
  }

  if (error || !invoice) {
    return (
      <CheckoutFrame>
        <WarningCircle size={42} className="mx-auto text-red-500" weight="fill" />
        <h1 className="mt-4 text-2xl font-semibold text-primary">Checkout unavailable</h1>
        <p role="alert" className="mt-2 text-sm text-foreground/65">
          {error ?? 'This payment request could not be found.'}
        </p>
      </CheckoutFrame>
    )
  }

  const token = TOKENS[invoice.mint]
  if (!token || !/^\d+$/.test(invoice.amountAtomic) || BigInt(invoice.amountAtomic) <= 0n) {
    return (
      <CheckoutFrame>
        <WarningCircle size={42} className="mx-auto text-amber-500" weight="fill" />
        <h1 className="mt-4 text-2xl font-semibold text-primary">Unsupported payment</h1>
        <p className="mt-2 text-sm text-foreground/65">This request uses an invalid amount or an unsupported token.</p>
      </CheckoutFrame>
    )
  }

  const displayAmount = formatAmount(invoice.amountAtomic, token.decimals)

  const isOwner = user !== null && invoice.userId === user.id

  if (
    invoice.status === 'claimed' ||
    (invoice.status === 'funded' && invoice.receiveMode !== 'private')
  ) {
    return (
      <CheckoutFrame>
        <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle size={36} weight="fill" />
        </div>
        <h1 className="mt-5 text-2xl font-semibold tracking-tight text-primary">Payment complete</h1>
        <p className="mt-2 text-sm text-foreground/65">
          {displayAmount} {token.symbol} paid for “{invoice.memo || 'Payment request'}”.
        </p>
        <p className="mt-6 rounded-card bg-background px-4 py-3 text-xs text-foreground/55">
          This payment was made with a standard on-chain transfer. You can safely close this page.
        </p>
      </CheckoutFrame>
    )
  }

  if (invoice.status === 'funded' && invoice.receiveMode === 'private') {
    return (
      <CheckoutFrame>
        <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle size={36} weight="fill" />
        </div>
        <h1 className="mt-5 text-2xl font-semibold tracking-tight text-primary">
          Private payment received
        </h1>
        <p className="mt-2 text-sm text-foreground/65">
          {displayAmount} {token.symbol} is awaiting withdrawal from the private receiving address.
        </p>
        {isOwner ? (
          <div className="mt-6 space-y-3 text-left">
            <label htmlFor="claim-signature" className="block text-sm font-medium text-primary">
              Withdrawal transaction signature
            </label>
            <input
              id="claim-signature"
              type="text"
              value={claimSignature}
              onChange={(event) => setClaimSignature(event.target.value)}
              placeholder="Paste the confirmed transaction signature"
              className="h-11 w-full rounded-card border border-primary/15 bg-background px-3 font-mono text-sm outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
            />
            {claimError && (
              <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-sm text-red-700">
                {claimError}
              </p>
            )}
            <Button
              fullWidth
              loading={claiming}
              disabled={!claimSignature.trim()}
              onClick={() => void handleClaim()}
            >
              Confirm claim
            </Button>
            <p className="text-xs leading-relaxed text-foreground/55">
              Withdraw the funds to your main wallet first. Veil verifies that this transaction moved
              the requested token amount out of the private address.
            </p>
          </div>
        ) : (
          <p className="mt-6 rounded-card bg-background px-4 py-3 text-xs text-foreground/55">
            The merchant must withdraw the funds from the private receiving address to complete settlement.
          </p>
        )}
      </CheckoutFrame>
    )
  }

  if (invoice.status !== 'created') {
    return (
      <CheckoutFrame>
        <WarningCircle size={42} className="mx-auto text-amber-500" weight="fill" />
        <h1 className="mt-4 text-2xl font-semibold text-primary">Payment unavailable</h1>
        <p className="mt-2 text-sm text-foreground/65">This payment request is no longer available.</p>
      </CheckoutFrame>
    )
  }

  const installedWallets = wallets.filter((item) => item.readyState === WalletReadyState.Installed)

  return (
    <CheckoutFrame>
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Wallet size={24} weight="fill" />
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-foreground/50">Secure checkout</p>
      <p className="mt-2 text-4xl font-semibold tracking-tight text-primary">
        {displayAmount} <span className="text-2xl text-primary/60">{token.symbol}</span>
      </p>
      <p className="mt-2 text-sm text-foreground/65">{invoice.memo || 'Payment request'}</p>

      <div className="my-6 rounded-card border border-primary/10 bg-background p-4 text-left">
        <div className="flex items-start gap-2 text-sm text-foreground/70">
          {invoice.receiveMode === 'private'
            ? <ShieldCheck className="mt-0.5 shrink-0 text-amber-600" size={17} />
            : <GlobeHemisphereWest className="mt-0.5 shrink-0 text-primary" size={17} />}
          <p>
            This payment is sent as a standard on-chain transfer. Transaction details are visible on the blockchain.
            {invoice.receiveMode === 'private' && ' Funds are sent to the configured private receiving address, but the transfer remains publicly visible on Solana.'}
          </p>
        </div>
      </div>

      {paymentError && (
        <p role="alert" className="mb-4 rounded-card bg-red-50 px-3 py-2 text-left text-sm text-red-700">
          {pendingSignature
            ? `Transfer sent (${truncateAddress(pendingSignature)}), but confirmation is pending. Retry to finish confirmation. `
            : ''}
          {paymentError}
        </p>
      )}
      {connectError && (
        <p role="alert" className="mb-4 rounded-card bg-red-50 px-3 py-2 text-sm text-red-700">{connectError}</p>
      )}

      {publicKey && connected ? (
        <div className="space-y-3">
          <p className="text-xs text-foreground/55">
            Connected: {wallet?.adapter.name ?? 'Wallet'} · {truncateAddress(publicKey.toBase58())}
          </p>
          <Button size="lg" fullWidth loading={paying} onClick={() => void handlePay()}>
            {pendingSignature ? 'Retry payment confirmation' : `Pay ${displayAmount} ${token.symbol}`}
          </Button>
        </div>
      ) : installedWallets.length > 0 ? (
        <div className="space-y-2">
          <p className="mb-3 text-sm font-medium">Connect a wallet to continue</p>
          {installedWallets.map(({ adapter }) => (
            <button
              key={adapter.name}
              type="button"
              disabled={connecting || pendingConnect}
              onClick={() => chooseWallet(adapter.name)}
              className="flex w-full items-center gap-3 rounded-card border border-primary/15 bg-white px-4 py-3 text-left text-sm font-medium transition hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
            >
              <img src={adapter.icon} alt="" className="size-6 rounded-md" />
              {connecting || pendingConnect ? 'Connecting…' : `Continue with ${adapter.name}`}
            </button>
          ))}
        </div>
      ) : (
        <div className="rounded-card border border-primary/10 bg-background p-4 text-sm text-foreground/65">
          No Solana wallet was found. Install a browser wallet such as{' '}
          <a className="font-medium text-primary underline" href="https://phantom.com/download" target="_blank" rel="noreferrer">Phantom</a>
          {' '}or{' '}
          <a className="font-medium text-primary underline" href="https://www.solflare.com/download/" target="_blank" rel="noreferrer">Solflare</a>
          , then reload this page.
        </div>
      )}

      <p className="mt-6 text-xs text-foreground/45">No Veil account needed · Powered by Veil on Solana</p>
    </CheckoutFrame>
  )
}

function CheckoutFrame({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-background px-4 py-10">
      <section className="w-full max-w-md rounded-panel border border-primary/10 bg-white p-6 text-center shadow-veil-md sm:p-8">
        {children}
      </section>
    </main>
  )
}
