from __future__ import annotations


class SnapshotError(Exception):
    """An output could not be produced. `retryable` errors are retried with backoff (network
    hiccups, AI provider down); the rest fail the job permanently (unsupported/broken input)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
