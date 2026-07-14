import argparse
import json
import sys

from dax import lade_dax

# ── Kommandozeilen-Argumente ──
# Start-/Enddatum sind frei wählbar; ohne Angabe gelten die Standardwerte.
parser = argparse.ArgumentParser(
    description="Lädt historische DAX-Eröffnungskurse von Yahoo Finance."
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
parser.add_argument(
    "--out", default="dax_data.json",
    help="Ausgabedatei (Standard: dax_data.json)"
)
args = parser.parse_args()

daten = lade_dax(args.start, args.end, args.symbol)

if not daten:
    print(f"Keine Daten gefunden für {args.symbol} ({args.start} bis {args.end}).")
    sys.exit(1)

with open(args.out, "w", encoding="utf-8") as f:
    json.dump(daten, f, ensure_ascii=False, indent=2)

print(f"{len(daten)} Datensätze ({args.start} bis {args.end}) gespeichert in {args.out}")
