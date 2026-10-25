"""UTC observations without a Home Assistant dependency."""
from datetime import UTC, datetime


def utcnow() -> datetime:
    """Use the same aware UTC observation semantics as the accepted policy."""
    return datetime.now(UTC)
