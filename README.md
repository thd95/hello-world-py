# aktien-kurse

Lädt historische Kurse verschiedener Werte (DAX, S&P 500, Apple, Tesla, Bitcoin …) von Yahoo Finance und zeigt sie als Tabelle und als interaktives Chart im Browser an.

## Installation

```bash
pip install -r requirements.txt
```

## Verwendung

1. Kursdaten von Yahoo Finance laden (erzeugt `dax_data.json`):

   ```bash
   python fetch_dax.py
   ```

2. Lokalen Webserver starten:

   ```bash
   python server.py
   ```

3. Im Browser öffnen: [http://localhost:8000](http://localhost:8000)

Oben in der Ladeleiste einen **Wert** (z. B. DAX, Apple, Bitcoin) und den **Zeitraum** wählen, dann auf „Daten laden" klicken. Tabelle und Chart zeigen jeweils den gewählten Wert.

Weitere Symbole lassen sich in `index.html` im `<select id="symbol">` ergänzen — jedes gültige [Yahoo-Finance-Symbol](https://finance.yahoo.com/) funktioniert (z. B. `NVDA`, `^GSPC`, `EURUSD=X`).

## Dateien

- `fetch_dax.py` — lädt die DAX-Eröffnungskurse via `yfinance`
- `server.py` — einfacher lokaler HTTP-Server
- `index.html` — Anzeige als Tabelle und interaktives Liniendiagramm

## Lizenz

MIT
