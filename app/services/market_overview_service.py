import logging
from dataclasses import dataclass

import yfinance as yf

logger = logging.getLogger(__name__)

# Indian market indices + commodity proxies available on NSE
_INDICES = [
    {"label": "NIFTY 50", "ticker": "^NSEI"},
    {"label": "SENSEX", "ticker": "^BSESN"},
    {"label": "GOLD ETF", "ticker": "GOLDBEES.NS"},
    {"label": "SILVER ETF", "ticker": "SILVERBEES.NS"},
]


@dataclass
class MarketOverviewItem:
    label: str
    ticker: str
    price: float | None
    change_percent: float | None
    currency: str = "INR"


def fetch_market_overview() -> list[MarketOverviewItem]:
    results: list[MarketOverviewItem] = []

    for idx in _INDICES:
        try:
            fi = yf.Ticker(idx["ticker"]).fast_info
            price: float | None = getattr(fi, "last_price", None)
            prev: float | None = getattr(fi, "previous_close", None)

            pct: float | None = None
            if price is not None and prev and prev != 0:
                pct = round((price - prev) / prev * 100, 2)

            results.append(
                MarketOverviewItem(
                    label=idx["label"],
                    ticker=idx["ticker"],
                    price=round(price, 2) if price is not None else None,
                    change_percent=pct,
                )
            )
        except Exception as exc:
            logger.warning("Market overview fetch failed for %s: %s", idx["ticker"], exc)
            results.append(
                MarketOverviewItem(
                    label=idx["label"],
                    ticker=idx["ticker"],
                    price=None,
                    change_percent=None,
                )
            )

    return results
