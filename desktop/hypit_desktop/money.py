"""How costs are shown. The ledger keeps every amount in US dollars (Ark's yuan are converted at a fixed rate when a
run is recorded), so old and new runs add up; only the display changes with the user's choice in Settings."""
from __future__ import annotations

CNY_PER_USD = 7.2
CURRENCIES = {"CNY": "人民币(¥)", "USD": "美元($)"}
_currency = "USD"


def configure(currency: str) -> None:
    global _currency
    _currency = currency if currency in CURRENCIES else "CNY"


def fmt(usd: float) -> str:
    """A ledger amount (dollars) as text in the chosen currency."""
    if _currency == "USD":
        return f"${usd:.2f}"
    return f"¥{usd * CNY_PER_USD:.2f}"
