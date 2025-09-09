from __future__ import annotations
import os
import threading
from datetime import date
from hashlib import sha256
from typing import Tuple, Optional

# Quota per day (default 3)
QUOTA_PER_DAY = int(os.getenv("QUOTA_PER_DAY", "3"))


class DailyQuotaManager:
    """In-memory per-day quota manager.
    Keys are account IDs derived from Authorization tokens.
    Reset occurs automatically when the calendar date changes.
    """

    def __init__(self, per_day: int = QUOTA_PER_DAY):
        self.per_day = per_day
        self._lock = threading.Lock()
        self._today: date = date.today()
        self._usage: dict[str, int] = {}

    def _ensure_today(self):
        today = date.today()
        if today != self._today:
            # Reset usage on date change
            self._today = today
            self._usage = {}

    def get_remaining(self, account_id: str) -> int:
        with self._lock:
            self._ensure_today()
            used = self._usage.get(account_id, 0)
            remaining = self.per_day - int(used)
            return max(0, remaining)

    def consume_if_allowed(self, account_id: str) -> Tuple[bool, int]:
        with self._lock:
            self._ensure_today()
            used = self._usage.get(account_id, 0)
            if used >= self.per_day:
                return False, 0
            used += 1
            self._usage[account_id] = used
            remaining = self.per_day - used
            return True, max(0, remaining)


_quota_manager = DailyQuotaManager()


def get_quota_manager() -> DailyQuotaManager:
    return _quota_manager


def account_id_from_token(token: Optional[str], ip: Optional[str]) -> str:
    if token:
        return sha256(token.encode("utf-8")).hexdigest()
    # Fallback to IP-based bucket if no token present
    return f"ip:{ip or 'unknown'}"
