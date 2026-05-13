"""TPM-aware throttler for Groq API calls.

Reads x-ratelimit-remaining-tokens and x-ratelimit-reset-tokens response
headers after every streaming call, then proactively sleeps before the next
section if the remaining budget would not cover the next request.

Usage
-----
throttler = TpmThrottler(model_id)
# after stream is created:
throttler.update_from_stream(stream)
# before next section:
throttler.wait_if_needed(max_tokens, yield_event_cb)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# TPM limits per model (Groq free tier, May 2026)
_MODEL_TPM: dict[str, int] = {
    "meta-llama/llama-4-scout-17b-16e-instruct": 30_000,
    "llama-3.3-70b-versatile": 12_000,
    "openai/gpt-oss-120b": 8_000,
    "openai/gpt-oss-20b": 8_000,
    "openai/gpt-oss-safeguard-20b": 8_000,
    "qwen/qwen3-32b": 6_000,
    "llama-3.1-8b-instant": 6_000,
    "gemma2-9b-it": 6_000,
}

# Safety margin: wait if remaining < max_tokens * HEADROOM
_HEADROOM = 1.25


def _parse_duration(s: str) -> float:
    """Parse Groq reset header values like '7.66s', '2m30.1s', '1m' into seconds."""
    s = (s or "").strip()
    m = re.fullmatch(r"(?:(\d+)m)?(?:([\d.]+)s)?", s)
    if m:
        minutes = int(m.group(1) or 0)
        seconds = float(m.group(2) or 0)
        total = minutes * 60 + seconds
        if total > 0:
            return total
    return 60.0  # conservative fallback


class TpmThrottler:
    """Per-request TPM budget tracker driven by Groq response headers."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.model_tpm: int = _MODEL_TPM.get(model_id, 6_000)
        self._remaining: Optional[int] = None
        self._reset_s: float = 60.0
        self._updated_at: float = 0.0

    # ── Header ingestion ─────────────────────────────────────────────────────

    def update_from_stream(self, stream) -> None:
        """Extract rate-limit headers from a Groq streaming response object."""
        try:
            # Groq SDK wraps httpx; the raw response is accessible via .response
            headers = None
            if hasattr(stream, "response") and hasattr(stream.response, "headers"):
                headers = stream.response.headers
            elif hasattr(stream, "_response") and hasattr(stream._response, "headers"):
                headers = stream._response.headers
            if headers is None:
                return
            self._ingest(headers)
        except Exception as exc:
            logger.debug("TpmThrottler: could not read headers: %s", exc)

    def update_from_completion(self, completion) -> None:
        """Extract rate-limit headers from a non-streaming Groq completion."""
        try:
            resp = getattr(completion, "_response", None) or getattr(completion, "response", None)
            if resp and hasattr(resp, "headers"):
                self._ingest(resp.headers)
        except Exception as exc:
            logger.debug("TpmThrottler: could not read completion headers: %s", exc)

    def _ingest(self, headers) -> None:
        remaining_str = (headers.get("x-ratelimit-remaining-tokens") or "").strip()
        reset_str = (headers.get("x-ratelimit-reset-tokens") or "").strip()
        if remaining_str:
            try:
                self._remaining = int(remaining_str)
            except ValueError:
                pass
        if reset_str:
            self._reset_s = _parse_duration(reset_str)
        self._updated_at = time.monotonic()
        logger.info(
            "TPM header: remaining=%s reset=%s (model=%s)",
            self._remaining, reset_str or "?", self.model_id,
        )

    # ── Throttling ────────────────────────────────────────────────────────────

    def wait_if_needed(
        self,
        needed_tokens: int,
        yield_cb: Optional[Callable[[float], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Sleep until the TPM window resets if remaining < needed * HEADROOM.

        yield_cb(wait_seconds) is called once before sleeping so the caller
        can emit a rate_limit_wait SSE event.
        """
        if self._remaining is None:
            # No header data yet — use conservative pacing only if we know model_tpm
            return

        threshold = int(needed_tokens * _HEADROOM)
        if self._remaining >= threshold:
            return  # Plenty of budget left

        elapsed = time.monotonic() - self._updated_at
        wait = max(0.5, self._reset_s - elapsed + 1.5)   # 1.5s extra safety
        logger.info(
            "TPM budget low (remaining=%d < threshold=%d) — waiting %.1fs for reset",
            self._remaining, threshold, wait,
        )
        if yield_cb:
            yield_cb(wait)
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if is_cancelled and is_cancelled():
                return
            time.sleep(0.1)
        # Optimistically reset remaining estimate after the window
        self._remaining = self.model_tpm
