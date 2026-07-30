"""
Configuration management for Telegram bot service using Pydantic Settings.
"""

import os
from typing import List, Set
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot API Token")
    TELEGRAM_WEBHOOK_SECRET: str = Field(default="", description="Secret header token for webhook verification")
    ALLOWED_TELEGRAM_USER_IDS: str = Field(default="", description="Comma-separated list of authorized numeric user IDs")
    ALLOWED_CHAT_TYPES: str = Field(default="private", description="Comma-separated allowed chat types (private, group, supergroup)")

    GITHUB_TOKEN: str = Field(default="", description="Fine-grained GitHub Personal Access Token")
    GITHUB_OWNER: str = Field(default="", description="GitHub repository owner/organization")
    GITHUB_REPO: str = Field(default="", description="GitHub repository name")
    GITHUB_WORKFLOW_FILE: str = Field(default="transcribe.yml", description="Workflow file name")
    GITHUB_REF: str = Field(default="main", description="Git reference for workflow dispatch")

    BOT_STATE_DB_PATH: str = Field(default="telegram_bot.db", description="Path to SQLite database")
    TELEGRAM_MAX_DIRECT_DOWNLOAD_BYTES: int = Field(default=20 * 1024 * 1024, description="Max direct download bytes (20 MB for hosted API)")

    DEFAULT_LANGUAGE: str = Field(default="ar", description="Default transcription language")
    DEFAULT_MODEL: str = Field(default="medium", description="Default faster-whisper model")
    DEFAULT_OUTPUT_FORMATS: str = Field(default="txt", description="Default output formats")
    SHOW_GITHUB_RUN_URL: bool = Field(default=False, description="Include GitHub run URL in status message")
    TELEGRAM_API_BASE_URL: str = Field(default="https://api.telegram.org", description="Base URL for Telegram Bot API")

    @property
    def allowed_user_ids(self) -> Set[int]:
        """Parse comma-separated user IDs into set of integers."""
        if not self.ALLOWED_TELEGRAM_USER_IDS.strip():
            return set()
        result = set()
        for item in self.ALLOWED_TELEGRAM_USER_IDS.split(","):
            cleaned = item.strip()
            if cleaned:
                try:
                    result.add(int(cleaned))
                except ValueError:
                    pass
        return result

    @property
    def allowed_chat_types_list(self) -> List[str]:
        """Parse allowed chat types."""
        return [t.strip().lower() for t in self.ALLOWED_CHAT_TYPES.split(",") if t.strip()]


def get_settings() -> Settings:
    return Settings()
