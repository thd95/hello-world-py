"""Gemeinsame DAX-Ladelogik — der reine Zugriff auf Yahoo Finance.

Die Cache- und Datenbanklogik liegt in db.py; hier steht nur das eigentliche
Abholen der Kurse. lade_dax_roh() liefert echte date-Objekte für die
Datenbankschicht."""

from datetime import date
import signal

import yfinance as yf


class Timeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise Timeout("Yahoo-Finance-Abruf hat zu lange gedauert")


def lade_dax_roh(start: str, end: str, symbol: str = "^GDAXI") -> list[tuple[date, float]]:
    """
    Lädt historische Eröffnungskurse von Yahoo Finance als Rohdaten.

    start, end: Datum im Format JJJJ-MM-TT
    symbol:     Yahoo-Finance-Symbol (Standard: ^GDAXI für den DAX)

    Rückgabe: Liste von (datum, eroeffnung), aufsteigend nach Datum sortiert.

    Bei Timeout (>10 Sekunden) wird eine leere Liste zurückgegeben, damit die
    Anwendung mit gecachten Daten weiterarbeitet statt zu blockieren.
    """
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(10)

        hist = yf.Ticker(symbol).history(start=start, end=end)
        signal.alarm(0)

        if hist.empty:
            return []
        return [
            (datum.date(), round(float(row["Open"]), 2))
            for datum, row in hist.iterrows()
        ]
    except Timeout:
        return []
    except Exception:
        return []


def hole_name(symbol: str) -> str | None:
    """Versucht, den Anzeigenamen eines Symbols von Yahoo Finance zu holen."""
    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or info.get("longName")
    except Exception:
        return None
