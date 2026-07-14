"""
Lokaler HTTP-Server für die DAX-Anwendung.

- Liefert die statischen Dateien (index.html usw.) aus dem aktuellen Ordner.
- Stellt zusätzlich eine API bereit, die Kursdaten direkt von Yahoo Finance holt:
      GET /api/dax?start=JJJJ-MM-TT&end=JJJJ-MM-TT&symbol=^GDAXI
  So kann das Laden direkt über die Weboberfläche ausgelöst werden.

Aufruf: python server.py
Dann im Browser öffnen: http://localhost:8000
"""
import http.server
import json
import socketserver
from urllib.parse import urlparse, parse_qs

from dax import lade_dax

PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        # ── API-Route ──
        if parsed.path == "/api/dax":
            self.handle_api(parse_qs(parsed.query))
            return

        # ── sonst: statische Dateien wie gewohnt ──
        super().do_GET()

    def handle_api(self, params):
        # Query-Parameter mit Standardwerten
        start  = params.get("start",  ["2023-07-01"])[0]
        end    = params.get("end",    ["2026-07-01"])[0]
        symbol = params.get("symbol", ["^GDAXI"])[0]

        try:
            daten = lade_dax(start, end, symbol)
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


with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Server läuft auf http://localhost:{PORT}  —  Strg+C zum Beenden")
    httpd.serve_forever()
