"""
GitHub REST API client for dispatching workflow runs from Telegram Bot Service.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from telegram_bot.config import Settings

logger = logging.getLogger("github_client")


class GitHubDispatchClient:
    """Async client for GitHub Actions workflow_dispatch requests."""

    def __init__(self, settings: Settings):
        self.token = settings.GITHUB_TOKEN.strip()
        self.owner = settings.GITHUB_OWNER.strip()
        self.repo = settings.GITHUB_REPO.strip()
        self.workflow_file = settings.GITHUB_WORKFLOW_FILE.strip()
        self.ref = settings.GITHUB_REF.strip()

        if not self.token or not self.owner or not self.repo:
            logger.warning("GitHub configuration (token, owner, repo) is incomplete.")

    def sanitize_error(self, message: str) -> str:
        """Strip GitHub token from any error message."""
        if not message:
            return "Unknown error"
        sanitized = str(message)
        if self.token and self.token in sanitized:
            sanitized = sanitized.replace(self.token, "[REDACTED_TOKEN]")
        return sanitized

    async def trigger_workflow(self, inputs: Dict[str, str]) -> Tuple[bool, str]:
        """
        Trigger GitHub workflow_dispatch.
        Returns (success: bool, status_or_error_message: str).
        """
        if not self.token or not self.owner or not self.repo:
            return False, "GitHub bot configuration is missing (GITHUB_TOKEN, GITHUB_OWNER, or GITHUB_REPO)."

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/workflows/{self.workflow_file}/dispatches"

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Telegram-Whisper-Bot/1.0",
        }

        payload = {
            "ref": self.ref,
            "inputs": inputs,
        }

        max_retries = 3
        backoff = 1.0

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(
                        f"Dispatching GitHub workflow '{self.workflow_file}' for "
                        f"request_id={inputs.get('request_id', '')[:8]}..."
                    )
                    response = await client.post(url, headers=headers, json=payload)

                    # Handle GitHub HTTP Status Codes
                    if response.status_code == 204:
                        logger.info("GitHub workflow_dispatch accepted (204 No Content).")
                        return True, "Workflow dispatched successfully."

                    elif response.status_code in (200, 201, 202):
                        logger.info(f"GitHub workflow_dispatch accepted ({response.status_code}).")
                        return True, f"Workflow dispatched ({response.status_code})."

                    # Permanent Client Errors (401 Unauthorized, 403 Forbidden, 404 Not Found, 422 Unprocessable Entity)
                    if response.status_code in (401, 403, 404, 422):
                        err_text = self.sanitize_error(response.text)
                        logger.error(
                            f"GitHub API permanent error ({response.status_code}): {err_text}"
                        )
                        return False, f"GitHub API error ({response.status_code}): {err_text}"

                    # Rate Limiting (429) or Server Errors (5xx)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == max_retries:
                            err_text = self.sanitize_error(response.text)
                            return False, f"GitHub API error after retries ({response.status_code}): {err_text}"
                        logger.warning(
                            f"GitHub API retry {attempt}/{max_retries} due to status {response.status_code}"
                        )
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        continue

                    err_text = self.sanitize_error(response.text)
                    return False, f"Unexpected GitHub API response ({response.status_code}): {err_text}"

                except httpx.TimeoutException as e:
                    if attempt == max_retries:
                        return False, "GitHub API dispatch request timed out after retries."
                    logger.warning(f"GitHub API timeout (attempt {attempt}/{max_retries}). Retrying...")
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                except Exception as e:
                    safe_err = self.sanitize_error(str(e))
                    return False, f"GitHub dispatch exception: {safe_err}"

        return False, "Failed to dispatch GitHub workflow."
