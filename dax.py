"""Gemeinsame DAX-Ladelogik — genutzt von fetch_dax.py (CLI) und server.py (API)."""

import yfinance as yf


def lade_dax(start: str, end: str, symbol: str = "^GDAXI") -> list[dict]:
    """
    Lädt historische Eröffnungskurse von Yahoo Finance.

    start, end: Datum im Format JJJJ-MM-TT
    symbol:     Yahoo-Finance-Symbol (Standard: ^GDAXI für den DAX)

    Rückgabe: Liste von {"datum": "TT.MM.JJJJ", "eroeffnung": float},
              aufsteigend nach Datum sortiert.
    """
    hist = yf.Ticker(symbol).history(start=start, end=end)
    if hist.empty:
        return []
    return [
        {
            "datum": datum.strftime("%d.%m.%Y"),
            "eroeffnung": round(row["Open"], 2),
        }
        for datum, row in hist.iterrows()
    ]
