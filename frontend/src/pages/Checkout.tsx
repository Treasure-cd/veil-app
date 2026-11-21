import { useEffect, useState, type ReactNode } from 'react'
import { WalletReadyState } from '@solana/wallet-adapter-base'
import { useConnection, useWallet } from '@solana/wallet-adapter-react'
import {
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
  type BlockhashWithExpiryBlockHeight,
} from '@solana/web3.js'
import { ArrowSquareOut, CheckCircle, GlobeHemisphereWest, ShieldCheck, Wallet, WarningCircle } from '@phosphor-icons/react'
import { useParams } from 'react-router'
import { truncateAddress } from '../lib/format'
import { api } from '../services/api'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'
import { Money } from '../components/ui/Money'
import { NETWORK, NETWORK_LABEL, SOLANA_GENESIS_HASH, USDC_MINT } from '../lib/network'

const TOKEN_PROGRAM_ID = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
const ASSOCIATED_PROGRAM_ID = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
const MEMO_PROGRAM_ID = new PublicKey('MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr')
const TOKENS: Record<string, { symbol: string; decimals: number }> = {
  [USDC_MINT]: { symbol: 'USDC', decimals: 6 },
}

interface InvoiceData {
  id: string
  userId?: string
  merchantRef: string
  mint: string
  amountAtomic: string
  amount_ngn?: string | null
  rate_ngn_per_token?: string | null
  expires_at?: string | null
  recipientAddress: string
  receiveMode: string
  memo: string | null
  status: string
  fundSignature?: string | null
  failureReason?: string | null
}

async function associatedTokenAddress(owner: PublicKey, mint: PublicKey) {
  const [address] = await PublicKey.findProgramAddress(
    [owner.toBytes(), TOKEN_PROGRAM_ID.toBytes(), mint.toBytes()],
    ASSOCIATED_PROGRAM_ID,
  )
  return address
}

function safeRpcEndpoint(endpoint: string) {
  try {
    return new URL(endpoint).origin
  } catch {
    return '<custom RPC>'
  }
}

function createAssociatedTokenAccountIdempotentInstruction(
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
    data: new Uint8Array([1]),
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
  const [confirmedSignature, setConfirmedSignature] = useState<string | null>(null)
  const [claimSignature, setClaimSignature] = useState('')
  const [claimError, setClaimError] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)
  const [pendingTransaction, setPendingTransaction] = useState<
    ({ signature: string } & BlockhashWithExpiryBlockHeight) | null
  >(null)
  const [pendingConnect, setPendingConnect] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null)

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
        if (active) {
          setInvoice(data)
          if (data.fundSignature) setConfirmedSignature(data.fundSignature)
        }
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
    if (!invoice?.expires_at || invoice.status !== 'created') return
    const updateRemaining = () => {
      const seconds = Math.max(0, Math.ceil((new Date(invoice.expires_at as string).getTime() - Date.now()) / 1000))
      setRemainingSeconds(seconds)
    }
    updateRemaining()
    const interval = window.setInterval(updateRemaining, 1000)
    return () => window.clearInterval(interval)
  }, [invoice?.expires_at, invoice?.status])

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
    let paymentPhase = 'Preparing the payment'
    try {
      let pending = pendingTransaction
      if (!pending) {
        const rpcEndpoint = safeRpcEndpoint(connection.rpcEndpoint)
        console.info('[Veil checkout] payment network', {
          configuredNetwork: NETWORK,
          rpcEndpoint,
          intentMint: invoice.mint,
          expectedUsdcMint: USDC_MINT,
          payer: publicKey.toBase58(),
        })
        if (invoice.mint !== USDC_MINT) {
          throw new Error(
            `This payment request uses a different USDC mint than the configured ${NETWORK_LABEL[NETWORK]} network. Ask the merchant to create a new payment link on ${NETWORK_LABEL[NETWORK]}.`,
          )
        }
        const token = TOKENS[invoice.mint]
        if (!token) throw new Error('This checkout uses a token that is not supported on this network.')
        let genesisHash: string
        paymentPhase = 'Checking the Solana RPC cluster'
        try {
          genesisHash = await connection.getGenesisHash()
        } catch (rpcError) {
          console.error('[Veil checkout] could not read Solana cluster from RPC', {
            rpcEndpoint,
            errorType: rpcError instanceof Error ? rpcError.name : typeof rpcError,
          })
          throw new Error(
            `Could not reach the configured Solana RPC (${rpcEndpoint}). Check VITE_SOLANA_RPC_URL and try again.`,
          )
        }
        if (genesisHash !== SOLANA_GENESIS_HASH[NETWORK]) {
          console.error('[Veil checkout] RPC cluster does not match app configuration', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            genesisHash,
            expectedGenesisHash: SOLANA_GENESIS_HASH[NETWORK],
          })
          throw new Error(
            `The configured Solana RPC is connected to a different cluster than ${NETWORK_LABEL[NETWORK]}. Check VITE_SOLANA_NETWORK and VITE_SOLANA_RPC_URL.`,
          )
        }
        const amount = BigInt(invoice.amountAtomic)
        if (amount <= 0n || amount > 18_446_744_073_709_551_615n) {
          throw new Error('This payment amount is invalid.')
        }
        const recipient = new PublicKey(invoice.recipientAddress)
        if (publicKey.equals(recipient)) {
          throw new Error('You cannot pay your own wallet. Ask the merchant to use a different receiving wallet.')
        }
        const instructions: TransactionInstruction[] = []

        const mint = new PublicKey(invoice.mint)
        const payerAta = await associatedTokenAddress(publicKey, mint)
        const destination = await associatedTokenAddress(recipient, mint)
        console.info('[Veil checkout] payer token account lookup', {
          configuredNetwork: NETWORK,
          rpcEndpoint,
          mint: invoice.mint,
          payer: publicKey.toBase58(),
          payerAta: payerAta.toBase58(),
        })
        let payerTokenAccounts: Awaited<ReturnType<typeof connection.getParsedTokenAccountsByOwner>>
        paymentPhase = 'Looking up your USDC token accounts'
        try {
          payerTokenAccounts = await connection.getParsedTokenAccountsByOwner(
            publicKey,
            { mint },
            'confirmed',
          )
        } catch (rpcError) {
          console.error('[Veil checkout] payer token account RPC lookup failed', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: invoice.mint,
            payer: publicKey.toBase58(),
            payerAta: payerAta.toBase58(),
            errorType: rpcError instanceof Error ? rpcError.name : typeof rpcError,
          })
          throw new Error(
            `Could not look up your USDC account on ${NETWORK_LABEL[NETWORK]}. The RPC request failed; check your connection and try again.`,
          )
        }
        if (payerTokenAccounts.value.length === 0) {
          console.warn('[Veil checkout] payer has no token account for configured USDC mint', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: invoice.mint,
            payer: publicKey.toBase58(),
            payerAta: payerAta.toBase58(),
          })
          const fundingHint =
            NETWORK === 'devnet'
              ? 'Get test USDC from faucet.circle.com and select Solana Devnet.'
              : 'Make sure the wallet holds native Circle USDC on Solana Mainnet.'
          throw new Error(
            `No USDC token account was found for your wallet on ${NETWORK_LABEL[NETWORK]}. It needs USDC for mint ${invoice.mint}. ${fundingHint}`,
          )
        }

        const payerAccounts = payerTokenAccounts.value.map((item) => ({
          address: item.pubkey,
          amount: BigInt(item.account.data.parsed.info.tokenAmount.amount as string),
        }))
        console.info('[Veil checkout] payer token accounts found', {
          mint: invoice.mint,
          accounts: payerAccounts.map(({ address, amount }) => ({
            address: address.toBase58(),
            amount: amount.toString(),
          })),
        })
        const sourceAccount =
          payerAccounts.find(({ address, amount: balance }) => address.equals(payerAta) && balance >= amount) ??
          payerAccounts.find(({ amount: balance }) => balance >= amount)
        if (!sourceAccount) {
          const available = payerAccounts.reduce((total, account) => total + account.amount, 0n)
          console.warn('[Veil checkout] payer USDC balance is below the requested amount', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: invoice.mint,
            payer: publicKey.toBase58(),
            requestedAmount: amount.toString(),
            availableAmount: available.toString(),
          })
          throw new Error(
            `Your wallet has ${formatAmount(available.toString(), token.decimals)} USDC on ${NETWORK_LABEL[NETWORK]}, but this payment needs ${formatAmount(invoice.amountAtomic, token.decimals)} USDC.`,
          )
        }
        const source = sourceAccount.address
        paymentPhase = 'Checking the merchant token account'
        const destinationAccount = await connection.getAccountInfo(destination, 'confirmed')
        if (!destinationAccount) {
          instructions.push(
            createAssociatedTokenAccountIdempotentInstruction(publicKey, recipient, mint, destination),
          )
        }
        instructions.push(
          transferCheckedInstruction(source, destination, mint, publicKey, amount, token.decimals),
          new TransactionInstruction({
            programId: MEMO_PROGRAM_ID,
            keys: [],
            data: new TextEncoder().encode(`veil:${invoice.id}`),
          }),
        )

        const blockhash = await connection.getLatestBlockhash('confirmed')
        const messageV0 = new TransactionMessage({
          payerKey: publicKey,
          recentBlockhash: blockhash.blockhash,
          instructions,
        }).compileToV0Message()
        const transaction = new VersionedTransaction(messageV0)

        let simulation
        paymentPhase = 'Simulating the Solana transaction'
        try {
          simulation = await connection.simulateTransaction(transaction)
        } catch (simulationError) {
          console.error('[Veil checkout] transaction simulation RPC failed', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: invoice.mint,
            payer: publicKey.toBase58(),
            error: simulationError,
          })
          throw new Error(
            `Could not simulate this transaction on ${NETWORK_LABEL[NETWORK]}. Check the Solana RPC and try again.`,
          )
        }

        console.info('[Veil checkout] transaction simulation result', {
          configuredNetwork: NETWORK,
          rpcEndpoint,
          mint: invoice.mint,
          payer: publicKey.toBase58(),
          err: simulation.value.err,
          logs: simulation.value.logs,
          unitsConsumed: simulation.value.unitsConsumed,
        })
        if (simulation.value.err) {
          const logs = simulation.value.logs?.slice(-12).join('\n')
          throw new Error(
            [
              `Solana simulation rejected this transaction: ${JSON.stringify(simulation.value.err)}`,
              logs ? `Program logs:\n${logs}` : null,
            ]
              .filter(Boolean)
              .join('\n'),
          )
        }

        paymentPhase = 'Waiting for wallet approval and signature'
        const signature = await sendTransaction(transaction, connection)
        pending = { signature, ...blockhash }
        setPendingTransaction(pending)
      }

      if (!pending) throw new Error('The transaction could not be prepared. Please try again.')
      const transactionToConfirm = pending
      paymentPhase = 'Waiting for on-chain transaction confirmation'
      const confirmation = await connection.confirmTransaction(transactionToConfirm, 'confirmed')
      if (confirmation.value.err) throw new Error('The transfer failed on the Solana network.')

      paymentPhase = 'Confirming the payment with Veil'
      const confirmedInvoice = await api<InvoiceData>(`/v1/payments/intents/${invoice.id}/confirm-fund`, {
        method: 'POST',
        body: JSON.stringify({ signature: transactionToConfirm.signature }),
      })
      setConfirmedSignature(transactionToConfirm.signature)
      setInvoice({ ...invoice, ...confirmedInvoice, status: 'funded', fundSignature: transactionToConfirm.signature })
      setPendingTransaction(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Payment failed. Please try again.'
      console.error('[Veil checkout] payment failed', {
        phase: paymentPhase,
        errorName: err instanceof Error ? err.name : typeof err,
        errorMessage: message,
        stack: err instanceof Error ? err.stack : undefined,
      })
      const walletNetworkHint = /network|cluster|blockhash|transaction version|failed to send/i.test(message)
        ? ` Check that your wallet is set to ${NETWORK_LABEL[NETWORK]} and try again.`
        : ''
      setPaymentError(`${paymentPhase}: ${message}${walletNetworkHint}`)
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
  const expired = invoice.status === 'failed' || invoice.failureReason === 'expired' || (remainingSeconds !== null && remainingSeconds <= 0)
  const countdown = remainingSeconds === null
    ? null
    : `${Math.floor(remainingSeconds / 60).toString().padStart(2, '0')}:${(remainingSeconds % 60).toString().padStart(2, '0')}`

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
          <Money amountNgn={invoice.amount_ngn} tokenAmount={displayAmount} token={token.symbol} className="inline-flex align-middle" /> paid for “{invoice.memo || 'Payment request'}”.
        </p>
        {(confirmedSignature || invoice.fundSignature) && (
          <a
            href={`https://explorer.solana.com/tx/${encodeURIComponent(confirmedSignature || invoice.fundSignature || '')}?cluster=${NETWORK}`}
            target="_blank"
            rel="noreferrer"
            className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary underline underline-offset-4"
          >
            View on Solana Explorer <ArrowSquareOut size={16} />
          </a>
        )}
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
          <Money amountNgn={invoice.amount_ngn} tokenAmount={displayAmount} token={token.symbol} className="align-middle" /> is awaiting withdrawal from the private receiving address.
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

  if (expired && !pendingTransaction) {
    return (
      <CheckoutFrame>
        <WarningCircle size={42} className="mx-auto text-amber-500" weight="fill" />
        <h1 className="mt-4 text-2xl font-semibold text-primary">Quote expired</h1>
        <p className="mt-2 text-sm text-foreground/65">This 30-minute payment quote has expired. Ask the merchant for a new payment link.</p>
        <Money amountNgn={invoice.amount_ngn} tokenAmount={displayAmount} token={token.symbol} className="mx-auto mt-4" primaryClassName="text-xl font-semibold text-primary" />
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
      <Money amountNgn={invoice.amount_ngn} tokenAmount={displayAmount} token={token.symbol} className="mx-auto mt-2" primaryClassName="text-4xl font-semibold tracking-tight text-primary" secondaryClassName="text-sm" />
      <p className="mt-2 text-sm text-foreground/65">{invoice.memo || 'Payment request'}</p>

      {countdown && (
        <p className={`mt-3 rounded-pill px-3 py-1.5 text-xs font-medium tabular-nums ${expired ? 'bg-amber-50 text-amber-800' : 'bg-primary/5 text-primary/70'}`} role="timer">
          {expired ? 'Quote expired' : `Locked quote expires in ${countdown}`}
          {expired && pendingTransaction ? ' · confirm your submitted transfer below' : ''}
        </p>
      )}

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
        <p role="alert" className="mb-4 whitespace-pre-line rounded-card bg-red-50 px-3 py-2 text-left text-sm text-red-700">
          {pendingTransaction
            ? `Transfer sent (${truncateAddress(pendingTransaction.signature)}), but confirmation is pending. Retry to finish confirmation. `
            : ''}
          {paymentError}
          {NETWORK === 'devnet' && paymentError.includes('No USDC token account') && (
            <>
              {' '}
              <a
                href="https://faucet.circle.com/"
                target="_blank"
                rel="noreferrer"
                className="font-semibold underline underline-offset-2"
              >
                Open Circle’s Devnet faucet
              </a>
              . Select Solana Devnet and send USDC to the connected payer wallet.
            </>
          )}
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
          <p className="text-xs text-foreground/45">This payment uses Solana {NETWORK_LABEL[NETWORK]}. If your wallet reports a network error, switch it to {NETWORK_LABEL[NETWORK]}.</p>
          <Button size="lg" fullWidth loading={paying} onClick={() => void handlePay()} disabled={expired && !pendingTransaction}>
            {pendingTransaction ? 'Retry payment confirmation' : 'Pay now'}
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
