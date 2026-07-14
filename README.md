# dax-kurse

Lädt historische DAX-Kurse von Yahoo Finance und zeigt sie als Tabelle und als interaktives Chart im Browser an.

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

Im Tab **Tabelle** bzw. **Chart** auf „Daten laden" klicken.

## Dateien

- `fetch_dax.py` — lädt die DAX-Eröffnungskurse via `yfinance`
- `server.py` — einfacher lokaler HTTP-Server
- `index.html` — Anzeige als Tabelle und interaktives Liniendiagramm

## Lizenz

MIT
