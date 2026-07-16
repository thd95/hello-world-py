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

Aufruf: python server.py
Dann im Browser öffnen: http://localhost:8000
"""
import http.server
import json
import socketserver
from urllib.parse import urlparse, parse_qs

from db import fuege_wert_hinzu, hole_kurse, init_db, liste_werte

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

        # ── sonst: statische Dateien wie gewohnt ──
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/werte":
            self.send_json({"fehler": "Unbekannter Endpunkt."}, 404)
            return

        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(laenge) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json({"fehler": "Ungültiger Anfrageinhalt (JSON erwartet)."}, 400)
            return

        try:
            wert = fuege_wert_hinzu(
                body.get("symbol", ""),
                body.get("name", ""),
                body.get("einheit", ""),
                body.get("einheit_lang", ""),
            )
            self.send_json(wert, 201)
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

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Server läuft auf http://localhost:{PORT}  —  Strg+C zum Beenden")
    httpd.serve_forever()
