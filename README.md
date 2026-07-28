# aktien-kurse

Lädt historische Kurse verschiedener Werte (DAX, S&P 500, Apple, Tesla, Bitcoin …) von Yahoo Finance und zeigt sie als Tabelle und als interaktives Chart im Browser an. Im Menüpunkt **Simulation** lassen sich Handelsstrategien (SMA-Kreuzung, Stop-Loss/Take-Profit, Buy & Hold) auf den historischen Kursen durchspielen — mit gespeicherten Tagesendständen, Trades und Kapitalverlaufs-Chart je Lauf.

## Installation

```bash
pip install -r requirements.txt
```

## Verwendung

1. Optional: Kursdaten von Yahoo Finance in die lokale Datenbank (`kurse.db`) vorladen — der Server lädt fehlende Zeiträume sonst bei der ersten Anfrage selbst nach:

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

## Betrieb auf einem eigenen Server

Einrichtung auf einem Hetzner-Cloud-Server (Domain, HTTPS, Passwortschutz, Autostart):
siehe [DEPLOY.md](DEPLOY.md).

## Für Entwickler

Architektur, Datenmodell, API-Referenz und Erweiterungspunkte: siehe [DEVELOPER.md](DEVELOPER.md).

## Lizenz

MIT
