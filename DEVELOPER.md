# Entwickler-Dokumentation — aktien-kurse

Diese Dokumentation richtet sich an Entwickler, die das Projekt verstehen, warten
oder erweitern wollen. Für die reine Benutzung siehe [README.md](README.md).

## 1. Überblick

Die Anwendung lädt historische **Eröffnungskurse** verschiedener Werte (Indizes,
Aktien, Krypto) von **Yahoo Finance**, speichert sie in einer lokalen
**SQLite-Datenbank** (Cache mit Nachladen) und zeigt sie im Browser als Tabelle
und interaktives SVG-Chart an.

**Technologie-Stack:**

| Schicht    | Technologie                                              |
|------------|----------------------------------------------------------|
| Datenquelle| Yahoo Finance via [`yfinance`](https://pypi.org/project/yfinance/) |
| Datenbank  | SQLite via SQLAlchemy 2.x (ORM, `DeclarativeBase`)       |
| Backend    | Python-Standardbibliothek (`http.server`, kein Framework)|
| Frontend   | Eine einzelne `index.html` — Vanilla JS, handgebautes SVG-Chart, keine externen Bibliotheken |

Python-Abhängigkeiten (siehe [requirements.txt](requirements.txt)): `yfinance`, `SQLAlchemy`.
Der Code nutzt moderne Typannotationen (`list[tuple[date, float]]`, `str | None`)
und benötigt daher **Python ≥ 3.10** (getestet mit 3.11).

## 2. Architektur

```
┌─────────────┐   HTTP    ┌─────────────┐          ┌─────────────┐
│ index.html  │ ────────▶ │  server.py  │ ───────▶ │    db.py    │
│ (Browser)   │  /api/…   │ HTTP-Server │          │ Cache + ORM │
└─────────────┘           └─────────────┘          └──────┬──────┘
                                                    ▲     │ bei Cache-Lücke
                          ┌─────────────┐           │     ▼
                          │ fetch_dax.py│ ──────────┘  ┌─────────────┐
                          │ (CLI)       │              │   dax.py    │
                          └─────────────┘              │ yfinance    │
                                                       └──────┬──────┘
┌─────────────┐                                               ▼
│  kurse.db   │ ◀── SQLAlchemy ──────────────────      Yahoo Finance
└─────────────┘
```

Die Schichten sind strikt getrennt:

- [dax.py](dax.py) — **reiner Yahoo-Finance-Zugriff**, kennt weder Datenbank noch Server.
- [db.py](db.py) — **Datenbank- und Cache-Schicht**, einziger Ort mit Geschäftslogik.
- [server.py](server.py) — **dünner HTTP-Adapter**: Routen, JSON-Ein-/Ausgabe, Fehlercodes.
- [fetch_dax.py](fetch_dax.py) — **CLI-Adapter** auf dieselbe `db.py`-Logik (Vorbefüllen der DB).
- [index.html](index.html) — komplettes Frontend in einer Datei (HTML + CSS + JS).

## 3. Module im Detail

### 3.1 dax.py — Yahoo-Finance-Zugriff

| Funktion | Zweck |
|----------|-------|
| `lade_dax_roh(start, end, symbol)` | Lädt Eröffnungskurse als `list[tuple[date, float]]`, aufsteigend sortiert. `start`/`end` im Format `JJJJ-MM-TT`, `end` **ausschließend** (Yahoo-Konvention). Leere Liste, wenn Yahoo nichts liefert. |
| `hole_name(symbol)` | Anzeigename (`shortName`/`longName`) von Yahoo, `None` bei Fehler. |

Standard-Symbol ist überall `^GDAXI` (DAX). Kurse werden auf 2 Nachkommastellen
gerundet. Die Modulnamen (`dax.py`, `/api/dax`) sind historisch — das Projekt
begann als reiner DAX-Viewer und unterstützt inzwischen beliebige
Yahoo-Symbole.

### 3.2 db.py — Datenmodell und Cache

**Datenmodell** (SQLite-Datei `kurse.db`, wird automatisch angelegt):

```
wert                                kurs
────                                ────
id            PK                    id          PK
symbol        unique, index         wert_id     FK → wert.id, index
name                                datum       Date, index
einheit       z. B. "Pkt.", "$"     eroeffnung  Float
einheit_lang  z. B. "Punkte","USD"
cached_von    Date | NULL           UNIQUE(wert_id, datum)  ← uq_wert_datum
cached_bis    Date | NULL
```

- `Wert` = ein handelbares Instrument; `Kurs` = ein Eröffnungskurs pro Handelstag.
- Beziehung `Wert.kurse` mit `cascade="all, delete-orphan"` — löscht man einen
  Wert, verschwinden seine Kurse mit.
- `STANDARD_WERTE` (DAX, S&P 500, Apple, …) wird bei `init_db()` in die
  `wert`-Tabelle geschrieben; die Liste entspricht dem `<select id="symbol">`
  in `index.html`.

**Cache-Strategie** (Kern der Anwendung, in `hole_kurse()`):

Jeder `Wert` merkt sich mit `cached_von`/`cached_bis` **einen einzigen
zusammenhängenden Zeitraum**, der bereits vollständig aus Yahoo geladen wurde.

1. Liegt der angefragte Zeitraum `[start, end)` komplett innerhalb der
   Abdeckung → Antwort direkt aus der DB, kein API-Aufruf.
2. Sonst wird der **Vereinigungsbereich** aus Anfrage und bisheriger Abdeckung
   von Yahoo geladen (`min(start, cached_von)` bis `max(end, cached_bis)`),
   damit die Abdeckung lückenlos bleibt. Bereits vorhandene Tage werden
   übersprungen (Abgleich gegen die DB, zusätzlich abgesichert durch den
   Unique-Constraint).
3. Ausgeliefert wird **immer aus der Datenbank**, nie direkt aus der API-Antwort.

Konsequenz: Fragt man erst 2010 und dann 2024 an, wird der gesamte Zwischenraum
mitgeladen. Das ist bewusst so — ein Intervall pro Wert hält die Logik einfach.

**Öffentliche Funktionen:**

| Funktion | Zweck |
|----------|-------|
| `init_db()` | Tabellen anlegen + Standardwerte einfügen (idempotent). Muss vor allem anderen laufen; `server.py` und `fetch_dax.py` rufen sie beim Start auf. |
| `hole_kurse(start, end, symbol)` | Einstiegspunkt der Anwendung: Kurse mit Cache-Nachladen (siehe oben). |
| `liste_werte()` | Alle Werte inkl. `anzahl_kurse` und Cache-Zeitraum (für den „Symbole“-Tab). |
| `fuege_wert_hinzu(symbol, name, einheit, einheit_lang)` | Neuen Wert anlegen. Validiert das Symbol per Probeabruf (letzte 60 Tage); ohne Name wird der Yahoo-Anzeigename übernommen. Wirft `ValueError` bei leerem, doppeltem oder ungültigem Symbol. |

Interne Helfer: `_hole_oder_lege_wert_an()` (Wert per Symbol finden oder anlegen),
`_lade_und_speichere()` (Yahoo-Abruf + Duplikat-freies Einfügen).

### 3.3 server.py — HTTP-Server und API

Basiert auf `http.server.SimpleHTTPRequestHandler` — statische Dateien kommen
aus dem **aktuellen Arbeitsverzeichnis** (deshalb den Server immer aus dem
Projektordner starten). Der Server ist ein `ThreadingHTTPServer` (jede Anfrage
in eigenem Thread, ein langsamer Yahoo-Abruf blockiert also nichts) und lauscht
nur auf `127.0.0.1:8000` (Konstanten `HOST`/`PORT`). Der Handler setzt
`Cache-Control: no-cache`, damit Änderungen an `index.html` sofort sichtbar sind.

Start: `python server.py` → http://localhost:8000

### 3.4 fetch_dax.py — CLI zum Vorbefüllen

```bash
python fetch_dax.py --symbol AAPL --start 2020-01-01 --end 2026-07-01
```

Nutzt exakt dieselbe `hole_kurse()`-Logik wie der Server, d. h. der Aufruf
befüllt den Cache in `kurse.db`. Standardwerte: `^GDAXI`, `2023-07-01` bis
`2026-07-01`. Exit-Code 1, wenn keine Daten gefunden wurden.

### 3.5 index.html — Frontend

Eine Datei, helles Design (CSS-Variablen in `:root`, Akzent Indigo/Sky).
Zwei Navigationsebenen: ein **Hauptmenü** in der Kopfleiste (`zeigeMenue()`)
wechselt zwischen den Bereichen, innerhalb eines Bereichs wechseln **Tabs**
(`zeigeTab()`, wirkt nur auf Panels des eigenen Bereichs — neue Tabs brauchen
nur ein `panel-<name>`-Div plus einen Tab-Button im jeweiligen `<section>`):

- Menü **Kurse** (mit der Ladeleiste für Wert/Zeitraum):
  - Tab **Tabelle** — Kursliste mit Statistik (Info-/Stats-Bereich).
  - Tab **Chart** — handgebautes SVG-Liniendiagramm (Details unten).
- Menü **Verwaltung**:
  - Tab **Symbolliste** — alle Werte aus `GET /api/werte` mit Cache-Stand.
  - Tab **Neues Symbol** — Formular für `POST /api/werte` (`fuegeSymbolHinzu()`).

Beim Wechsel zurück ins Kurse-Menü wird ein aktives Chart neu gezeichnet
(im versteckten Zustand hat das SVG keine Breite).

Das **Chart** im Detail:
  - Zeitraum-Schnellwahl (Range-Buttons),
  - zuschaltbaren Indikatoren: **Bollinger-Bänder**, **SMA 50**, **SMA 200**,
    **EMA 20** (Checkboxen, neu zeichnen via `zeichneChart(daxDaten, aktiveTage)`),
  - **Signal-Markern**: ▲/▼-Dreiecke an jedem Tag, an dem der Kurs den
    SMA 200 nach oben bzw. unten kreuzt (Erkennung: `findeKreuzungen()`,
    generisch für beliebige Indikator-Serien; der Tooltip zeigt das Signal mit an),
  - Crosshair mit Tooltip (Datum + Kurs), Flächen-Gradient, Gitternetz.

Zentrale JS-Funktionen: `ladeWerte()` (füllt das Symbol-Dropdown und die
Symbolliste), `ladeDaten()` (holt Kurse von `/api/dax`, rendert Tabelle und
Chart), `zeichneChart()` (SVG-Rendering inkl. Indikatoren). Einheit und
Langform (`Pkt.`/`Punkte`, `$`/`USD`, …) hängen als `data`-Attribute an den
`<option>`-Elementen und steuern die Beschriftung.

Es gibt **keinen Build-Schritt** — Datei ändern, Browser neu laden, fertig.

## 4. API-Referenz

Alle Antworten sind JSON (`charset=utf-8`). Fehler haben die Form
`{"fehler": "…"}`.

### GET /api/dax

Kursdaten eines Zeitraums; fehlende Zeiträume werden automatisch von Yahoo
nachgeladen.

| Parameter | Standard     | Beschreibung                          |
|-----------|--------------|---------------------------------------|
| `start`   | `2023-07-01` | Startdatum `JJJJ-MM-TT` (einschließend)|
| `end`     | `2026-07-01` | Enddatum `JJJJ-MM-TT` (**ausschließend**)|
| `symbol`  | `^GDAXI`     | Yahoo-Finance-Symbol                   |

```
GET /api/dax?start=2024-01-01&end=2024-02-01&symbol=AAPL
200 → [{"datum": "02.01.2024", "eroeffnung": 187.15}, …]
404 → {"fehler": "Keine Daten für AAPL (… bis …)."}
500 → {"fehler": "…"}   (z. B. ungültiges Datumsformat, Yahoo nicht erreichbar)
```

### GET /api/werte

Alle Werte der Datenbank:

```
200 → [{"symbol": "^GDAXI", "name": "DAX", "einheit": "Pkt.",
        "einheit_lang": "Punkte", "cached_von": "01.07.2023",
        "cached_bis": "01.07.2026", "anzahl_kurse": 760}, …]
```

### POST /api/werte

Neuen Wert anlegen. Body (JSON): `symbol` (Pflicht, wird upper-gecased),
`name`, `einheit`, `einheit_lang` (optional).

```
201 → {"symbol": "NVDA", "name": "NVIDIA Corporation", "einheit": "$", "einheit_lang": "USD"}
400 → {"fehler": "„NVDA“ ist bereits vorhanden."}          (ValueError aus db.py)
400 → {"fehler": "Ungültiger Anfrageinhalt (JSON erwartet)."}
500 → {"fehler": "…"}
```

Hinweis: Das Anlegen macht einen Probeabruf bei Yahoo (letzte 60 Tage) und
kann daher 1–2 Sekunden dauern.

## 5. Entwicklungs-Workflow

```bash
pip install -r requirements.txt   # einmalig
python server.py                  # Server starten (legt kurse.db bei Bedarf an)
# Browser: http://localhost:8000
```

- **Frontend-Änderungen:** `index.html` editieren, Browser neu laden
  (kein Build, Server sendet `no-cache`).
- **Backend-Änderungen:** Server neu starten (Strg+C, erneut `python server.py`).
- **Datenbank zurücksetzen:** Server stoppen, `kurse.db` löschen — sie wird beim
  nächsten Start neu angelegt und mit `STANDARD_WERTE` befüllt.
- **Cache eines Werts zurücksetzen:** aktuell nur per Hand, z. B.
  `sqlite3 kurse.db "DELETE FROM kurs WHERE wert_id=(SELECT id FROM wert WHERE symbol='AAPL'); UPDATE wert SET cached_von=NULL, cached_bis=NULL WHERE symbol='AAPL';"`
- Es gibt derzeit **keine automatisierten Tests**.

Git-Konventionen (aus der Historie): Branches nach dem Muster
`feature/<thema>` und `fix/<thema>`, Hauptbranch `main`.

## 6. Erweiterungspunkte

- **Neues Symbol dauerhaft aufnehmen:** Eintrag in `STANDARD_WERTE`
  ([db.py](db.py)) **und** im `<select id="symbol">` in
  [index.html](index.html) ergänzen — oder einfach zur Laufzeit über den
  „Symbole“-Tab bzw. `POST /api/werte` anlegen.
- **Andere Kursart (Schluss statt Eröffnung):** `lade_dax_roh()` liest
  `row["Open"]` — auf `"Close"` umstellen; Spaltenname `eroeffnung` und
  Frontend-Beschriftungen dann konsequent mit anpassen.
- **Neuer API-Endpunkt:** Route in `do_GET`/`do_POST` in
  [server.py](server.py) ergänzen, Logik in [db.py](db.py) implementieren,
  `send_json()` für die Antwort verwenden.
- **Neuer Chart-Indikator:** in `index.html` Checkbox + Legende + `<path>` im
  SVG ergänzen und die Berechnung in `zeichneChart()` einhängen (Vorbild:
  SMA 50/200, EMA 20, Bollinger).
- **Neue Signal-Marker:** `findeKreuzungen(kurse, serie)` ist bewusst generisch —
  für z. B. SMA-50-Kreuzungen dieselbe Funktion mit der SMA-50-Serie aufrufen
  und im Marker-Block von `zeichneChart()` zeichnen (Vorbild: SMA-200-Signale).

## 7. Bekannte Eigenheiten & Grenzen

- **Kein Framework:** bewusst nur Standardbibliothek plus SQLAlchemy/yfinance.
- **Ein Cache-Intervall pro Wert:** Weit auseinanderliegende Anfragen führen
  dazu, dass auch der Zwischenraum geladen wird (bewusste Vereinfachung,
  siehe Abschnitt 3.2).
- **Keine Authentifizierung/CORS-Behandlung:** Der Server ist nur für den
  lokalen Einsatz gedacht und bindet deshalb ausschließlich auf `127.0.0.1`.
- **Yahoo-Finance-Abhängigkeit:** `yfinance` ist ein inoffizieller Client —
  bei Änderungen an Yahoos API kann das Laden ausfallen; dank Cache bleiben
  bereits geladene Daten nutzbar.
