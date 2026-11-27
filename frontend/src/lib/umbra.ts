import {
  address,
  getTransactionDecoder,
  getTransactionEncoder,
  type Address,
} from '@solana/kit'
import { createSignerFromWalletAccount, getUmbraClient } from '@umbra-privacy/sdk'
import {
  getATAIntoETADirectDepositorFunction,
  getATAIntoReceiverBurnableStealthPoolNoteCreatorFunction,
} from '@umbra-privacy/sdk/deposit'
import { getUserRegistrationFunction } from '@umbra-privacy/sdk/registration'
import { createU64 } from '@umbra-privacy/sdk/types'
import { getATAIntoStealthPoolNoteCreatorProver } from '@umbra-privacy/sdk/zk-prover'
import type { WalletContextState } from '@solana/wallet-adapter-react'
import { clusterApiUrl, Connection, PublicKey } from '@solana/web3.js'


import { NETWORK, NETWORK_LABEL, SOLANA_GENESIS_HASH, SOLANA_RPC_URL, USDC_MINT } from './network'

const RPC_URL = SOLANA_RPC_URL || clusterApiUrl(NETWORK)
const WS_URL =
  process.env.SOLANA_WS_URL || RPC_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')

export const UMBRA_MINTS: Record<string, Address> = {
  SOL: address('So11111111111111111111111111111111111111112'),
  USDC: address(USDC_MINT),
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

interface PrivateInvoiceParams {
  wallet: WalletContextState
  recipientAddress: string
  mint: string
  amountAtomic: bigint
  onStatus?: (message: string) => void
}

interface RegisterUmbraRecipientParams {
  wallet: WalletContextState
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
  const chain: `${string}:${string}` = NETWORK === 'mainnet-beta'
    ? 'solana:mainnet'
    : 'solana:devnet'

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

async function createClient(wallet: WalletContextState) {
  const signer = buildBrowserSigner(wallet)
  const client = await getUmbraClient({
    network: NETWORK === 'mainnet-beta' ? 'mainnet' : 'devnet',
    rpcUrl: RPC_URL,
    rpcSubscriptionsUrl: WS_URL,
    signer,
  })
  return { client, signer }
}

function formatTokenAmount(amount: bigint, decimals: number): string {
  const scale = 10n ** BigInt(decimals)
  const whole = (amount / scale).toString()
  const fraction = (amount % scale).toString().padStart(decimals, '0').replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}

async function checkBalances(
  wallet: WalletContextState,
  token: FundVaultParams['token'],
  requiredTokenAtomic: bigint,
): Promise<void> {
  const publicKey = wallet.publicKey
  if (!publicKey) throw new Error('Connect a wallet before funding payroll.')

  const connection = new Connection(RPC_URL, 'confirmed')
  const owner = new PublicKey(publicKey.toBase58())
  const mintAddress = UMBRA_MINTS[token]
  if (!mintAddress) {
    throw new Error(`Umbra ${NETWORK_LABEL[NETWORK]} does not support ${token} deposits.`)
  }
  const mint = new PublicKey(mintAddress)
  const [tokenAta] = await PublicKey.findProgramAddress(
    [owner.toBytes(), TOKEN_PROGRAM_ID.toBytes(), mint.toBytes()],
    ASSOCIATED_TOKEN_PROGRAM_ID,
  )

  let nativeLamports: bigint
  let tokenAtomic = 0n
  const wrongClusterMessage = `Umbra requires a ${NETWORK_LABEL[NETWORK]} RPC. The configured RPC is connected to a different Solana cluster.`
  try {
    const genesisHash = await connection.getGenesisHash()
    if (genesisHash !== SOLANA_GENESIS_HASH[NETWORK]) {
      throw new Error(wrongClusterMessage)
    }
    const balance = await connection.getBalance(owner, 'confirmed')
    nativeLamports = BigInt(balance)
    const ataInfo = await connection.getAccountInfo(tokenAta, 'confirmed')
    if (ataInfo) {
      const tokenBalance = await connection.getTokenAccountBalance(tokenAta, 'confirmed')
      tokenAtomic = BigInt(tokenBalance.value.amount)
    }
  } catch (error) {
    console.error('[Umbra] Balance preflight failed', error)
    if (error instanceof Error && error.message === wrongClusterMessage) {
      throw error
    }
    throw new Error(`Could not check your SOL and ${token} balances. Check the Solana RPC and retry.`)
  }

  const decimals = token === 'USDC' ? 6 : 9
  if (tokenAtomic < requiredTokenAtomic) {
    throw new Error(
      `Not enough ${token} in your wallet ATA. Current: ${formatTokenAmount(tokenAtomic, decimals)} ${token}; required: ${formatTokenAmount(requiredTokenAtomic, decimals)} ${token}.`,
    )
  }
  if (nativeLamports < MIN_NATIVE_SOL_LAMPORTS) {
    throw new Error(
      `Low SOL balance: ${formatTokenAmount(nativeLamports, 9)} SOL. Umbra registration and transaction fees may need at least 0.05 SOL; fund this wallet and retry.`,
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

/** Ensures a merchant can receive Umbra notes at their registered wallet address. */
export async function registerUmbraRecipient({
  wallet,
  onStatus,
}: RegisterUmbraRecipientParams): Promise<void> {
  const { client } = await createClient(wallet)
  onStatus?.('Preparing your private receiving account...')
  const register = getUserRegistrationFunction({ client })
  try {
    await register({ confidential: true, anonymous: false })
  } catch (error) {
    throw diagnoseUmbraError('Umbra private receiving account registration', error)
  }
}

/** Sends USDC into Umbra with the recipient's registered account as the note owner. */
export async function payPrivateInvoice({
  wallet,
  recipientAddress,
  mint,
  amountAtomic,
  onStatus,
}: PrivateInvoiceParams): Promise<string> {
  if (mint !== UMBRA_MINTS.USDC) {
    throw new Error(`Private checkout supports only ${NETWORK_LABEL[NETWORK]} USDC.`)
  }
  if (amountAtomic <= 0n) {
    throw new Error('Private payment amount must be greater than zero.')
  }

  onStatus?.('Checking SOL and USDC balances...')
  await checkBalances(wallet, 'USDC', amountAtomic)
  const { client } = await createClient(wallet)
  onStatus?.('Preparing the shielded Umbra transfer...')

  const createNote = getATAIntoReceiverBurnableStealthPoolNoteCreatorFunction(
    { client },
    { zkProver: getATAIntoStealthPoolNoteCreatorProver() },
  )
  let result
  try {
    result = await createNote(
      {
        amount: createU64({ value: amountAtomic }),
        destinationAddress: address(recipientAddress),
        mint: address(mint),
      },
      {
        hooks: {
          onZkProofGenerationStart: async () => {
            onStatus?.('Generating the Umbra shielded-transfer proof...')
          },
        },
      },
    )
  } catch (error) {
    throw diagnoseUmbraError('Umbra private invoice payment', error)
  }
  if (!result.createUtxoSignature) {
    throw new Error('Umbra private payment did not return a confirmed transaction signature.')
  }
  return String(result.createUtxoSignature)
}

/** Registers the employer and deposits payroll funds into their Umbra ETA. */
export async function fundPayrollVault({
  wallet,
  token,
  totalAmountAtomic,
  onStatus,
}: FundVaultParams): Promise<string> {
  const mint = UMBRA_MINTS[token]
  if (!mint) {
    throw new Error(`Umbra ${NETWORK_LABEL[NETWORK]} does not support ${token} deposits.`)
  }
  if (totalAmountAtomic <= 0n) {
    throw new Error('Total payroll amount must be greater than zero.')
  }

  onStatus?.(`Checking SOL and ${token} balances...`)
  await checkBalances(wallet, token, totalAmountAtomic)

  onStatus?.(`Initializing Umbra ${NETWORK_LABEL[NETWORK]} client...`)
  const { client, signer } = await createClient(wallet)

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
    throw diagnoseUmbraError(`Umbra ${token} deposit`, error)
  }
  if (!result.queueSignature) {
    throw new Error('Umbra deposit did not return a transaction signature.')
  }
  return String(result.queueSignature)
}
