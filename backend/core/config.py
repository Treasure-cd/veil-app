from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices, field_validator, model_validator
from functools import lru_cache
from typing import List
import dotenv

dotenv.load_dotenv()

MAINNET_RPC_URL = "https://api.mainnet-beta.solana.com"
DEVNET_RPC_URL = "https://api.devnet.solana.com"
MAINNET_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEVNET_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )

    PORT: int = Field(default=8000)
    DATABASE_URL: str = Field(validation_alias=AliasChoices("DATABASE_URL_DEV", "DATABASE_URL"))
    SQL_ECHO: bool = Field(default=False)
    SOLANA_NETWORK: str = Field(default="mainnet-beta")
    SOLANA_RPC_URL: str = Field(default="")
    USDC_MINT: str = Field(default="")
    SOL_MINT: str = Field(default=NATIVE_SOL_MINT)

    @model_validator(mode="after")
    def _resolve_solana_network_defaults(self) -> "Settings":
        raw = (self.SOLANA_NETWORK or "").strip().lower()
        if raw in ("", "mainnet", "mainnet-beta"):
            self.SOLANA_NETWORK = "mainnet-beta"
            if not (self.SOLANA_RPC_URL or "").strip():
                self.SOLANA_RPC_URL = MAINNET_RPC_URL
            if not (self.USDC_MINT or "").strip():
                self.USDC_MINT = MAINNET_USDC_MINT
        elif raw == "devnet":
            self.SOLANA_NETWORK = "devnet"
            if not (self.SOLANA_RPC_URL or "").strip():
                self.SOLANA_RPC_URL = DEVNET_RPC_URL
            if not (self.USDC_MINT or "").strip():
                self.USDC_MINT = DEVNET_USDC_MINT
        else:
            raise ValueError("SOLANA_NETWORK must be 'mainnet-beta', 'mainnet', or 'devnet'")
        if not (self.SOL_MINT or "").strip():
            self.SOL_MINT = NATIVE_SOL_MINT
        return self

    @property
    def is_mainnet(self) -> bool:
        return self.SOLANA_NETWORK == "mainnet-beta"

    @property
    def known_usdc_mints(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.USDC_MINT, MAINNET_USDC_MINT, DEVNET_USDC_MINT)))
    RATE_NGN_PER_SOL: float | None = Field(default=None)
    RATE_NGN_PER_USDC: float | None = Field(default=None)
    
    ALLOWED_ORIGINS: str = Field(default="http://localhost:5173")
    
    WASENDER_API_KEY: str | None = Field(default=None)
    TWILIO_ACCOUNT_SID: str | None = Field(default=None)
    TWILIO_AUTH_TOKEN: str | None = Field(default=None)
    TWILIO_CONTENT_SID: str | None = Field(default=None)
    WEBHOOK_PUBLIC_URL: str | None = Field(default=None)
    FRONTEND_URL: str = Field(default="https://yourveil.vercel.app")
    TWILIO_WHATSAPP_FROM: str | None = Field(default=None)
    TWILIO_SANDBOX_JOIN_CODE: str | None = Field(default=None)
    WHATSAPP_DEMO_MODE: str = Field(default="false")
    WHATSAPP_DEMO_MAX_NUMBERS: int = Field(default=10, ge=0)
    WHATSAPP_DEMO_MERCHANT_WALLET: str | None = Field(default=None)
    WHATSAPP_PAYMENT_METHODS: str = Field(default="usdc,fossapay")
    WHATSAPP_PRIVATE_PAYMENTS: bool = Field(default=False)
    JWT_SECRET: str = Field(..., min_length=32)
    FOSSAPAY_API_KEY: str = Field(...)
    FOSSAPAY_SECRET:str =Field(...)
    FOSSAPAY_WEBHOOK_SECRET:str = Field(...)
    FOSSAPAY_BASE_URL:str = Field(default="https://api-production.fossapay.com")
    PAJCASH_APIKEY: str | None = Field(default=None)
    PAJCASH_BASE_URL: str = Field(default="https://api.paj.cash")
    PAJCASH_WEBHOOK_SECRET: str | None = Field(default=None)

    @field_validator("WHATSAPP_PAYMENT_METHODS", mode="before")
    @classmethod
    def _normalize_whatsapp_payment_methods(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("WHATSAPP_PAYMENT_METHODS must be a comma-separated string")
        methods = {method.strip().lower() for method in value.split(",") if method.strip()}
        if "usdc" not in methods or methods - {"usdc", "fossapay"}:
            raise ValueError(
                "WHATSAPP_PAYMENT_METHODS must include usdc and may also include fossapay"
            )
        return ",".join(method for method in ("usdc", "fossapay") if method in methods)

    @model_validator(mode="after")
    def _validate_whatsapp_payment_settings(self) -> "Settings":
        if self.WHATSAPP_PRIVATE_PAYMENTS and "fossapay" in self.whatsapp_payment_methods:
            raise ValueError(
                "Private WhatsApp payments cannot offer FossaPay; set "
                "WHATSAPP_PAYMENT_METHODS=usdc"
            )
        return self

    @property
    def whatsapp_payment_methods(self) -> frozenset[str]:
        return frozenset(self.WHATSAPP_PAYMENT_METHODS.split(","))

    @property
    def allowed_origins_list(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]


settings = Settings()
