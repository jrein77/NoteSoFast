"""
Mock-mode toggle.

In mock mode, all LLM-facing functions short-circuit to canned placeholder
responses (see mock_llm.py) instead of calling the Anthropic API. This lets
the demo run end-to-end with no API key.

Default behavior (in this demo fork):
- If the env var MOCK_MODE is set, that wins ("1"/"true"/"yes" → on).
- Otherwise mock mode is ON by default so the zipped demo "just works".
- The user can flip it at runtime via the sidebar toggle (POST /api/mock-mode),
  which writes the chosen state to .mock_mode_state so it persists across
  reloads. Toggling to API mode requires ANTHROPIC_API_KEY to be set.
"""

import os
from pathlib import Path

_STATE_FILE = Path(__file__).parent / ".mock_mode_state"


def _env_override():
    val = os.environ.get("MOCK_MODE")
    if val is None:
        return None
    return val.strip().lower() in ("1", "true", "yes", "on")


def _read_state():
    try:
        return _STATE_FILE.read_text().strip() == "mock"
    except FileNotFoundError:
        return None


def is_mock():
    """True if LLM calls should be replaced with mock responses."""
    env = _env_override()
    if env is not None:
        return env
    saved = _read_state()
    if saved is not None:
        return saved
    # Default: mock ON so the zipped demo runs without a key.
    return True


def set_mock(enabled: bool):
    """Persist the toggle state. Returns the new state."""
    _STATE_FILE.write_text("mock" if enabled else "api")
    return enabled


def has_api_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
