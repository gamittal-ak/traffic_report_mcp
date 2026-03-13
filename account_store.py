"""
Server-side account store — keeps switch keys off the LLM/user.

Flow:
  1. search_accounts(query)  → stores candidates, returns [{index, accountName}] only
  2. select_account(index)   → resolves candidate → stores {name: switch_key}, returns name
  3. _resolve_switch_key(name) → looks up internally, raises ToolError if not found
"""
import threading
from typing import Optional

_lock = threading.Lock()

# Candidates from the last search: list of {accountName, accountSwitchKey, accountId}
_candidates: list[dict] = []

# Resolved accounts: lowercased name → switch key
_resolved: dict[str, str] = {}

# Last selected account name (used as default when account_name is omitted)
_active_account: Optional[str] = None


def store_candidates(accounts: list[dict]) -> None:
    global _candidates
    with _lock:
        _candidates = accounts


def get_candidates() -> list[dict]:
    with _lock:
        return list(_candidates)


def resolve_candidate(index: int) -> str:
    """Store the switch key for the selected candidate. Returns the account name."""
    global _active_account
    with _lock:
        if index < 1 or index > len(_candidates):
            raise ValueError(f"Index {index} out of range (1–{len(_candidates)})")
        account = _candidates[index - 1]
        name = account["accountName"]
        key = account["accountSwitchKey"]
        _resolved[name.lower()] = key
        _active_account = name
        return name


def get_switch_key(account_name: str) -> Optional[str]:
    """Return switch key for an account name, or None if not resolved yet."""
    with _lock:
        return _resolved.get(account_name.lower())


def get_active_account() -> Optional[str]:
    with _lock:
        return _active_account


def list_resolved_accounts() -> list[str]:
    """Return names of all accounts the user has already selected (no keys)."""
    with _lock:
        return list(_resolved.keys())
