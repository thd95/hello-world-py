"""
Lokaler HTTP-Server für die Kurs-Anwendung.

- Liefert die statischen Dateien (index.html usw.) aus dem aktuellen Ordner.
- Stellt zusätzlich eine API bereit:
      GET  /api/dax?start=JJJJ-MM-TT&end=JJJJ-MM-TT&symbol=^GDAXI
           Kursdaten aus der Datenbank, fehlende Zeiträume werden von
           Yahoo Finance nachgeladen (Cache mit Nachladen).
      GET  /api/werte
           Alle Werte der Datenbank (Symbol, Name, Einheit, Cache-Stand).
      POST /api/werte   Body: {"symbol": …, "name": …, "einheit": …, "einheit_lang": …}
           Legt einen neuen Wert an — nur wenn Yahoo Finance das Symbol kennt.
      GET  /api/simulationen
           Alle gespeicherten Simulationsläufe (Kennzahlen, ohne Tagesdaten).
      GET  /api/simulationen/<id>
           Ein Lauf im Detail: Konfiguration, Trades, Tagesendstände.
      POST /api/simulationen
           Body: Simulations-Konfiguration (siehe simulation.SimulationsEngine).
           Führt den Lauf sofort aus, speichert ihn und liefert die Kennzahlen.

Aufruf: python server.py
Dann im Browser öffnen: http://localhost:8000
"""
import http.server
import json
from urllib.parse import urlparse, parse_qs

from db import fuege_wert_hinzu, hole_kurse, init_db, liste_werte
from simulation import hole_simulation, liste_simulationen, starte_simulation

# Nur auf localhost lauschen — die Anwendung ist nicht für den Netzzugriff
# gedacht (keine Authentifizierung).
HOST = "127.0.0.1"
PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Browser sollen immer beim Server nachfragen statt alte Seiten aus dem
        # Cache zu zeigen — sonst sind Änderungen an index.html nicht sichtbar.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # ── API-Routen ──
        if parsed.path == "/api/dax":
            self.handle_api(parse_qs(parsed.query))
            return
        if parsed.path == "/api/werte":
            try:
                self.send_json(liste_werte(), 200)
            except Exception as e:
                self.send_json({"fehler": str(e)}, 500)
            return
        if parsed.path == "/api/simulationen":
            try:
                self.send_json(liste_simulationen(), 200)
            except Exception as e:
                self.send_json({"fehler": str(e)}, 500)
            return
        if parsed.path.startswith("/api/simulationen/"):
            try:
                sim_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"fehler": "Ungültige Simulations-ID."}, 400)
                return
            try:
                sim = hole_simulation(sim_id)
                if sim is None:
                    self.send_json({"fehler": f"Simulation {sim_id} nicht gefunden."}, 404)
                else:
                    self.send_json(sim, 200)
            except Exception as e:
                self.send_json({"fehler": str(e)}, 500)
            return

        # ── sonst: statische Dateien wie gewohnt ──
        super().do_GET()

    def do_POST(self):
        pfad = urlparse(self.path).path
        if pfad not in ("/api/werte", "/api/simulationen"):
            self.send_json({"fehler": "Unbekannter Endpunkt."}, 404)
            return

        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(laenge) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json({"fehler": "Ungültiger Anfrageinhalt (JSON erwartet)."}, 400)
            return

        try:
            if pfad == "/api/werte":
                antwort = fuege_wert_hinzu(
                    body.get("symbol", ""),
                    body.get("name", ""),
                    body.get("einheit", ""),
                    body.get("einheit_lang", ""),
                )
            else:
                antwort = starte_simulation(body)
            self.send_json(antwort, 201)
        except ValueError as e:
            self.send_json({"fehler": str(e)}, 400)
        except Exception as e:
            self.send_json({"fehler": str(e)}, 500)

    def handle_api(self, params):
        # Query-Parameter mit Standardwerten
        start  = params.get("start",  ["2023-07-01"])[0]
        end    = params.get("end",    ["2026-07-01"])[0]
        symbol = params.get("symbol", ["^GDAXI"])[0]

        try:
            daten = hole_kurse(start, end, symbol)
            if not daten:
                self.send_json({"fehler": f"Keine Daten für {symbol} ({start} bis {end})."}, 404)
            else:
                self.send_json(daten, 200)
        except Exception as e:
            self.send_json({"fehler": str(e)}, 500)

    def send_json(self, obj, code):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


init_db()

# ThreadingHTTPServer: ein langsamer Yahoo-Abruf blockiert so nicht die
# übrigen Anfragen (db.py öffnet pro Aufruf eine eigene Session).
with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
    print(f"Server läuft auf http://localhost:{PORT}  —  Strg+C zum Beenden")
    httpd.serve_forever()
