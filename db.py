"""Datenbankschicht der Kurs-Anwendung (SQLAlchemy auf SQLite).

Zwei Entitäten:

  Wert  — verwaltet die Aktien/Instrumente (Symbol, Name, Einheit) und merkt
          sich, welcher Zeitraum bereits im Cache liegt (cached_von/cached_bis).
  Kurs  — die einzelnen Eröffnungskurse, jeweils einem Wert zugeordnet.

hole_kurse() ist der Einstiegspunkt für die Anwendung: es liefert die Kurse
eines Zeitraums und lädt fehlende Zeiträume bei Bedarf von Yahoo Finance nach
(Cache mit Nachladen)."""

from datetime import date, datetime, timedelta

from sqlalchemy import (
    Date, Float, ForeignKey, String, UniqueConstraint, create_engine, func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, Session, mapped_column, relationship,
)

from dax import hole_name, lade_dax_roh

# ── Bekannte Werte: dieselbe Liste wie im <select> von index.html. ──
# Wird beim ersten Start in die Wert-Tabelle geschrieben, damit Name und
# Einheit auch ohne vorherigen API-Abruf bekannt sind.
STANDARD_WERTE = [
    ("^GDAXI",  "DAX",       "Pkt.", "Punkte"),
    ("^GSPC",   "S&P 500",   "Pkt.", "Punkte"),
    ("^DJI",    "Dow Jones", "Pkt.", "Punkte"),
    ("AAPL",    "Apple",     "$",    "USD"),
    ("MSFT",    "Microsoft", "$",    "USD"),
    ("TSLA",    "Tesla",     "$",    "USD"),
    ("SAP.DE",  "SAP",       "€",    "EUR"),
    ("SIE.DE",  "Siemens",   "€",    "EUR"),
    ("BTC-USD", "Bitcoin",   "$",    "USD"),
]

DB_DATEI = "kurse.db"
engine = create_engine(f"sqlite:///{DB_DATEI}")


class Base(DeclarativeBase):
    pass


class Wert(Base):
    """Ein handelbarer Wert (Index, Aktie, Krypto …)."""
    __tablename__ = "wert"

    id:           Mapped[int] = mapped_column(primary_key=True)
    symbol:       Mapped[str] = mapped_column(String, unique=True, index=True)
    name:         Mapped[str] = mapped_column(String)
    einheit:      Mapped[str] = mapped_column(String, default="")
    einheit_lang: Mapped[str] = mapped_column(String, default="")

    # Bereits im Cache abgedeckter Zeitraum (None = noch nichts geladen).
    cached_von: Mapped[date | None] = mapped_column(Date, default=None)
    cached_bis: Mapped[date | None] = mapped_column(Date, default=None)

    kurse: Mapped[list["Kurs"]] = relationship(
        back_populates="wert", cascade="all, delete-orphan"
    )


class Kurs(Base):
    """Ein Eröffnungskurs eines Werts an einem Handelstag."""
    __tablename__ = "kurs"
    __table_args__ = (UniqueConstraint("wert_id", "datum", name="uq_wert_datum"),)

    id:         Mapped[int]   = mapped_column(primary_key=True)
    wert_id:    Mapped[int]   = mapped_column(ForeignKey("wert.id"), index=True)
    datum:      Mapped[date]  = mapped_column(Date, index=True)
    eroeffnung: Mapped[float] = mapped_column(Float)

    wert: Mapped["Wert"] = relationship(back_populates="kurse")


def init_db() -> None:
    """Legt die Tabellen an und befüllt die Wert-Tabelle mit den Standardwerten."""
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        vorhanden = set(s.scalars(select(Wert.symbol)))
        for symbol, name, einheit, einheit_lang in STANDARD_WERTE:
            if symbol not in vorhanden:
                s.add(Wert(symbol=symbol, name=name,
                           einheit=einheit, einheit_lang=einheit_lang))
        s.commit()


def _hole_oder_lege_wert_an(s: Session, symbol: str) -> Wert:
    """Sucht den Wert zum Symbol oder legt ihn (mit Symbol als Name) neu an."""
    wert = s.scalar(select(Wert).where(Wert.symbol == symbol))
    if wert is None:
        wert = Wert(symbol=symbol, name=symbol)
        s.add(wert)
        s.flush()
    return wert


def _lade_und_speichere(s: Session, wert: Wert, start: date, end: date) -> None:
    """Holt [start, end) von Yahoo und speichert neue Kurse (überspringt Duplikate)."""
    roh = lade_dax_roh(start.isoformat(), end.isoformat(), wert.symbol)
    if not roh:
        return
    bekannt = {
        d for d in s.scalars(
            select(Kurs.datum).where(
                Kurs.wert_id == wert.id,
                Kurs.datum >= start,
                Kurs.datum < end,
            )
        )
    }
    for datum, eroeffnung in roh:
        if datum not in bekannt:
            s.add(Kurs(wert_id=wert.id, datum=datum, eroeffnung=eroeffnung))


def liste_werte() -> list[dict]:
    """Liefert alle Werte der Datenbank inkl. Kurs-Anzahl und Cache-Zeitraum."""
    with Session(engine) as s:
        zaehler = dict(
            s.execute(select(Kurs.wert_id, func.count()).group_by(Kurs.wert_id)).all()
        )
        return [
            {
                "symbol":       w.symbol,
                "name":         w.name,
                "einheit":      w.einheit,
                "einheit_lang": w.einheit_lang,
                "cached_von":   w.cached_von.strftime("%d.%m.%Y") if w.cached_von else None,
                "cached_bis":   w.cached_bis.strftime("%d.%m.%Y") if w.cached_bis else None,
                "anzahl_kurse": zaehler.get(w.id, 0),
            }
            for w in s.scalars(select(Wert).order_by(Wert.id))
        ]


def fuege_wert_hinzu(symbol: str, name: str = "",
                     einheit: str = "", einheit_lang: str = "") -> dict:
    """
    Legt einen neuen Wert an — aber nur, wenn Yahoo Finance dafür Kurse liefert.

    Zur Prüfung werden die letzten 60 Tage abgefragt; kommt nichts zurück, gilt
    das Symbol als ungültig. Ohne angegebenen Namen wird der Anzeigename von
    Yahoo übernommen (Rückfall: das Symbol selbst).

    Wirft ValueError bei leerem, bereits vorhandenem oder ungültigem Symbol.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Kein Symbol angegeben.")

    with Session(engine) as s:
        if s.scalar(select(Wert).where(Wert.symbol == symbol)):
            raise ValueError(f"„{symbol}“ ist bereits vorhanden.")

    heute = date.today()
    probe = lade_dax_roh((heute - timedelta(days=60)).isoformat(),
                         heute.isoformat(), symbol)
    if not probe:
        raise ValueError(
            f"Yahoo Finance liefert keine Kurse für „{symbol}“ — nicht übernommen."
        )

    if not name:
        name = hole_name(symbol) or symbol

    with Session(engine) as s:
        s.add(Wert(symbol=symbol, name=name,
                   einheit=einheit, einheit_lang=einheit_lang))
        s.commit()

    return {"symbol": symbol, "name": name,
            "einheit": einheit, "einheit_lang": einheit_lang}


def hole_kurse(start: str, end: str, symbol: str = "^GDAXI") -> list[dict]:
    """
    Liefert die Eröffnungskurse eines Zeitraums (Cache mit Nachladen).

    start, end: Datum im Format JJJJ-MM-TT (end ist ausschließend, wie bei Yahoo)

    Nicht abgedeckte Zeiträume werden von Yahoo geholt, in der DB gespeichert und
    die Cache-Abdeckung des Werts entsprechend erweitert. Ausgeliefert wird immer
    aus der Datenbank.

    Rückgabe: Liste von {"datum": "TT.MM.JJJJ", "eroeffnung": float},
              aufsteigend nach Datum sortiert.
    """
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d   = datetime.strptime(end,   "%Y-%m-%d").date()

    with Session(engine) as s:
        wert = _hole_oder_lege_wert_an(s, symbol)

        # Deckt der Cache den angefragten Zeitraum ab? Wenn nicht, laden wir den
        # Vereinigungsbereich, damit die Abdeckung lückenlos zusammenhängend bleibt.
        gedeckt = (
            wert.cached_von is not None
            and wert.cached_von <= start_d
            and wert.cached_bis >= end_d
        )
        if not gedeckt:
            lade_von = min(start_d, wert.cached_von) if wert.cached_von else start_d
            lade_bis = max(end_d,   wert.cached_bis) if wert.cached_bis else end_d
            _lade_und_speichere(s, wert, lade_von, lade_bis)
            wert.cached_von = lade_von
            wert.cached_bis = lade_bis
            s.commit()

        kurse = s.scalars(
            select(Kurs)
            .where(Kurs.wert_id == wert.id, Kurs.datum >= start_d, Kurs.datum < end_d)
            .order_by(Kurs.datum)
        ).all()

        return [
            {"datum": k.datum.strftime("%d.%m.%Y"), "eroeffnung": k.eroeffnung}
            for k in kurse
        ]
