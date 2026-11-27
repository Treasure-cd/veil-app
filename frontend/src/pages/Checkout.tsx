import { useCallback, useEffect, useState, type ReactNode } from 'react'
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
import {
  ArrowSquareOut,
  ArrowsClockwise,
  Bank,
  CheckCircle,
  Copy,
  GlobeHemisphereWest,
  ShieldCheck,
  Wallet,
  WarningCircle,
} from '@phosphor-icons/react'
import { useParams } from 'react-router'
import { truncateAddress } from '../lib/format'
import { formatNgn } from '../lib/money'
import { api } from '../services/api'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'
import { Money } from '../components/ui/Money'
import { BankTransferCard } from '../components/payments/BankTransferCard'
import {
  createIntentFiatCheckout,
  reconcileIntentFiatCheckout,
  type FiatPayment,
} from '../services/fiat'
import {
  createIntentPajOfframp,
  getPajStatusPresentation,
  reconcileIntentPajOfframp,
  type MerchantBankAccount,
  type PajOfframpOrder,
} from '../services/paj'
import {
  IS_DEVNET,
  IS_MAINNET,
  KNOWN_TOKENS,
  NETWORK,
  NETWORK_LABEL,
  SOLANA_GENESIS_HASH,
  SOL_MINT,
  USDC_MINT,
  solanaExplorerTxUrl,
} from '../lib/network'
import { payPrivateInvoice } from '../lib/umbra'

const PAJ_TOKENS = ['USDC', 'SOL', 'USDT', 'USDG'] as const
const TOKEN_PROGRAM_ID = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
const TOKEN_2022_PROGRAM_ID = new PublicKey('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb')
const ASSOCIATED_PROGRAM_ID = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
const MEMO_PROGRAM_ID = new PublicKey('MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr')
const DEFAULT_TX_FEE_LAMPORTS = 5_000n

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
  allowFiatCheckout?: boolean
  settlementTarget?: 'crypto' | 'fiat'
  memo: string | null
  status: string
  fundSignature?: string | null
  failureReason?: string | null
  fiatCheckout?: FiatPayment | null
  fiatPayout?: FiatPayment | { status: string; bankName?: string | null } | null
  pajOfframp?: PajOfframpOrder | null
  bankAccount?: MerchantBankAccount | null
}

function quoteMatchesChoice(order: PajOfframpOrder | null, choice: string, customMint: string) {
  if (!order) return false
  if (choice === 'CUSTOM') return order.mint === customMint.trim()
  return order.tokenSymbol.toUpperCase() === choice
}

async function associatedTokenAddress(
  owner: PublicKey,
  mint: PublicKey,
  tokenProgramId: PublicKey = TOKEN_PROGRAM_ID,
) {
  const [address] = await PublicKey.findProgramAddress(
    [owner.toBytes(), tokenProgramId.toBytes(), mint.toBytes()],
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
  tokenProgramId: PublicKey = TOKEN_PROGRAM_ID,
) {
  return new TransactionInstruction({
    programId: ASSOCIATED_PROGRAM_ID,
    keys: [
      { pubkey: payer, isSigner: true, isWritable: true },
      { pubkey: account, isSigner: false, isWritable: true },
      { pubkey: owner, isSigner: false, isWritable: false },
      { pubkey: mint, isSigner: false, isWritable: false },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      { pubkey: tokenProgramId, isSigner: false, isWritable: false },
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
  tokenProgramId: PublicKey = TOKEN_PROGRAM_ID,
) {
  const data = new Uint8Array(10)
  data[0] = 12
  for (let index = 0; index < 8; index += 1) {
    data[index + 1] = Number((amount >> BigInt(index * 8)) & 0xffn)
  }
  data[9] = decimals
  return new TransactionInstruction({
    programId: tokenProgramId,
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

function decimalToAtomic(value: string, decimals: number): bigint {
  const cleaned = value.trim()
  if (!/^\d+(?:\.\d+)?$/.test(cleaned)) {
    throw new Error('Invalid token amount from payment quote.')
  }
  const [wholePart, fracPart = ''] = cleaned.split('.')
  const paddedFrac = fracPart.slice(0, decimals).padEnd(decimals, '0')
  return BigInt(wholePart) * 10n ** BigInt(decimals) + BigInt(paddedFrac || '0')
}

export default function Checkout() {
  const { id } = useParams()
  const { connection } = useConnection()
  const walletContext = useWallet()
  const {
    wallets,
    wallet,
    publicKey,
    connected,
    connecting,
    select,
    connect,
    sendTransaction,
  } = walletContext
  const { user } = useAuth()

  const [invoice, setInvoice] = useState<InvoiceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [payMethod, setPayMethod] = useState<'bank' | 'wallet'>('bank')
  const [paying, setPaying] = useState(false)
  const [fiatLoading, setFiatLoading] = useState(false)
  const [fiatChecking, setFiatChecking] = useState(false)
  const [fiatError, setFiatError] = useState<string | null>(null)
  const [pajTokenChoice, setPajTokenChoice] = useState<string>('USDC')
  const [customMint, setCustomMint] = useState('')
  const [pajLoading, setPajLoading] = useState(false)
  const [pajChecking, setPajChecking] = useState(false)
  const [pajError, setPajError] = useState<string | null>(null)
  const [copiedPajAddress, setCopiedPajAddress] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [paymentError, setPaymentError] = useState<string | null>(null)
  const [confirmedSignature, setConfirmedSignature] = useState<string | null>(null)
  const [claimSignature, setClaimSignature] = useState('')
  const [claimError, setClaimError] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)
  const [pendingTransaction, setPendingTransaction] = useState<
    ({ signature: string } & BlockhashWithExpiryBlockHeight) | null
  >(null)
  const [pendingPrivateSignature, setPendingPrivateSignature] = useState<string | null>(null)
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
        if (!active) return
        setInvoice(data)
        if (data.fundSignature) setConfirmedSignature(data.fundSignature)
        if (data.pajOfframp) {
          const upper = data.pajOfframp.tokenSymbol.toUpperCase()
          if (PAJ_TOKENS.includes(upper as (typeof PAJ_TOKENS)[number])) {
            setPajTokenChoice(upper)
          } else {
            setPajTokenChoice('CUSTOM')
            setCustomMint(data.pajOfframp.mint)
          }
        }
        const wholeNgn = data.amount_ngn ? /^\d+$/.test(data.amount_ngn) && Number(data.amount_ngn) >= 1 : false
        const bankTransferAvailable = Boolean(
          data.fiatCheckout ||
            (data.allowFiatCheckout !== false &&
              data.receiveMode !== 'private' &&
              wholeNgn &&
              data.settlementTarget !== 'fiat'),
        )
        if (bankTransferAvailable) setPayMethod('bank')
        else setPayMethod('wallet')
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

  const invoiceId = invoice?.id
  const invoiceStatus = invoice?.status
  const fiatCheckoutStatus = invoice?.fiatCheckout?.status
  const pajOrderId = invoice?.pajOfframp?.id
  const pajOrderStatus = invoice?.pajOfframp?.status

  const handleReconcileFiat = useCallback(async () => {
    if (!invoiceId) return
    setFiatChecking(true)
    setFiatError(null)
    try {
      const updated = await reconcileIntentFiatCheckout(invoiceId)
      if (updated.status === 'completed') {
        const refreshed = await api<InvoiceData>(`/v1/payments/intents/${encodeURIComponent(invoiceId)}`).catch(() => null)
        if (refreshed) {
          setInvoice(refreshed)
          return
        }
      }
      setInvoice((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          fiatCheckout: updated,
          status: updated.status === 'completed' ? 'funded' : prev.status,
        }
      })
    } catch (err) {
      setFiatError(err instanceof Error ? err.message : 'Could not check bank transfer status.')
    } finally {
      setFiatChecking(false)
    }
  }, [invoiceId])

  const handleReconcilePaj = useCallback(async () => {
    if (!invoiceId) return
    setPajChecking(true)
    setPajError(null)
    try {
      const updated = await reconcileIntentPajOfframp(invoiceId, pajOrderId)
      setInvoice((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          pajOfframp: updated,
          status: updated.status === 'COMPLETED' ? 'funded' : prev.status,
          fundSignature: updated.txSignature ?? prev.fundSignature,
        }
      })
    } catch (err) {
      setPajError(err instanceof Error ? err.message : 'Could not check Paj Cash offramp status.')
    } finally {
      setPajChecking(false)
    }
  }, [invoiceId, pajOrderId])

  useEffect(() => {
    if (!invoiceId || invoiceStatus !== 'created' || (fiatCheckoutStatus !== 'pending' && fiatCheckoutStatus !== 'processing')) {
      return
    }
    const interval = window.setInterval(() => {
      void handleReconcileFiat()
    }, 8000)
    return () => window.clearInterval(interval)
  }, [invoiceId, invoiceStatus, fiatCheckoutStatus, handleReconcileFiat])

  useEffect(() => {
    if (!invoiceId || invoiceStatus !== 'created' || (pajOrderStatus !== 'INIT' && pajOrderStatus !== 'PROCESSING')) {
      return
    }
    const interval = window.setInterval(() => {
      void handleReconcilePaj()
    }, 8000)
    return () => window.clearInterval(interval)
  }, [invoiceId, invoiceStatus, pajOrderStatus, handleReconcilePaj])

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

  async function handleGenerateFiatCheckout() {
    if (!invoice) return
    setFiatLoading(true)
    setFiatError(null)
    try {
      const checkout = await createIntentFiatCheckout(invoice.id)
      setInvoice((prev) => (prev ? { ...prev, fiatCheckout: checkout } : prev))
    } catch (err) {
      setFiatError(err instanceof Error ? err.message : 'Could not generate bank transfer details.')
    } finally {
      setFiatLoading(false)
    }
  }

  async function handleCreatePajOrder(tokenArg?: string) {
    if (!invoice) return
    const chosen = (tokenArg ?? (pajTokenChoice === 'CUSTOM' ? customMint : pajTokenChoice)).trim()
    if (!chosen) {
      setPajError('Select a token or enter a valid Solana token mint address.')
      return
    }
    setPajLoading(true)
    setPajError(null)
    setPaymentError(null)
    try {
      const order = await createIntentPajOfframp(invoice.id, chosen)
      setInvoice((prev) => (prev ? { ...prev, pajOfframp: order } : prev))
      setPendingTransaction(null)
    } catch (err) {
      setPajError(err instanceof Error ? err.message : 'Could not prepare Paj Cash offramp quote.')
    } finally {
      setPajLoading(false)
    }
  }

  async function copyPajAddress(address: string) {
    try {
      await navigator.clipboard.writeText(address)
      setCopiedPajAddress(true)
      window.setTimeout(() => setCopiedPajAddress(false), 2000)
    } catch {
      setPajError('Could not copy deposit address.')
    }
  }

  async function handlePay() {
    if (!invoice || !publicKey || !connected) return
    setPaymentError(null)
    setPajError(null)
    setPaying(true)
    let paymentPhase = 'Preparing the payment'
    const isFiatSettlement = invoice.settlementTarget === 'fiat'
    let activeOrder = isFiatSettlement ? invoice.pajOfframp ?? null : null
    const isPrivatePayment = !isFiatSettlement && invoice.receiveMode === 'private'
    try {
      if (isPrivatePayment) {
        let signature = pendingPrivateSignature
        if (!signature) {
          signature = await payPrivateInvoice({
            wallet: walletContext,
            recipientAddress: invoice.recipientAddress,
            mint: invoice.mint,
            amountAtomic: BigInt(invoice.amountAtomic),
            onStatus: (message) => {
              paymentPhase = message
            },
          })
          setPendingPrivateSignature(signature)
        }

        paymentPhase = 'Confirming the private payment with Veil'
        const confirmedInvoice = await api<InvoiceData>(`/v1/payments/intents/${invoice.id}/confirm-fund`, {
          method: 'POST',
          body: JSON.stringify({ signature }),
        })
        setConfirmedSignature(null)
        setInvoice({ ...invoice, ...confirmedInvoice, status: 'funded', fundSignature: null })
        setPendingPrivateSignature(null)
        return
      }

      let pending = pendingTransaction
      if (!pending) {
        const rpcEndpoint = safeRpcEndpoint(connection.rpcEndpoint)
        let payMint = invoice.mint
        let paySymbol = KNOWN_TOKENS[invoice.mint]?.symbol ?? 'USDC'
        let payDecimals = KNOWN_TOKENS[invoice.mint]?.decimals ?? 6
        let amount = 0n
        let recipient: PublicKey

        if (isFiatSettlement) {
          if (NETWORK !== 'mainnet-beta') {
            throw new Error(
              `Paj Cash settles on Solana Mainnet, while this app is configured for ${NETWORK_LABEL[NETWORK]}. Send funds manually on Mainnet to the Paj deposit address or switch SOLANA_NETWORK to mainnet-beta.`,
            )
          }
          if (!activeOrder || !activeOrder.tokenAmount || !quoteMatchesChoice(activeOrder, pajTokenChoice, customMint)) {
            const chosen = (pajTokenChoice === 'CUSTOM' ? customMint : pajTokenChoice).trim()
            if (!chosen) {
              throw new Error('Select a token or enter a valid Solana token mint address.')
            }
            paymentPhase = `Locking ${pajTokenChoice === 'CUSTOM' ? 'token' : pajTokenChoice} offramp quote`
            const freshOrder = await createIntentPajOfframp(invoice.id, chosen)
            activeOrder = freshOrder
            setInvoice((prev) => (prev ? { ...prev, pajOfframp: freshOrder } : prev))
          }
          if (!activeOrder.tokenAmount) {
            throw new Error('Paj Cash quote did not return a token amount. Refresh the quote and try again.')
          }
          payMint = activeOrder.mint
          paySymbol = activeOrder.tokenSymbol
          payDecimals = activeOrder.tokenDecimals
          amount = decimalToAtomic(activeOrder.tokenAmount, payDecimals)
          recipient = new PublicKey(activeOrder.depositAddress)
        } else {
          const directToken = KNOWN_TOKENS[invoice.mint]
          if (!directToken) {
            throw new Error('This checkout uses a token that is not supported for direct wallet payment.')
          }
          if (directToken.network && directToken.network !== NETWORK) {
            throw new Error(
              `This payment request uses ${directToken.symbol} on ${NETWORK_LABEL[directToken.network]}, while the app is configured for ${NETWORK_LABEL[NETWORK]}.`,
            )
          }
          if (invoice.mint !== USDC_MINT && invoice.mint !== SOL_MINT) {
            throw new Error(
              `This payment request uses a different ${directToken.symbol} mint than the configured ${NETWORK_LABEL[NETWORK]} network. Ask the merchant to create a new payment link on ${NETWORK_LABEL[NETWORK]}.`,
            )
          }
          paySymbol = directToken.symbol
          payDecimals = directToken.decimals
          amount = BigInt(invoice.amountAtomic)
          recipient = new PublicKey(invoice.recipientAddress)
        }

        console.info('[Veil checkout] payment network', {
          configuredNetwork: NETWORK,
          rpcEndpoint,
          payMint,
          paySymbol,
          settlementTarget: invoice.settlementTarget ?? 'crypto',
          payer: publicKey.toBase58(),
        })

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
            `Could not reach the configured Solana RPC (${rpcEndpoint}). Check SOLANA_RPC_URL and try again.`,
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
            `The configured Solana RPC is connected to a different cluster than ${NETWORK_LABEL[NETWORK]}. Check SOLANA_NETWORK and SOLANA_RPC_URL.`,
          )
        }

        if (amount <= 0n || amount > 18_446_744_073_709_551_615n) {
          throw new Error('This payment amount is invalid.')
        }
        if (publicKey.equals(recipient)) {
          throw new Error('You cannot pay your own wallet. Ask the merchant to use a different receiving wallet.')
        }

        const instructions: TransactionInstruction[] = []
        paymentPhase = 'Checking your SOL balance'
        const payerSolLamports = BigInt(await connection.getBalance(publicKey, 'confirmed'))
        let needsDestinationAta = false
        let tokenProgramId = TOKEN_PROGRAM_ID

        if (payMint === SOL_MINT) {
          if (payerSolLamports < amount) {
            throw new Error(
              `Your wallet has ${formatAmount(payerSolLamports.toString(), 9)} SOL on ${NETWORK_LABEL[NETWORK]}, but this payment needs ${formatAmount(amount.toString(), 9)} SOL.`,
            )
          }
          if (amount > BigInt(Number.MAX_SAFE_INTEGER)) {
            throw new Error('SOL transfer amount exceeds safe integer lamport range.')
          }
          const recipientAccount = await connection.getAccountInfo(recipient, 'confirmed')
          if (!recipientAccount) {
            const minSystemRent = BigInt(await connection.getMinimumBalanceForRentExemption(0, 'confirmed'))
            if (amount < minSystemRent) {
              throw new Error(
                `This deposit address is uninitialized, so Solana requires at least ${formatAmount(minSystemRent.toString(), 9)} SOL for account rent.`,
              )
            }
          }
          instructions.push(
            SystemProgram.transfer({
              fromPubkey: publicKey,
              toPubkey: recipient,
              lamports: Number(amount),
            }),
          )
        } else {
          const mint = new PublicKey(payMint)
          const mintAccount = await connection.getAccountInfo(mint, 'confirmed')
          if (!mintAccount) {
            throw new Error(
              `The ${paySymbol} token mint (${payMint}) was not found on ${NETWORK_LABEL[NETWORK]}.`,
            )
          }
          if (mintAccount.owner.equals(TOKEN_2022_PROGRAM_ID)) {
            tokenProgramId = TOKEN_2022_PROGRAM_ID
          } else if (!mintAccount.owner.equals(TOKEN_PROGRAM_ID)) {
            throw new Error(
              `The token mint ${payMint} uses an unsupported Solana token program.`,
            )
          }

          const payerAta = await associatedTokenAddress(publicKey, mint, tokenProgramId)
          const destination = await associatedTokenAddress(recipient, mint, tokenProgramId)
          console.info('[Veil checkout] payer token account lookup', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: payMint,
            tokenProgramId: tokenProgramId.toBase58(),
            payer: publicKey.toBase58(),
            payerAta: payerAta.toBase58(),
          })
          let payerTokenAccounts: Awaited<ReturnType<typeof connection.getParsedTokenAccountsByOwner>>
          paymentPhase = `Looking up your ${paySymbol} token accounts`
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
              mint: payMint,
              payer: publicKey.toBase58(),
              payerAta: payerAta.toBase58(),
              errorType: rpcError instanceof Error ? rpcError.name : typeof rpcError,
            })
            throw new Error(
              `Could not look up your ${paySymbol} account on ${NETWORK_LABEL[NETWORK]}. The RPC request failed; check your connection and try again.`,
            )
          }
          if (payerTokenAccounts.value.length === 0) {
            console.warn('[Veil checkout] payer has no token account for mint', {
              configuredNetwork: NETWORK,
              rpcEndpoint,
              mint: payMint,
              payer: publicKey.toBase58(),
              payerAta: payerAta.toBase58(),
            })
            const fundingHint =
              payMint === USDC_MINT && NETWORK === 'devnet'
                ? 'Get test USDC from faucet.circle.com and select Solana Devnet.'
                : `Make sure the wallet holds ${paySymbol} on ${NETWORK_LABEL[NETWORK]}.`
            throw new Error(
              `No ${paySymbol} token account was found for your wallet on ${NETWORK_LABEL[NETWORK]}. Mint: ${payMint}. ${fundingHint}`,
            )
          }

          const payerAccounts = payerTokenAccounts.value.map((item) => ({
            address: item.pubkey,
            amount: BigInt(item.account.data.parsed.info.tokenAmount.amount as string),
          }))
          const sourceAccount =
            payerAccounts.find(({ address, amount: balance }) => address.equals(payerAta) && balance >= amount) ??
            payerAccounts.find(({ amount: balance }) => balance >= amount)
          if (!sourceAccount) {
            const available = payerAccounts.reduce((total, account) => total + account.amount, 0n)
            throw new Error(
              `Your wallet has ${formatAmount(available.toString(), payDecimals)} ${paySymbol} on ${NETWORK_LABEL[NETWORK]}, but this payment needs ${formatAmount(amount.toString(), payDecimals)} ${paySymbol}.`,
            )
          }
          const source = sourceAccount.address
          paymentPhase = 'Checking the destination token account'
          const destinationAccount = await connection.getAccountInfo(destination, 'confirmed')
          if (!destinationAccount) {
            needsDestinationAta = true
            instructions.push(
              createAssociatedTokenAccountIdempotentInstruction(
                publicKey,
                recipient,
                mint,
                destination,
                tokenProgramId,
              ),
            )
          }
          instructions.push(
            transferCheckedInstruction(
              source,
              destination,
              mint,
              publicKey,
              amount,
              payDecimals,
              tokenProgramId,
            ),
          )
        }

        instructions.push(
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

        let feeLamports = DEFAULT_TX_FEE_LAMPORTS
        try {
          const feeResponse = await connection.getFeeForMessage(messageV0, 'confirmed')
          if (feeResponse.value !== null) {
            feeLamports = BigInt(feeResponse.value)
          }
        } catch {
          // Fall back to standard single-signer fee if fee estimation fails.
        }

        let ataRentLamports = 0n
        if (needsDestinationAta) {
          const ataSpace = tokenProgramId.equals(TOKEN_2022_PROGRAM_ID) ? 182 : 165
          ataRentLamports = BigInt(await connection.getMinimumBalanceForRentExemption(ataSpace, 'confirmed'))
        }
        const requiredSolLamports = (payMint === SOL_MINT ? amount : 0n) + feeLamports + ataRentLamports
        if (payerSolLamports < requiredSolLamports) {
          if (payerSolLamports === 0n) {
            throw new Error(
              `Your wallet has 0 SOL on ${NETWORK_LABEL[NETWORK]} to pay Solana network fees${needsDestinationAta ? ' and create the recipient token account' : ''}. Add at least ${formatAmount(requiredSolLamports.toString(), 9)} SOL and try again.`,
            )
          }
          throw new Error(
            `Your wallet has ${formatAmount(payerSolLamports.toString(), 9)} SOL on ${NETWORK_LABEL[NETWORK]}, but needs at least ${formatAmount(requiredSolLamports.toString(), 9)} SOL${payMint === SOL_MINT ? ' (including network fees)' : needsDestinationAta ? ' for network fees and recipient token account creation' : ' for network fees'}.`,
          )
        }

        const transaction = new VersionedTransaction(messageV0)

        let simulation
        paymentPhase = 'Simulating the Solana transaction'
        try {
          simulation = await connection.simulateTransaction(transaction, { commitment: 'confirmed' })
        } catch (simulationError) {
          console.error('[Veil checkout] transaction simulation RPC failed', {
            configuredNetwork: NETWORK,
            rpcEndpoint,
            mint: payMint,
            payer: publicKey.toBase58(),
            error: simulationError,
          })
          throw new Error(
            `Could not simulate this transaction on ${NETWORK_LABEL[NETWORK]}. Check the Solana RPC and try again.`,
          )
        }

        if (simulation.value.err) {
          const logs = simulation.value.logs?.slice(-12).join('\n')
          const accountNotFoundHint = simulation.value.err === 'AccountNotFound'
            ? ` (your fee-paying wallet may have 0 SOL on ${NETWORK_LABEL[NETWORK]} or a recent deposit has not propagated to this RPC node yet)`
            : ''
          throw new Error(
            [
              `Solana simulation rejected this transaction: ${JSON.stringify(simulation.value.err)}${accountNotFoundHint}`,
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
        body: JSON.stringify({
          signature: transactionToConfirm.signature,
          ...(activeOrder ? { pajOfframpOrderId: activeOrder.id } : {}),
        }),
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

  const token = KNOWN_TOKENS[invoice.mint]
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
  const isFiatSettlement = invoice.settlementTarget === 'fiat'
  const pajOrder = invoice.pajOfframp ?? null
  const pajBadge = pajOrder ? getPajStatusPresentation(pajOrder.status) : null
  const selectedChoiceLabel = pajTokenChoice === 'CUSTOM' ? 'custom token' : pajTokenChoice
  const matchesQuote = quoteMatchesChoice(pajOrder, pajTokenChoice, customMint)
  const paidByFiat = invoice.fiatCheckout?.status === 'completed'
  const paidByPaj = pajOrder?.status === 'COMPLETED'
  const wholeNgnEligible = Boolean(
    invoice.amount_ngn && /^\d+$/.test(invoice.amount_ngn) && Number(invoice.amount_ngn) >= 1,
  )
  const bankTransferAvailable = Boolean(
    invoice.fiatCheckout ||
      (invoice.allowFiatCheckout !== false &&
        invoice.receiveMode !== 'private' &&
        wholeNgnEligible &&
        invoice.settlementTarget !== 'fiat'),
  )
  const headerTokenAmount = pajOrder?.tokenAmount ?? displayAmount
  const headerTokenSymbol = pajOrder?.tokenSymbol ?? token.symbol

  if (
    invoice.status === 'claimed' ||
    (invoice.status === 'funded' && invoice.receiveMode !== 'private')
  ) {
    return (
      <CheckoutFrame>
        <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
          <CheckCircle size={36} weight="fill" />
        </div>
        <h1 className="mt-5 text-2xl font-semibold tracking-tight text-primary">Payment complete</h1>
        <p className="mt-2 text-sm text-foreground/65">
          <Money amountNgn={invoice.amount_ngn} tokenAmount={headerTokenAmount} token={headerTokenSymbol} className="inline-flex align-middle" /> paid for “{invoice.memo || 'Payment request'}”.
        </p>
        {paidByFiat && invoice.fiatCheckout && (
          <div className="mt-5 rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 text-left text-xs text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-950/45 dark:text-emerald-200">
            <p className="font-semibold">Settled via NGN bank transfer</p>
            <p className="mt-1">
              Amount: <span className="font-mono font-medium">{formatNgn(invoice.fiatCheckout.amountPayable ?? invoice.fiatCheckout.amount)}</span>
            </p>
            <p className="mt-0.5 font-mono text-emerald-800/80 dark:text-emerald-300/80">Ref: {invoice.fiatCheckout.reference}</p>
            {invoice.settlementTarget === 'fiat' && invoice.fiatPayout && (
              <p className="mt-1 text-emerald-900/90 dark:text-emerald-200">
                Bank settlement ({invoice.fiatPayout.bankName || invoice.bankAccount?.bankName || 'Linked bank'}):{' '}
                <span className="font-medium capitalize">{invoice.fiatPayout.status}</span>
              </p>
            )}
          </div>
        )}
        {pajOrder && !paidByFiat && (
          <div className="mt-5 space-y-2 rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 text-left text-xs text-emerald-950 dark:border-emerald-500/30 dark:bg-emerald-950/45 dark:text-emerald-200">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold">
                {paidByPaj ? 'Settled via Paj Cash NGN offramp' : 'Offramp processing via Paj Cash'}
              </p>
              {pajBadge && (
                <span className={`inline-flex rounded-pill px-2 py-0.5 text-[11px] font-medium ${pajBadge.className}`}>
                  {pajBadge.label}
                </span>
              )}
            </div>
            <p>
              Sent:{' '}
              <span className="font-mono font-medium">
                {pajOrder.tokenAmount ?? displayAmount} {pajOrder.tokenSymbol}
              </span>
              {' → '}
              <span className="font-mono font-medium">{formatNgn(pajOrder.fiatAmount)}</span>
              {invoice.bankAccount ? ` (${invoice.bankAccount.bankName})` : ''}
            </p>
            <p className="truncate font-mono text-emerald-900/75 dark:text-emerald-300/80">Deposit: {pajOrder.depositAddress}</p>
            {pajError && (
              <p role="alert" className="text-red-700 dark:text-red-300">{pajError}</p>
            )}
            {!paidByPaj && (
              <Button
                size="sm"
                variant="secondary"
                loading={pajChecking}
                leftIcon={<ArrowsClockwise size={14} />}
                onClick={() => void handleReconcilePaj()}
              >
                Reconcile NGN settlement
              </Button>
            )}
          </div>
        )}
        {invoice.receiveMode !== 'private' && (confirmedSignature || invoice.fundSignature) && (
          <a
            href={solanaExplorerTxUrl(confirmedSignature || invoice.fundSignature || '')}
            target="_blank"
            rel="noreferrer"
            className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary underline underline-offset-4"
          >
            View on Solana Explorer <ArrowSquareOut size={16} />
          </a>
        )}
        <p className="mt-6 rounded-card bg-background px-4 py-3 text-xs text-foreground/55">
          {paidByFiat
            ? 'This NGN bank transfer has been verified by FossaPay. You can safely close this page.'
            : pajOrder
              ? 'This on-chain transfer settles to the merchant’s Nigerian bank account via Paj Cash. You can safely close this page.'
              : invoice.receiveMode === 'private'
                ? 'This payment was shielded using Umbra. You can safely close this page.'
                : 'This payment was made with a standard on-chain transfer. You can safely close this page.'}
        </p>
      </CheckoutFrame>
    )
  }

  if (invoice.status === 'funded' && invoice.receiveMode === 'private') {
    return (
      <CheckoutFrame>
        <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
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
              <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">
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
        {payMethod === 'bank' ? <Bank size={24} weight="fill" /> : <Wallet size={24} weight="fill" />}
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-foreground/50">Secure checkout</p>
      <Money amountNgn={invoice.amount_ngn} tokenAmount={headerTokenAmount} token={headerTokenSymbol} className="mx-auto mt-2" primaryClassName="text-4xl font-semibold tracking-tight text-primary" secondaryClassName="text-sm" />
      <p className="mt-2 text-sm text-foreground/65">{invoice.memo || 'Payment request'}</p>

      {countdown && (
        <p className={`mt-3 inline-flex rounded-pill px-3 py-1.5 text-xs font-medium tabular-nums ${expired ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-primary/5 text-primary/70'}`} role="timer">
          {expired ? 'Quote expired' : `Locked quote expires in ${countdown}`}
          {expired && pendingTransaction ? ' · confirm your submitted transfer below' : ''}
        </p>
      )}

      <div
        className={`mt-5 grid ${bankTransferAvailable ? 'grid-cols-2' : 'grid-cols-1'} gap-1 rounded-pill border border-primary/10 bg-background p-1`}
        role="tablist"
        aria-label="Payment method"
      >
        {bankTransferAvailable && (
          <button
            type="button"
            role="tab"
            aria-selected={payMethod === 'bank'}
            onClick={() => setPayMethod('bank')}
            className={`flex min-h-9 items-center justify-center gap-1.5 rounded-pill px-3 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              payMethod === 'bank' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
            }`}
          >
            <Bank size={15} weight={payMethod === 'bank' ? 'fill' : 'regular'} />
            Bank transfer
          </button>
        )}
        <button
          type="button"
          role="tab"
          aria-selected={payMethod === 'wallet'}
          onClick={() => setPayMethod('wallet')}
          className={`flex min-h-9 items-center justify-center gap-1.5 rounded-pill px-3 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            payMethod === 'wallet' ? 'bg-primary-action text-white' : 'text-foreground/65 hover:text-primary'
          }`}
        >
          <Wallet size={15} weight={payMethod === 'wallet' ? 'fill' : 'regular'} />
          Solana wallet
        </button>
      </div>

      {payMethod === 'bank' ? (
        <div className="mt-5 space-y-4">
          {fiatError && (
            <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-left text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">
              {fiatError}
            </p>
          )}
          {invoice.fiatCheckout ? (
            <BankTransferCard
              checkout={invoice.fiatCheckout}
              checkingStatus={fiatChecking}
              onCheckStatus={() => void handleReconcileFiat()}
              canGenerateNew={!expired}
              generatingNew={fiatLoading}
              onGenerateNew={() => void handleGenerateFiatCheckout()}
            />
          ) : (
            <div className="rounded-card border border-primary/10 bg-background p-4 text-left">
              <p className="text-sm font-medium text-primary">Pay in Naira via bank transfer</p>
              <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                Generate a dedicated 30-minute virtual bank account from FossaPay for this payment.
              </p>
              <Button
                className="mt-4"
                size="lg"
                fullWidth
                loading={fiatLoading}
                disabled={expired || !wholeNgnEligible}
                leftIcon={<Bank size={18} weight="fill" />}
                onClick={() => void handleGenerateFiatCheckout()}
              >
                Get bank transfer account
              </Button>
            </div>
          )}
        </div>
      ) : (
        <>
          {isFiatSettlement ? (
            <div className="my-5 space-y-4 text-left">
              <div className="rounded-card border border-primary/10 bg-background p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-primary">Pay with any Solana token</p>
                  <span className="rounded-pill bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary">
                    NGN settlement (Paj Cash)
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-foreground/60">
                  Pick a token to lock an offramp quote. The merchant receives{' '}
                  <span className="font-mono font-medium text-foreground">{formatNgn(invoice.amount_ngn)}</span>
                  {invoice.bankAccount ? ` in ${invoice.bankAccount.bankName}` : ' in NGN'}.
                </p>

                <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Solana payment token">
                  {PAJ_TOKENS.map((symbol) => (
                    <button
                      key={symbol}
                      type="button"
                      aria-pressed={pajTokenChoice === symbol}
                      onClick={() => setPajTokenChoice(symbol)}
                      className={`min-h-8 rounded-pill border px-3 text-xs font-semibold transition-colors ${
                        pajTokenChoice === symbol
                          ? 'border-primary-action bg-primary-action text-white'
                          : 'border-primary/15 bg-surface text-foreground/70 hover:border-primary/35 hover:text-primary'
                      }`}
                    >
                      {symbol}
                    </button>
                  ))}
                  <button
                    type="button"
                    aria-pressed={pajTokenChoice === 'CUSTOM'}
                    onClick={() => setPajTokenChoice('CUSTOM')}
                    className={`min-h-8 rounded-pill border px-3 text-xs font-semibold transition-colors ${
                      pajTokenChoice === 'CUSTOM'
                        ? 'border-primary-action bg-primary-action text-white'
                        : 'border-primary/15 bg-surface text-foreground/70 hover:border-primary/35 hover:text-primary'
                    }`}
                  >
                    Custom mint
                  </button>
                </div>

                {pajTokenChoice === 'CUSTOM' && (
                  <div className="mt-3">
                    <label htmlFor="custom-paj-mint" className="sr-only">Solana token mint address</label>
                    <input
                      id="custom-paj-mint"
                      type="text"
                      value={customMint}
                      onChange={(event) => setCustomMint(event.target.value)}
                      placeholder="Paste Solana SPL mint address"
                      className="h-10 w-full rounded-card border border-primary/15 bg-surface px-3 font-mono text-xs outline-none transition focus:border-primary/40 focus:ring-2 focus:ring-primary/10"
                    />
                  </div>
                )}

                <Button
                  className="mt-3"
                  size="sm"
                  fullWidth
                  variant={matchesQuote ? 'secondary' : 'primary'}
                  loading={pajLoading}
                  disabled={expired}
                  onClick={() => void handleCreatePajOrder()}
                >
                  {!pajOrder
                    ? `Get ${selectedChoiceLabel} payment quote`
                    : matchesQuote
                      ? `Refresh ${selectedChoiceLabel} quote`
                      : `Update quote for ${selectedChoiceLabel}`}
                </Button>
              </div>

              {pajError && (
                <p role="alert" className="rounded-card bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">
                  {pajError}
                </p>
              )}

              {pajOrder && pajBadge && (
                <div className="space-y-3 rounded-card border border-primary/15 bg-surface p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-xs text-foreground/55">Send exact amount</p>
                      <p className="font-mono text-lg font-semibold tabular-nums text-primary">
                        {pajOrder.tokenAmount ?? '—'} {pajOrder.tokenSymbol}
                      </p>
                    </div>
                    <span className={`inline-flex rounded-pill px-2.5 py-0.5 text-xs font-medium ${pajBadge.className}`}>
                      {pajBadge.label}
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-foreground/60">
                    <span>NGN value: <span className="font-mono font-medium text-foreground">{formatNgn(pajOrder.fiatAmount)}</span></span>
                    {pajOrder.rate && (
                      <span className="font-mono tabular-nums">Rate ₦{pajOrder.rate}/USD</span>
                    )}
                    {pajOrder.feeUsdc && (
                      <span className="font-mono tabular-nums">Fee {pajOrder.feeUsdc} USDC</span>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-2 rounded-card border border-primary/10 bg-background px-3 py-2">
                    <div className="min-w-0">
                      <p className="text-[11px] uppercase tracking-wider text-foreground/50">
                        {IS_MAINNET
                          ? 'Paj Cash Solana Mainnet deposit address'
                          : 'Paj Cash deposit address (Solana Mainnet only)'}
                      </p>
                      <p className="truncate font-mono text-xs text-primary">{pajOrder.depositAddress}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void copyPajAddress(pajOrder.depositAddress)}
                      leftIcon={copiedPajAddress ? <CheckCircle size={14} /> : <Copy size={14} />}
                    >
                      {copiedPajAddress ? 'Copied' : 'Copy'}
                    </Button>
                  </div>

                  {NETWORK !== 'mainnet-beta' && (
                    <p role="status" className="rounded-card border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200">
                      Paj Cash settles on Solana Mainnet, while this app is configured for {NETWORK_LABEL[NETWORK]}.
                      Send {pajOrder.tokenAmount ?? ''} {pajOrder.tokenSymbol} on Mainnet to the deposit address above,
                      then click Reconcile status.
                    </p>
                  )}

                  <Button
                    size="sm"
                    variant="secondary"
                    fullWidth
                    loading={pajChecking}
                    leftIcon={<ArrowsClockwise size={14} />}
                    onClick={() => void handleReconcilePaj()}
                  >
                    Reconcile status
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="my-5 rounded-card border border-primary/10 bg-background p-4 text-left">
              <div className="flex items-start gap-2 text-sm text-foreground/70">
                {invoice.receiveMode === 'private'
                  ? <ShieldCheck className="mt-0.5 shrink-0 text-amber-600" size={17} />
                  : <GlobeHemisphereWest className="mt-0.5 shrink-0 text-primary" size={17} />}
                <p>
                  {invoice.receiveMode === 'private'
                    ? 'This payment is shielded via Umbra. Your wallet and payment details are not publicly linked to the merchant. The sender wallet and amount remain visible in the Umbra deposit transaction.'
                    : 'This payment is sent as a standard on-chain transfer. Transaction details are visible on the blockchain.'}
                </p>
              </div>
            </div>
          )}

          {paymentError && (
            <p role="alert" className="mb-4 whitespace-pre-line rounded-card bg-red-50 px-3 py-2 text-left text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">
              {pendingTransaction || pendingPrivateSignature
                ? 'Payment sent, but confirmation is pending. Retry to finish confirmation. '
                : ''}
              {paymentError}
              {IS_DEVNET && paymentError.includes('No USDC token account') && (
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
            <p role="alert" className="mb-4 rounded-card bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/45 dark:text-red-300">{connectError}</p>
          )}

          {publicKey && connected ? (
            <div className="space-y-3">
              <p className="text-xs text-foreground/55">
                Connected: {wallet?.adapter.name ?? 'Wallet'} · {truncateAddress(publicKey.toBase58())}
              </p>
              <p className="text-xs text-foreground/45" title={`Active mint: ${isFiatSettlement && pajOrder ? pajOrder.mint : invoice.mint}`}>
                This payment uses Solana {NETWORK_LABEL[NETWORK]}. If your wallet reports a network error, switch it to {NETWORK_LABEL[NETWORK]}.
              </p>
              <Button
                size="lg"
                fullWidth
                loading={paying}
                onClick={() => void handlePay()}
                disabled={
                  (expired && !pendingTransaction && !pendingPrivateSignature) ||
                  (isFiatSettlement &&
                    (NETWORK !== 'mainnet-beta' || (pajTokenChoice === 'CUSTOM' && !customMint.trim())))
                }
              >
                {pendingTransaction || pendingPrivateSignature
                  ? 'Retry payment confirmation'
                  : isFiatSettlement
                    ? matchesQuote && pajOrder?.tokenAmount
                      ? `Pay ${pajOrder.tokenAmount} ${pajOrder.tokenSymbol} now`
                      : `Pay with ${selectedChoiceLabel} now`
                    : `Pay ${displayAmount} ${token.symbol} now`}
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
                  className="flex w-full items-center gap-3 rounded-card border border-primary/15 bg-surface px-4 py-3 text-left text-sm font-medium transition hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
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
        </>
      )}

      <p className="mt-6 text-xs text-foreground/45">No Veil account needed · Powered by Veil</p>
    </CheckoutFrame>
  )
}

function CheckoutFrame({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-[calc(100dvh-4rem)] items-center justify-center bg-background px-4 py-10">
      <section className="w-full max-w-md rounded-panel border border-primary/10 bg-surface p-6 text-center shadow-veil-md sm:p-8">
        {children}
      </section>
    </main>
  )
}
