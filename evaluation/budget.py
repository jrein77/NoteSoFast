"""Budget tracking and hard cutoffs to prevent runaway API/token usage.

The budget is enforced at two levels:
  - Session: bounds a single (profile, note) run.
  - Eval   : bounds the entire evaluation across all sessions.

Any call through the student or teacher LLM MUST go through Budget.record_call()
before making the request. When a cap is exceeded the Budget raises BudgetExceeded,
which the simulator catches and terminates the session / eval cleanly.
"""

import time


class BudgetExceeded(Exception):
    """Raised when a hard cap is hit. Carries which cap tripped."""

    def __init__(self, reason: str, scope: str):
        super().__init__(f"Budget exceeded ({scope}): {reason}")
        self.reason = reason
        self.scope = scope


class Budget:
    """Tracks API calls, input/output tokens, and wall time against hard caps.

    Defaults are conservative. Override per-run via run_eval.py flags.
    """

    def __init__(
        self,
        max_api_calls: int = 400,
        max_input_tokens: int = 400_000,
        max_output_tokens: int = 120_000,
        max_wall_seconds: float = 1800.0,
        scope: str = "eval",
    ):
        self.max_api_calls = max_api_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_seconds = max_wall_seconds
        self.scope = scope

        self.api_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.start_time = time.monotonic()
        self.tripped = False

    def check(self):
        """Raise BudgetExceeded if any cap is met. Call before each API request."""
        if self.api_calls >= self.max_api_calls:
            self.tripped = True
            raise BudgetExceeded(
                f"api_calls={self.api_calls}/{self.max_api_calls}", self.scope
            )
        if self.input_tokens >= self.max_input_tokens:
            self.tripped = True
            raise BudgetExceeded(
                f"input_tokens={self.input_tokens}/{self.max_input_tokens}", self.scope
            )
        if self.output_tokens >= self.max_output_tokens:
            self.tripped = True
            raise BudgetExceeded(
                f"output_tokens={self.output_tokens}/{self.max_output_tokens}",
                self.scope,
            )
        elapsed = time.monotonic() - self.start_time
        if elapsed >= self.max_wall_seconds:
            self.tripped = True
            raise BudgetExceeded(
                f"wall_seconds={elapsed:.1f}/{self.max_wall_seconds}", self.scope
            )

    def record_call(self, input_tokens: int, output_tokens: int):
        """Record an API call's usage. Caller should first invoke check()."""
        self.api_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def summary(self) -> dict:
        return {
            "scope": self.scope,
            "api_calls": self.api_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_seconds": round(time.monotonic() - self.start_time, 2),
            "caps": {
                "max_api_calls": self.max_api_calls,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_wall_seconds": self.max_wall_seconds,
            },
            "tripped": self.tripped,
        }

    def remaining_calls(self) -> int:
        return max(0, self.max_api_calls - self.api_calls)
