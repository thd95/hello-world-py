# Betrieb auf einem Hetzner-Cloud-Server

Diese Anleitung richtet die Kurs-Anwendung auf einem eigenen Server ein: erreichbar
unter einer eigenen Domain, per HTTPS verschlüsselt und durch ein Passwort geschützt.

**Warum der Passwortschutz nötig ist:** Die Anwendung selbst kennt keine Benutzer und
keine Anmeldung (`server.py` lauscht lokal auf `127.0.0.1:8000`). Ohne vorgelagerten
Schutz könnte jeder im Internet die Simulationen starten, Werte anlegen und die
Datenbank füllen. Deshalb steht nginx davor und fragt Benutzername und Passwort ab.

Aufbau nach der Einrichtung:

```
Browser ──HTTPS──> nginx (Port 443, Passwortschutz) ──HTTP──> server.py (127.0.0.1:8000)
                                                                    │
                                                              kurse.db (SQLite)
                                                                    │
                                                        Yahoo Finance (ausgehend)
```

---

## 1. Server bei Hetzner bestellen

1. Bei der [Hetzner Cloud Console](https://console.hetzner.cloud) anmelden und ein
   Projekt anlegen (z. B. „Aktien-Kurse“).
2. **Server hinzufügen** und wählen:
   - **Standort:** Nürnberg oder Falkenstein (deutsche Rechenzentren, kurze Wege).
   - **Image:** Ubuntu 24.04.
   - **Typ:** **CX22** (2 vCPU, 4 GB RAM, 40 GB SSD, ca. 4 €/Monat) — für diese
     Anwendung reichlich bemessen. Kleiner geht auch, größer lohnt nicht.
   - **Netzwerk:** IPv4 **und** IPv6 aktiviert lassen (IPv4 kostet ein paar Cent
     extra, ist für Let's Encrypt und ältere Netze aber der bequemere Weg).
   - **SSH-Key:** den eigenen öffentlichen Schlüssel hinterlegen (siehe unten).
     Kein Passwort-Login — das erspart die halbe Sicherheitsdiskussion.
   - **Name:** z. B. `kurse`.
3. Bestellen. Nach etwa 30 Sekunden zeigt die Console die **IPv4-Adresse** an.

### SSH-Key erzeugen (falls noch keiner vorhanden)

Unter Windows in der PowerShell, unter macOS/Linux im Terminal:

```bash
ssh-keygen -t ed25519 -C "kurse-server"
```

Die Datei `~/.ssh/id_ed25519.pub` (Windows: `C:\Users\<Name>\.ssh\id_ed25519.pub`)
öffnen und ihren **kompletten Inhalt** bei Hetzner als SSH-Key einfügen.

---

## 2. Domain auf den Server zeigen lassen

Beim Domain-Anbieter (Hetzner DNS, Strato, IONOS …) für die gewünschte
(Sub-)Domain anlegen:

| Typ  | Name    | Wert                        |
|------|---------|-----------------------------|
| A    | `kurse` | die IPv4-Adresse des Servers |
| AAAA | `kurse` | die IPv6-Adresse (optional)  |

Danach prüfen — es kann einige Minuten bis wenige Stunden dauern:

```bash
dig +short kurse.example.de
```

Erst wenn hier die Server-IP erscheint, kann Let's Encrypt ein Zertifikat ausstellen.
Ohne Domain lässt sich die Einrichtung mit `SKIP_TLS=1` trotzdem durchführen und das
Zertifikat später nachholen.

---

## 3. Einrichtung ausführen

Am Server anmelden (IP aus der Hetzner-Console):

```bash
ssh root@<SERVER-IP>
```

Vorhandene Pakete aktualisieren und das Einrichtungsskript direkt aus dem Repository
starten:

```bash
apt update && apt upgrade -y

apt install -y git
git clone https://github.com/thd95/hello-world-py.git /opt/aktien-kurse
DOMAIN=kurse.example.de EMAIL=du@example.de bash /opt/aktien-kurse/deploy/setup-server.sh
```

`DOMAIN` und `EMAIL` durch die eigenen Werte ersetzen. Das Skript

1. installiert Python, nginx, certbot und die Firewall,
2. legt den Dienstbenutzer `aktien` an,
3. richtet die virtuelle Python-Umgebung mit `yfinance` und `SQLAlchemy` ein,
4. installiert den systemd-Dienst `aktien-kurse` (Autostart, Neustart nach Absturz),
5. **fragt interaktiv nach einem Passwort** für den Zugang (Benutzername `kurse`,
   änderbar über `BASIC_AUTH_USER=…`),
6. konfiguriert nginx als Reverse Proxy mit Passwortschutz,
7. öffnet in der Firewall nur SSH, HTTP und HTTPS,
8. holt das Let's-Encrypt-Zertifikat und schaltet die Weiterleitung auf HTTPS ein.

Das Skript ist wiederholbar: ein erneuter Aufruf aktualisiert nur, was sich geändert
hat, und lässt ein bereits gesetztes Passwort unangetastet.

Danach im Browser `https://kurse.example.de` öffnen — Benutzername und Passwort
eingeben, oben einen Wert und Zeitraum wählen, „Daten laden“ klicken.

---

## 4. Laufender Betrieb

```bash
systemctl status aktien-kurse        # Läuft der Dienst?
journalctl -u aktien-kurse -f        # Protokoll live mitlesen
systemctl restart aktien-kurse       # Neu starten
bash /opt/aktien-kurse/deploy/update.sh   # Neue Version einspielen
```

`update.sh` sichert vorher die Datenbank, holt den aktuellen Stand des Branches,
gleicht die Abhängigkeiten ab und startet den Dienst neu.

### Passwort ändern oder weitere Zugänge anlegen

```bash
htpasswd /etc/nginx/aktien-kurse.htpasswd kurse      # Passwort ändern
htpasswd /etc/nginx/aktien-kurse.htpasswd zweitname  # weiteren Benutzer anlegen
systemctl reload nginx
```

### Datenbank sichern

Die Datenbank liegt unter `/opt/aktien-kurse/kurse.db`. Eine konsistente Sicherung
im laufenden Betrieb (nicht einfach kopieren):

```bash
sqlite3 /opt/aktien-kurse/kurse.db ".backup '/root/kurse-$(date +%F).db'"
```

Täglich um 3 Uhr, mit Aufbewahrung der letzten 14 Tage — `crontab -e` als root:

```cron
0 3 * * * sqlite3 /opt/aktien-kurse/kurse.db ".backup '/root/backups/kurse-$(date +\%F).db'" && find /root/backups -name 'kurse-*.db' -mtime +14 -delete
```

(Vorher `mkdir -p /root/backups`.) Eine Kopie vom Server herunterholen:

```bash
scp root@<SERVER-IP>:/root/backups/kurse-2026-07-28.db .
```

Der Verlust der Datenbank ist übrigens nicht dramatisch: Kursdaten lädt die Anwendung
bei Bedarf erneut von Yahoo Finance. Nur die gespeicherten **Simulationsläufe** wären
weg — die hängen an dieser Datei.

### Zertifikat

Certbot erneuert automatisch (systemd-Timer `certbot.timer`). Prüfen:

```bash
systemctl list-timers certbot.timer
certbot certificates
```

---

## 5. Was das Ganze kostet

| Posten                | ca. pro Monat |
|-----------------------|---------------|
| CX22 (2 vCPU, 4 GB)   | 3,79 €        |
| IPv4-Adresse          | 0,50 €        |
| Domain (je nach TLD)  | 0,50–1,50 €   |
| **Summe**             | **rund 5 €**  |

Traffic ist bei Hetzner in großzügigem Umfang enthalten; diese Anwendung bewegt
kaum Daten. Preise ohne Gewähr — Stand der Hetzner-Preisliste prüfen.

---

## 6. Fehlersuche

| Symptom | Ursache und Abhilfe |
|---|---|
| `certbot` scheitert | DNS zeigt noch nicht auf den Server: `dig +short kurse.example.de` prüfen, warten, Skript erneut ausführen. |
| Browser zeigt **502 Bad Gateway** | Der Dienst läuft nicht: `journalctl -u aktien-kurse -n 50 --no-pager`. |
| **504 Gateway Timeout** beim Laden | Yahoo Finance antwortet langsam. Zeitraum verkleinern; die Zeitgrenzen stehen in `deploy/nginx-aktien-kurse.conf` (`proxy_read_timeout`). |
| Passwortabfrage kommt nicht | `nginx -t` und `systemctl reload nginx`; prüfen, ob `/etc/nginx/aktien-kurse.htpasswd` existiert. |
| „Keine Daten für …“ | Symbol oder Zeitraum liefert bei Yahoo Finance nichts (Wochenende, Feiertage, falsches Symbol). |
| Ausgesperrt nach Firewall-Änderung | Über die **Konsole** in der Hetzner-Cloud-Oberfläche anmelden (funktioniert ohne SSH) und `ufw allow OpenSSH` ausführen. |

---

## 7. Sicherheitshinweise

- Der Passwortschutz von nginx ist **HTTP-Basic-Auth**: sicher genug hinter HTTPS,
  aber kein Ersatz für eine echte Benutzerverwaltung. Ein ordentliches Passwort
  wählen und nicht anderweitig wiederverwenden.
- `server.py` bleibt an `127.0.0.1` gebunden — der Anwendungsserver ist also aus dem
  Internet nicht direkt erreichbar, nur über nginx. Diese Bindung nicht auf `0.0.0.0`
  ändern, sonst umgeht man den Passwortschutz.
- Die Firewall lässt nur SSH, HTTP und HTTPS zu. Zusätzlich lässt sich in der
  Hetzner-Console eine Cloud-Firewall davorschalten (greift schon vor dem Server).
- Sicherheitsupdates spielt `unattended-upgrades` automatisch ein; ein
  `apt update && apt upgrade` von Hand alle paar Wochen schadet trotzdem nicht.
- Wer den Zugang noch enger fassen will, ersetzt den Passwortschutz durch eine
  IP-Freigabe (`allow <deine-ip>; deny all;` im `server`-Block) oder erreicht den
  Server ausschließlich per SSH-Tunnel:
  `ssh -L 8000:127.0.0.1:8000 root@<SERVER-IP>`, dann `http://localhost:8000`.
