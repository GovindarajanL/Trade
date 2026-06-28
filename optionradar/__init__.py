"""OptionRadar -- a calls-only, curated-universe options signal system.

Scans a small static watchlist daily, runs a gate -> score -> fire pipeline, and
emits at most one of three Telegram outputs: No Trade Today, Standard Signal, or
Moonshot. Read-only: it never places orders. Entry is manual.
"""

__version__ = "1.0.0"
