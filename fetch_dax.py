import json
import yfinance as yf

# DAX-Daten laden: period1/period2 aus der Yahoo-URL entsprechen Unix-Timestamps
# ^GDAXI ist das Yahoo-Finance-Symbol für den DAX
ticker = yf.Ticker("^GDAXI")

# Historische Daten für den Zeitraum aus der URL abrufen
# (2025-07-01 bis 2026-07-01, entspricht den Timestamps in der URL)
hist = ticker.history(start="2023-07-01", end="2026-07-01")

if hist.empty:
    print("Keine Daten gefunden.")
else:
    # Nur Datum und Eröffnungskurs behalten, als Liste von Dicts
    daten = [
        {
            "datum": datum.strftime("%d.%m.%Y"),
            "eroeffnung": round(row["Open"], 2)
        }
        for datum, row in hist.iterrows()
    ]

    with open("dax_data.json", "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)

    print(f"{len(daten)} Datensätze gespeichert in dax_data.json")
