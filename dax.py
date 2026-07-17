"""Gemeinsame DAX-Ladelogik — der reine Zugriff auf Yahoo Finance.

Die Cache- und Datenbanklogik liegt in db.py; hier steht nur das eigentliche
Abholen der Kurse. lade_dax_roh() liefert echte date-Objekte für die
Datenbankschicht."""

from datetime import date

import yfinance as yf


def lade_dax_roh(start: str, end: str, symbol: str = "^GDAXI") -> list[tuple[date, float]]:
    """
    Lädt historische Eröffnungskurse von Yahoo Finance als Rohdaten.

    start, end: Datum im Format JJJJ-MM-TT
    symbol:     Yahoo-Finance-Symbol (Standard: ^GDAXI für den DAX)

    Rückgabe: Liste von (datum, eroeffnung), aufsteigend nach Datum sortiert.
    """
    hist = yf.Ticker(symbol).history(start=start, end=end)
    if hist.empty:
        return []
    return [
        (datum.date(), round(float(row["Open"]), 2))
        for datum, row in hist.iterrows()
    ]


def hole_name(symbol: str) -> str | None:
    """Versucht, den Anzeigenamen eines Symbols von Yahoo Finance zu holen."""
    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or info.get("longName")
    except Exception:
        return None
