from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, computed_field
from functools import lru_cache
from typing import List


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )

    PORT: int = Field(default=8000)
    DATABASE_URL_DEV: str = Field(...)
    SOLANA_RPC_URL: str = Field(default="https://api.devnet.solana.com")
    
    ALLOWED_ORIGINS: str = Field(default="http://localhost:5173")
    
    WASENDER_API_KEY: str | None = Field(default=None)
    JWT_SECRET: str = Field(..., min_length=32)

    @property
    def allowed_origins_list(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]


settings = Settings()
