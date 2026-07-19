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
| Frontend   | `index.html` (HTML + JS) und `styles.css` — Vanilla JS, handgebautes SVG-Chart, keine externen Bibliotheken |

Python-Abhängigkeiten (siehe [requirements.txt](requirements.txt)): `yfinance`, `SQLAlchemy`.
Der Code nutzt moderne Typannotationen (`list[tuple[date, float]]`, `str | None`)
und benötigt daher **Python ≥ 3.10** (getestet mit 3.11).

## 2. Architektur

```
┌─────────────┐   HTTP    ┌─────────────┐          ┌─────────────┐
│ index.html  │ ────────▶ │  server.py  │ ───────▶ │    db.py    │
│ (Browser)   │  /api/…   │ HTTP-Server │          │ Cache + ORM │
└─────────────┘           └──────┬──────┘          └──────┬──────┘
                                 │                  ▲     │ bei Cache-Lücke
                                 ▼                  │     ▼
                          ┌─────────────┐           │  ┌─────────────┐
                          │simulation.py│ ──────────┤  │   dax.py    │
                          │ Engine      │           │  │ yfinance    │
                          └──────┬──────┘           │  └──────┬──────┘
                                 ▼                  │         ▼
                          ┌─────────────┐           │   Yahoo Finance
                          │ trigger.py  │           │
                          │ Bewerter    │  ┌────────┴────┐
                          └─────────────┘  │ fetch_dax.py│
┌─────────────┐                            │ (CLI)       │
│  kurse.db   │ ◀── SQLAlchemy ──────      └─────────────┘
└─────────────┘
```

Die Schichten sind strikt getrennt:

- [dax.py](dax.py) — **reiner Yahoo-Finance-Zugriff**, kennt weder Datenbank noch Server.
- [db.py](db.py) — **Datenbank- und Cache-Schicht** für die Kurse.
- [trigger.py](trigger.py) — **Kauf-/Verkauf-Bewerter** der Handelssimulation (reine Logik, keine DB).
- [simulation.py](simulation.py) — **Simulationsengine** samt Persistenz der Läufe (nutzt db.py und trigger.py).
- [server.py](server.py) — **dünner HTTP-Adapter**: Routen, JSON-Ein-/Ausgabe, Fehlercodes.
- [fetch_dax.py](fetch_dax.py) — **CLI-Adapter** auf dieselbe `db.py`-Logik (Vorbefüllen der DB).
- [index.html](index.html) — Frontend-Markup und -Logik (HTML + JS); das Stylesheet liegt in [styles.css](styles.css).

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
| `hole_kurse_roh(start, end, symbol)` | Einstiegspunkt der Anwendung: Kurse mit Cache-Nachladen (siehe oben), als `(date, float)`-Tupel — wird auch von der Simulationsengine genutzt. |
| `hole_kurse(start, end, symbol)` | Wie `hole_kurse_roh()`, aber formatiert für die API (`TT.MM.JJJJ`). |
| `liste_werte()` | Alle Werte inkl. `anzahl_kurse` und Cache-Zeitraum (für den „Symbole“-Tab). |
| `fuege_wert_hinzu(symbol, name, einheit, einheit_lang)` | Neuen Wert anlegen. Validiert das Symbol per Probeabruf (letzte 60 Tage); ohne Name wird der Yahoo-Anzeigename übernommen. Wirft `ValueError` bei leerem, doppeltem oder ungültigem Symbol. |

Interne Helfer: `_hole_oder_lege_wert_an()` (Wert per Symbol finden oder anlegen),
`_lade_und_speichere()` (Yahoo-Abruf + Duplikat-freies Einfügen).

### 3.3 trigger.py und simulation.py — Handelssimulation

Die Simulation ist in zwei Module geteilt:

**trigger.py** — die Bewerter. Gemeinsame Schnittstelle
`pruefe(i, kurse, kaufkurs) -> bool`; konfiguriert über `{"typ": …, <parameter>}`.

| Familie | Typ | Bedeutung |
|---------|-----|-----------|
| Kauf    | `sma_kreuzung` (`periode`) | Kurs kreuzt SMA(periode) von unten nach oben |
| Kauf    | `immer` | kauft am ersten möglichen Tag (Buy & Hold) |
| Verkauf | `sma_kreuzung` (`periode`) | Kurs kreuzt SMA(periode) von oben nach unten |
| Verkauf | `stop_take` (`stop_prozent`, `take_prozent`) | Verlust-/Gewinnschwelle seit Kauf |
| Verkauf | `nie` | hält bis zum Ende |

Neue Trigger-Typen werden in `erzeuge_kauf_bewerter()` /
`erzeuge_verkauf_bewerter()` als weiterer Zweig ergänzt — die Engine bleibt
unangetastet. `benoetigter_vorlauf()` meldet, wie viele Handelstage
Vorgeschichte die Trigger vor dem Simulationsstart brauchen (SMA-Perioden).

**simulation.py** — die Engine und die Persistenz:

- `SimulationsEngine(config).laufe()` — der Kern: lädt die Kurse inkl. Vorlauf
  über `hole_kurse_roh()` (Cache!), läuft **Tag für Tag** über die
  Eröffnungskurse und befragt die Bewerter: ohne Position den Kauf-Trigger
  (gekauft wird mit dem gesamten Cash), mit Position den Verkauf-Trigger
  (verkauft wird alles). Für **jeden Handelstag** wird der Tagesendstand
  (Cash + Anteile × Kurs) festgehalten.
- **Karenzzeit** (`karenz_tage`, Standard 0): Nach jedem ausgeführten Trade
  werden für so viele Handelstage weder Kauf- noch Verkauf-Trigger geprüft
  (Sperre `gesperrt_bis` im Tages-Loop) — dämpft Whipsaw-Signale. Für
  Bestands-Datenbanken ergänzt `_migriere_karenz_spalte()` die Spalte per
  `ALTER TABLE` (create_all() legt keine neuen Spalten an).
- Vereinfachungen (bewusst): Handel nur in **USD** (Feld `waehrung` ist für
  weitere Währungen vorbereitet, andere Werte werden abgelehnt), teilbare
  Anteile, keine Gebühren, Ausführung zum Eröffnungskurs des Signaltags.
- `starte_simulation(config)` (validieren → laufen → speichern),
  `liste_simulationen()`, `hole_simulation(id)`, `loesche_simulation(id)`
  (Cascade löscht Tagesdaten und Trades mit) — die API-Einstiegspunkte.

Datenmodell (zusätzlich zu `wert`/`kurs`):

```
simulation                          simulations_tag          simulations_trade
──────────                          ───────────────          ─────────────────
id, name, symbol                    id, simulation_id FK     id, simulation_id FK
start, ende (ausschließend)         datum, kurs              datum, typ (kauf|verkauf)
kapital, waehrung ("USD")           cash, anteile            kurs, anteile, betrag
karenz_tage
kauf_trigger, verkauf_trigger (JSON)  endstand  ← Tagesendstand
erstellt_am, endstand,
rendite_prozent, anzahl_trades
```

### 3.4 server.py — HTTP-Server und API

Basiert auf `http.server.SimpleHTTPRequestHandler` — statische Dateien kommen
aus dem **aktuellen Arbeitsverzeichnis** (deshalb den Server immer aus dem
Projektordner starten). Der Server ist ein `ThreadingHTTPServer` (jede Anfrage
in eigenem Thread, ein langsamer Yahoo-Abruf blockiert also nichts) und lauscht
nur auf `127.0.0.1:8000` (Konstanten `HOST`/`PORT`). Der Handler setzt
`Cache-Control: no-cache`, damit Änderungen an `index.html` sofort sichtbar sind.

Start: `python server.py` → http://localhost:8000

### 3.5 fetch_dax.py — CLI zum Vorbefüllen

```bash
python fetch_dax.py --symbol AAPL --start 2020-01-01 --end 2026-07-01
```

Nutzt exakt dieselbe `hole_kurse()`-Logik wie der Server, d. h. der Aufruf
befüllt den Cache in `kurse.db`. Standardwerte: `^GDAXI`, `2023-07-01` bis
`2026-07-01`. Exit-Code 1, wenn keine Daten gefunden wurden.

### 3.6 index.html + styles.css — Frontend

Markup und JavaScript in `index.html`, das Stylesheet separat in `styles.css`
(helles Design, CSS-Variablen in `:root`, Akzent Indigo/Sky). Die Seite nutzt
die volle Browserbreite; beide Charts zeichnen sich bei Größenänderung des
Fensters neu.
Zwei Navigationsebenen: ein **Hauptmenü** in der Kopfleiste (`zeigeMenue()`)
wechselt zwischen den Bereichen, innerhalb eines Bereichs wechseln **Tabs**
(`zeigeTab()`, wirkt nur auf Panels des eigenen Bereichs — neue Tabs brauchen
nur ein `panel-<name>`-Div plus einen Tab-Button im jeweiligen `<section>`):

- Menü **Kurse** (mit der Ladeleiste für Wert/Zeitraum):
  - Tab **Tabelle** — Kursliste mit Statistik (Info-/Stats-Bereich).
  - Tab **Chart** — handgebautes SVG-Liniendiagramm (Details unten).
  - Tab **Indikator-Hilfe** — statische Dokumentation der Chart-Indikatoren
    und ihrer Bedienung (`panel-indi-hilfe`).
- Menü **Simulation**:
  - Tab **Neuer Lauf** — Konfigurationsformular (Wert, Zeitraum, Kapital,
    Kauf-/Verkauf-Trigger mit typabhängigen Parameterfeldern, `zeigeSimFelder()`),
    startet den Lauf per `POST /api/simulationen` (`starteSimulation()`).
  - Tab **Läufe** — alle gespeicherten Läufe (`ladeSimulationen()`); Klick auf
    eine Zeile öffnet die Detailansicht (`zeigeSimDetail()`): Kennzahlen-Karten,
    Kapitalverlaufs-Chart der Tagesendstände (`zeichneVerlauf()`, eigenes
    kleines SVG mit Startkapital-Referenzlinie, Kurslinie auf rechter Skala
    und Rechteck-Zoom wie im Kurs-Chart: `simZoom`, aufheben per Button oder
    Doppelklick) und Trade-Liste. Jede Zeile hat einen 🗑-Button
    (`loescheSimulation()`, mit Rückfrage → `DELETE /api/simulationen/<id>`).
  - Tab **Trigger-Hilfe** — statische Dokumentation aller Kauf-/Verkauf-Trigger,
    der Karenzzeit und des Engine-Ablaufs (reines HTML, `panel-sim-hilfe`).
- Menü **Verwaltung**:
  - Tab **Symbolliste** — alle Werte aus `GET /api/werte` mit Cache-Stand.
  - Tab **Neues Symbol** — Formular für `POST /api/werte` (`fuegeSymbolHinzu()`).

Beim Wechsel zurück ins Kurse-Menü wird ein aktives Chart neu gezeichnet
(im versteckten Zustand hat das SVG keine Breite).

Das **Chart** im Detail:
  - Zeitraum-Schnellwahl (Range-Buttons),
  - **Zoom per Maus**: mit gedrückter Taste ein Rechteck aufziehen → das Chart
    zeigt nur noch diese Zeitspanne (`zoomBereich`, Indizes in `daxDaten`);
    aufheben per „✕ Zoom aufheben“-Button, Doppelklick ins Chart oder
    Zeitraum-Schnellwahl,
  - zuschaltbaren Indikatoren: **Bollinger-Bänder**, **SMA 50**, **SMA 200**,
    **EMA 20**, **Signale** — Checkboxen im aufklappbaren Menü „Indikatoren ▾“
    (`toggleIndiMenue()`, schließt bei Klick außerhalb; neu zeichnen via
    `zeichneChart(daxDaten, aktiveTage)`),
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

### GET /api/simulationen

Alle gespeicherten Simulationsläufe, neueste zuerst — Kennzahlen ohne Tagesdaten:

```
200 → [{"id": 5, "name": "DAX: SMA-200-Kreuzung → Stop −8% / Take +25%",
        "symbol": "^GDAXI", "start": "01.01.2018", "ende": "01.07.2026",
        "kapital": 25000.0, "waehrung": "USD",
        "kauf_trigger": {"typ": "sma_kreuzung", "periode": 200},
        "verkauf_trigger": {"typ": "stop_take", "stop_prozent": 8, "take_prozent": 25},
        "erstellt_am": "17.07.2026 14:02", "endstand": 37946.06,
        "rendite_prozent": 51.78, "anzahl_trades": 13}, …]
```

### GET /api/simulationen/&lt;id&gt;

Ein Lauf im Detail: dieselben Kennzahlen plus `trades` (Datum, Typ, Kurs,
Anteile, Betrag) und `tage` (Datum, Kurs, **Tagesendstand**).

```
404 → {"fehler": "Simulation 99 nicht gefunden."}
```

### DELETE /api/simulationen/&lt;id&gt;

Löscht einen gespeicherten Lauf endgültig — die zugehörigen Tagesdaten und
Trades werden per Cascade mitgelöscht.

```
200 → {"geloescht": 5}
400 → {"fehler": "Ungültige Simulations-ID."}
404 → {"fehler": "Simulation 99 nicht gefunden."}
```

### POST /api/simulationen

Führt einen Simulationslauf aus und speichert ihn. Body = Konfiguration
(siehe `SimulationsEngine` in [simulation.py](simulation.py)):

```json
{"symbol": "^GDAXI", "start": "2018-01-01", "ende": "2026-07-01",
 "kapital": 25000, "karenz_tage": 10, "waehrung": "USD", "name": "optional",
 "kauf_trigger":    {"typ": "sma_kreuzung", "periode": 200},
 "verkauf_trigger": {"typ": "stop_take", "stop_prozent": 8, "take_prozent": 25}}
```

`karenz_tage` (optional, Standard 0): Handelstage nach jedem Trade, in denen
kein weiterer Kauf/Verkauf ausgelöst wird.

```
201 → Kennzahlen wie bei GET /api/simulationen (inkl. vergebener "id")
400 → {"fehler": "…"}   (ungültige Konfiguration, ValueError aus der Engine)
```

Fehlende Kurszeiträume werden dabei automatisch von Yahoo nachgeladen
(inkl. Vorlauf für SMA-Trigger) — der erste Lauf für einen neuen Wert kann
daher etwas dauern.

## 5. Entwicklungs-Workflow

```bash
pip install -r requirements.txt   # einmalig
python server.py                  # Server starten (legt kurse.db bei Bedarf an)
# Browser: http://localhost:8000
```

- **Frontend-Änderungen:** `index.html` bzw. `styles.css` editieren, Browser
  neu laden (kein Build, Server sendet `no-cache`).
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
- **Neuer Simulations-Trigger:** Bewerter-Klasse in [trigger.py](trigger.py)
  schreiben (Schnittstelle `pruefe(i, kurse, kaufkurs)`), in
  `erzeuge_kauf_bewerter()` bzw. `erzeuge_verkauf_bewerter()` registrieren,
  ggf. `benoetigter_vorlauf()` erweitern — und im Formular in
  [index.html](index.html) eine `<option>` plus Parameterfelder ergänzen
  (`zeigeSimFelder()`, `starteSimulation()`).
- **Weitere Währungen:** Das Feld `waehrung` ist in Konfiguration und
  Datenmodell bereits vorhanden; die Engine lehnt derzeit alles außer "USD"
  ab (eine Stelle in `SimulationsEngine.__init__`). Für echten Mehrwährungs-
  Handel fehlt vor allem die Kursumrechnung.

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
