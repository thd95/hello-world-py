"""CLI-Werkzeug zum Vorbefüllen der Datenbank.

Lädt einen Zeitraum eines Werts von Yahoo Finance und legt ihn in der lokalen
Datenbank (kurse.db) ab. Dieselbe Cache-Logik nutzt auch der Webserver — hier
lässt sie sich gezielt von der Kommandozeile aus anstoßen.

Beispiel: python fetch_dax.py --symbol AAPL --start 2020-01-01 --end 2026-07-01
"""
import argparse
import sys

from db import hole_kurse, init_db

parser = argparse.ArgumentParser(
    description="Lädt historische Kurse von Yahoo Finance in die Datenbank."
)
parser.add_argument(
    "--start", default="2023-07-01",
    help="Startdatum im Format JJJJ-MM-TT (Standard: 2023-07-01)"
)
parser.add_argument(
    "--end", default="2026-07-01",
    help="Enddatum im Format JJJJ-MM-TT (Standard: 2026-07-01)"
)
parser.add_argument(
    "--symbol", default="^GDAXI",
    help="Yahoo-Finance-Symbol (Standard: ^GDAXI für den DAX)"
)
args = parser.parse_args()

init_db()
daten = hole_kurse(args.start, args.end, args.symbol)

if not daten:
    print(f"Keine Daten gefunden für {args.symbol} ({args.start} bis {args.end}).")
    sys.exit(1)

print(f"{len(daten)} Datensätze ({args.start} bis {args.end}) "
      f"für {args.symbol} in der Datenbank.")
