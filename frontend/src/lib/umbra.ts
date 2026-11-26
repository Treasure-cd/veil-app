import {
  address,
  getTransactionDecoder,
  getTransactionEncoder,
  type Address,
} from '@solana/kit'
import { createSignerFromWalletAccount, getUmbraClient } from '@umbra-privacy/sdk'
import { getATAIntoETADirectDepositorFunction } from '@umbra-privacy/sdk/deposit'
import { getUserRegistrationFunction } from '@umbra-privacy/sdk/registration'
import { createU64 } from '@umbra-privacy/sdk/types'
import type { WalletContextState } from '@solana/wallet-adapter-react'
import { clusterApiUrl, Connection, PublicKey } from '@solana/web3.js'


import { NETWORK, SOLANA_GENESIS_HASH, SOLANA_RPC_URL } from './network'

const DEVNET_RPC_URL = SOLANA_RPC_URL || clusterApiUrl('devnet')
const DEVNET_WS_URL =
  process.env.SOLANA_WS_URL || DEVNET_RPC_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')

// Umbra devnet currently supports wSOL only.
export const UMBRA_DEVNET_MINTS: Record<string, Address> = {
  SOL: address('So11111111111111111111111111111111111111112'),
}

const TOKEN_PROGRAM_ID = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
const ASSOCIATED_TOKEN_PROGRAM_ID = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
const MIN_NATIVE_SOL_LAMPORTS = 50_000_000n

export interface FundVaultParams {
  wallet: WalletContextState
  token: 'USDC' | 'SOL'
  totalAmountAtomic: bigint
  onStatus?: (message: string) => void
}

function buildBrowserSigner(wallet: WalletContextState) {
  const adapter = wallet.wallet?.adapter
  if (!wallet.publicKey || !adapter || !('wallet' in adapter)) {
    throw new Error('Connected wallet must support Wallet Standard transaction and message signing.')
  }

  const standardWallet = adapter.wallet
  const walletAccount = standardWallet.accounts.find(
    account => account.address === wallet.publicKey?.toBase58(),
  )
  if (!walletAccount) {
    throw new Error('The connected account is not available from the selected Wallet Standard wallet.')
  }

  const baseSigner = createSignerFromWalletAccount({ wallet: standardWallet, account: walletAccount })
  const features = standardWallet.features as Record<string, unknown>
  const signTransactionFeature = features['solana:signTransaction'] as
    | {
        signTransaction: (
          ...inputs: Array<{
            account: typeof walletAccount
            transaction: Uint8Array
            chain?: `${string}:${string}`
          }>
        ) => Promise<Array<{ signedTransaction: Uint8Array }>>
      }
    | undefined

  if (!signTransactionFeature) {
    return baseSigner
  }

  const txEncoder = getTransactionEncoder()
  const txDecoder = getTransactionDecoder()
  const chain = `solana:${NETWORK}` as `${string}:${string}`

  const signWithWallet = async (tx: any) => {
    const [output] = await signTransactionFeature.signTransaction({
      account: walletAccount,
      transaction: new Uint8Array(txEncoder.encode(tx)),
      chain,
    })
    const decoded = txDecoder.decode(output.signedTransaction)
    return {
      ...tx,
      messageBytes: decoded.messageBytes,
      signatures: decoded.signatures,
    }
  }

  return {
    ...baseSigner,
    signTransaction: signWithWallet,
    async signTransactions(txs: readonly any[]) {
      const inputs = txs.map(tx => ({
        account: walletAccount,
        transaction: new Uint8Array(txEncoder.encode(tx)),
        chain,
      }))
      const outputs = await signTransactionFeature.signTransaction(...inputs)
      return outputs.map((output, i) => {
        const decoded = txDecoder.decode(output.signedTransaction)
        return {
          ...txs[i],
          messageBytes: decoded.messageBytes,
          signatures: decoded.signatures,
        }
      })
    },
  }
}

function formatTokenAmount(amount: bigint, decimals: number): string {
  const scale = 10n ** BigInt(decimals)
  const whole = (amount / scale).toString()
  const fraction = (amount % scale).toString().padStart(decimals, '0').replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}

async function checkDevnetBalances(
  wallet: WalletContextState,
  requiredWsol: bigint,
): Promise<void> {
  const publicKey = wallet.publicKey
  if (!publicKey) throw new Error('Connect a wallet before funding payroll.')

  const connection = new Connection(DEVNET_RPC_URL, 'confirmed')
  const owner = new PublicKey(publicKey.toBase58())
  const mint = new PublicKey(UMBRA_DEVNET_MINTS.SOL)
  const [wsolAta] = await PublicKey.findProgramAddress(
    [owner.toBytes(), TOKEN_PROGRAM_ID.toBytes(), mint.toBytes()],
    ASSOCIATED_TOKEN_PROGRAM_ID,
  )

  let nativeLamports: bigint
  let wsolAtomic = 0n
  try {
    const genesisHash = await connection.getGenesisHash()
    if (genesisHash !== SOLANA_GENESIS_HASH.devnet) {
      throw new Error('Payroll requires a Devnet RPC. The configured RPC is connected to a different Solana cluster.')
    }
    const balance = await connection.getBalance(owner, 'confirmed')
    nativeLamports = BigInt(balance)
    const ataInfo = await connection.getAccountInfo(wsolAta, 'confirmed')
    if (ataInfo) {
      const tokenBalance = await connection.getTokenAccountBalance(wsolAta, 'confirmed')
      wsolAtomic = BigInt(tokenBalance.value.amount)
    }
  } catch (error) {
    console.error('[Umbra] Devnet balance preflight failed', error)
    if (error instanceof Error && error.message.startsWith('Payroll requires a Devnet RPC.')) {
      throw error
    }
    throw new Error('Could not check your devnet SOL and wSOL balances. Check the Solana RPC and retry.')
  }

  if (wsolAtomic < requiredWsol) {
    throw new Error(
      `Not enough wSOL in your wallet ATA. Current: ${formatTokenAmount(wsolAtomic, 9)} wSOL; required: ${formatTokenAmount(requiredWsol, 9)} wSOL.`,
    )
  }
  if (nativeLamports < MIN_NATIVE_SOL_LAMPORTS) {
    throw new Error(
      `Low devnet SOL balance: ${formatTokenAmount(nativeLamports, 9)} SOL. Umbra registration and transaction fees may need at least 0.05 SOL; fund this wallet and retry.`,
    )
  }
}

function collectSimulationLogs(error: unknown): string[] {
  const logs: string[] = []
  const visited = new Set<object>()
  const visit = (value: unknown, depth: number) => {
    if (depth > 6 || value === null || typeof value !== 'object' || visited.has(value)) return
    visited.add(value)
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'string') logs.push(item)
        else visit(item, depth + 1)
      }
      return
    }
    for (const [key, nested] of Object.entries(value)) {
      if (/logs?/i.test(key) && Array.isArray(nested)) {
        for (const line of nested) {
          if (typeof line === 'string') logs.push(line)
          else visit(line, depth + 1)
        }
      } else if (/cause|simulation|value|data|context|err|error|response/i.test(key)) {
        visit(nested, depth + 1)
      }
    }
  }
  visit(error, 0)
  return [...new Set(logs)]
}

function diagnoseUmbraError(stage: string, error: unknown): Error {
  const errorObject = error !== null && typeof error === 'object'
    ? error as Record<string, unknown>
    : null
  const logs = collectSimulationLogs(error)
  console.error(`[Umbra] ${stage} failed; full error object:`, error)
  console.error(`[Umbra] ${stage} err.logs:`, errorObject?.logs)
  console.error(`[Umbra] ${stage} err.cause:`, errorObject?.cause)
  console.error(`[Umbra] ${stage} nested RPC simulation logs:`, logs)

  const firstMeaningfulLog = logs.find(line =>
    /program log:|custom program error|\berror\b|\bfailed\b/i.test(line) &&
    !/program (?:[1-9A-HJ-NP-Za-km-z]+ )?(?:invoke|success|consumed)/i.test(line),
  )
  const message = error instanceof Error ? error.message : String(error)
  return new Error(`${stage}: ${firstMeaningfulLog ?? message}`)
}

/** Registers the employer and deposits payroll funds into their Umbra ETA. */
export async function fundPayrollVault({
  wallet,
  token,
  totalAmountAtomic,
  onStatus,
}: FundVaultParams): Promise<string> {
  if (NETWORK !== 'devnet') {
    throw new Error('Payroll vault funding is only supported on Solana Devnet; Umbra mainnet support is not configured.')
  }

  const mint = UMBRA_DEVNET_MINTS[token]
  if (!mint) {
    throw new Error('Umbra devnet currently supports SOL (wSOL) only. Select SOL to test on devnet.')
  }
  if (totalAmountAtomic <= 0n) {
    throw new Error('Total payroll amount must be greater than zero.')
  }

  onStatus?.('Checking devnet SOL and wSOL balances...')
  await checkDevnetBalances(wallet, totalAmountAtomic)

  const signer = buildBrowserSigner(wallet)
  onStatus?.('Initializing Umbra devnet client...')
  const client = await getUmbraClient({
    network: 'devnet',
    rpcUrl: DEVNET_RPC_URL,
    rpcSubscriptionsUrl: DEVNET_WS_URL,
    signer,
  })

  onStatus?.('Checking Umbra account registration...')
  // The SDK checks the on-chain registration bits and skips completed steps.
  // Payroll deposits need confidential ETA setup only; anonymous registration is unnecessary here.
  const register = getUserRegistrationFunction({ client })
  try {
    await register({ confidential: true, anonymous: false })
  } catch (error) {
    throw diagnoseUmbraError('Umbra confidential registration', error)
  }

  onStatus?.('Depositing payroll funds into Umbra encrypted vault...')
  const deposit = getATAIntoETADirectDepositorFunction({ client })
  let result
  try {
    // SDK preparation completes before executeCorePipeline fetches a fresh blockhash,
    // then compiles and signs the transaction, avoiding proof/preparation expiry.
    result = await deposit(signer.address, mint, createU64({ value: totalAmountAtomic }))
  } catch (error) {
    throw diagnoseUmbraError('Umbra wSOL deposit', error)
  }
  if (!result.queueSignature) {
    throw new Error('Umbra deposit did not return a transaction signature.')
  }
  return String(result.queueSignature)
}
