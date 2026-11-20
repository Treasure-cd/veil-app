import { address, type Address } from '@solana/kit'
import { createSignerFromWalletAccount, getUmbraClient } from '@umbra-privacy/sdk'
import { getATAIntoETADirectDepositorFunction } from '@umbra-privacy/sdk/deposit'
import { getUserRegistrationFunction } from '@umbra-privacy/sdk/registration'
import { createU64 } from '@umbra-privacy/sdk/types'
import { getUserRegistrationProver } from '@umbra-privacy/sdk/zk-prover'
import type { WalletContextState } from '@solana/wallet-adapter-react'

const DEVNET_RPC_URL =
  import.meta.env.VITE_SOLANA_RPC_URL || 'https://api.devnet.solana.com'
const DEVNET_WS_URL =
  import.meta.env.VITE_SOLANA_WS_URL || 'wss://api.devnet.solana.com'

// Umbra devnet currently supports wSOL only.
export const UMBRA_DEVNET_MINTS: Record<string, Address> = {
  SOL: address('So11111111111111111111111111111111111111112'),
}

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

  return createSignerFromWalletAccount({ wallet: standardWallet, account: walletAccount })
}

/** Registers the employer and deposits payroll funds into their Umbra ETA. */
export async function fundPayrollVault({
  wallet,
  token,
  totalAmountAtomic,
  onStatus,
}: FundVaultParams): Promise<string> {
  const mint = UMBRA_DEVNET_MINTS[token]
  if (!mint) {
    throw new Error('Umbra devnet currently supports SOL (wSOL) only. Select SOL to test on devnet.')
  }
  if (totalAmountAtomic <= 0n) {
    throw new Error('Total payroll amount must be greater than zero.')
  }

  const signer = buildBrowserSigner(wallet)
  onStatus?.('Initializing Umbra devnet client...')
  const client = await getUmbraClient({
    network: 'devnet',
    rpcUrl: DEVNET_RPC_URL,
    rpcSubscriptionsUrl: DEVNET_WS_URL,
    signer,
  })

  onStatus?.('Checking Umbra account registration...')
  const register = getUserRegistrationFunction(
    { client },
    { zkProver: getUserRegistrationProver() },
  )
  await register({ confidential: true })

  onStatus?.('Depositing payroll funds into Umbra encrypted vault...')
  const deposit = getATAIntoETADirectDepositorFunction({ client })
  const result = await deposit(
    signer.address,
    mint,
    createU64({ value: totalAmountAtomic }),
  )
  if (!result.queueSignature) {
    throw new Error('Umbra deposit did not return a transaction signature.')
  }
  return String(result.queueSignature)
}
