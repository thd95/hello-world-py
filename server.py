"""
Startet einen lokalen HTTP-Server im aktuellen Ordner.
Nötig damit index.html die dax_data.json per fetch() laden darf
(Browser blockieren das bei file://-Protokoll aus Sicherheitsgründen).

Aufruf: python server.py
Dann im Browser öffnen: http://localhost:8000
"""
import http.server
import socketserver

PORT = 8000

handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("", PORT), handler) as httpd:
    print(f"Server läuft auf http://localhost:{PORT}  —  Strg+C zum Beenden")
    httpd.serve_forever()
