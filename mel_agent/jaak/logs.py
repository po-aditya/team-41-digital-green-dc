"""Log sink protocol and a no-op sink (Req 19, 20.2, 20.3).

Real log entry builders are added later; this module only defines the seam.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LogSink(Protocol):
    """Receives one structured log entry per call."""

    def write(self, entry: dict) -> None: ...


class NullLogSink:
    """Sink that discards every entry."""

    def write(self, entry: dict) -> None:
        return None
