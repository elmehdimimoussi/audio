"""
Unit tests for GitHub REST API dispatch client.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from telegram_bot.config import Settings
from telegram_bot.github_client import GitHubDispatchClient


def test_github_dispatch_success():
    async def _run():
        settings = Settings(
            GITHUB_TOKEN="secret_pat_token_12345",
            GITHUB_OWNER="myowner",
            GITHUB_REPO="myrepo",
            GITHUB_WORKFLOW_FILE="transcribe.yml",
            GITHUB_REF="main",
        )
        client = GitHubDispatchClient(settings)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            inputs = {
                "source_type": "telegram",
                "telegram_file_id": "file_123",
                "telegram_chat_id": "999",
                "request_id": "123e4567-e89b-12d3-a456-426614174000",
            }

            ok, msg = await client.trigger_workflow(inputs)
            assert ok is True
            assert "Workflow dispatched" in msg

            mock_post.assert_called_once()
            url = mock_post.call_args[0][0]
            assert "myowner/myrepo/actions/workflows/transcribe.yml/dispatches" in url

            headers = mock_post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer secret_pat_token_12345"
            assert headers["Accept"] == "application/vnd.github+json"

            json_body = mock_post.call_args[1]["json"]
            assert json_body["ref"] == "main"
            assert json_body["inputs"]["source_type"] == "telegram"

    asyncio.run(_run())


def test_github_token_sanitized_on_error():
    async def _run():
        settings = Settings(
            GITHUB_TOKEN="sensitive_pat_xyz",
            GITHUB_OWNER="myowner",
            GITHUB_REPO="myrepo",
        )
        client = GitHubDispatchClient(settings)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Bad credentials for token sensitive_pat_xyz"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            ok, msg = await client.trigger_workflow({"source_type": "telegram"})
            assert ok is False
            assert "sensitive_pat_xyz" not in msg
            assert "[REDACTED_TOKEN]" in msg

    asyncio.run(_run())
