import unittest
from pydantic import ValidationError

from core.config import (
    DEVNET_RPC_URL,
    DEVNET_USDC_MINT,
    MAINNET_RPC_URL,
    MAINNET_USDC_MINT,
    NATIVE_SOL_MINT,
    Settings,
)


BASE_SECRETS = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "JWT_SECRET": "test-jwt-secret-at-least-32-chars-long",
    "FOSSAPAY_API_KEY": "fk_test_key",
    "FOSSAPAY_SECRET": "test_secret",
    "FOSSAPAY_WEBHOOK_SECRET": "whsec_test_secret",
}


class SettingsNetworkTests(unittest.TestCase):
    def test_defaults_to_mainnet_when_network_omitted(self) -> None:
        cfg = Settings(_env_file=None, **BASE_SECRETS)
        self.assertEqual(cfg.SOLANA_NETWORK, "mainnet-beta")
        self.assertEqual(cfg.SOLANA_RPC_URL, MAINNET_RPC_URL)
        self.assertEqual(cfg.USDC_MINT, MAINNET_USDC_MINT)
        self.assertEqual(cfg.SOL_MINT, NATIVE_SOL_MINT)
        self.assertTrue(cfg.is_mainnet)

    def test_mainnet_alias_normalizes_and_derives_defaults(self) -> None:
        cfg = Settings(_env_file=None, SOLANA_NETWORK="mainnet", **BASE_SECRETS)
        self.assertEqual(cfg.SOLANA_NETWORK, "mainnet-beta")
        self.assertEqual(cfg.SOLANA_RPC_URL, MAINNET_RPC_URL)
        self.assertEqual(cfg.USDC_MINT, MAINNET_USDC_MINT)

    def test_devnet_derives_devnet_rpc_and_usdc_mint(self) -> None:
        cfg = Settings(_env_file=None, SOLANA_NETWORK="devnet", **BASE_SECRETS)
        self.assertEqual(cfg.SOLANA_NETWORK, "devnet")
        self.assertEqual(cfg.SOLANA_RPC_URL, DEVNET_RPC_URL)
        self.assertEqual(cfg.USDC_MINT, DEVNET_USDC_MINT)
        self.assertFalse(cfg.is_mainnet)

    def test_explicit_rpc_and_mint_overrides_are_preserved(self) -> None:
        custom_rpc = "https://rpc.example.com"
        cfg = Settings(
            _env_file=None,
            SOLANA_NETWORK="devnet",
            SOLANA_RPC_URL=custom_rpc,
            USDC_MINT=MAINNET_USDC_MINT,
            **BASE_SECRETS,
        )
        self.assertEqual(cfg.SOLANA_NETWORK, "devnet")
        self.assertEqual(cfg.SOLANA_RPC_URL, custom_rpc)
        self.assertEqual(cfg.USDC_MINT, MAINNET_USDC_MINT)

    def test_invalid_network_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, SOLANA_NETWORK="testnet", **BASE_SECRETS)

    def test_whatsapp_defaults_to_usdc_and_fossapay_without_private_payments(self) -> None:
        cfg = Settings(_env_file=None, **BASE_SECRETS)
        self.assertEqual(cfg.whatsapp_payment_methods, {"usdc", "fossapay"})
        self.assertFalse(cfg.WHATSAPP_PRIVATE_PAYMENTS)

    def test_whatsapp_can_be_configured_for_usdc_only_and_private_payments(self) -> None:
        cfg = Settings(
            _env_file=None,
            WHATSAPP_PAYMENT_METHODS="USDC",
            WHATSAPP_PRIVATE_PAYMENTS=True,
            **BASE_SECRETS,
        )
        self.assertEqual(cfg.whatsapp_payment_methods, {"usdc"})
        self.assertTrue(cfg.WHATSAPP_PRIVATE_PAYMENTS)

    def test_private_whatsapp_payments_reject_fossapay(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                WHATSAPP_PRIVATE_PAYMENTS=True,
                **BASE_SECRETS,
            )

    def test_whatsapp_payment_methods_require_usdc(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                WHATSAPP_PAYMENT_METHODS="fossapay",
                **BASE_SECRETS,
            )


if __name__ == "__main__":
    unittest.main()
