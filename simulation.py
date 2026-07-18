"""Simulationsengine für den Aktienhandel.

Ein Simulationslauf wird durch eine Konfiguration beschrieben (Wert, Zeitraum,
Kapital, Kauf-Trigger, Verkauf-Trigger — siehe SimulationsEngine.__init__) und
läuft so ab: Die Engine nimmt Tag für Tag die Eröffnungskurse (Modul der
kontinuierlichen Bewertung) und befragt die Bewerter aus trigger.py:

  * keine Position + Kauf-Trigger feuert  -> Kauf mit dem gesamten Cash
  * offene Position + Verkauf-Trigger feuert -> Verkauf der gesamten Position

Für jeden Handelstag wird der Tagesendstand (Cash + Position zum Tageskurs)
berechnet und zusammen mit den Trades in der Datenbank gespeichert.

Vereinfachungen (bewusst, für spätere Ausbaustufen offen):
  * Gehandelt wird ausschließlich in USD (Feld 'waehrung' ist für weitere
    Währungen vorbereitet); Kurse werden nicht umgerechnet.
  * Anteile sind teilbar (Bruchteile erlaubt), keine Gebühren/Spreads.
  * Ausführung zum Eröffnungskurs desselben Tags, an dem der Trigger feuert.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base, engine, hole_kurse_roh
from trigger import benoetigter_vorlauf, erzeuge_kauf_bewerter, erzeuge_verkauf_bewerter

# Kalendertage, die pro benötigtem Handelstag Vorlauf zusätzlich geladen werden
# (Wochenenden/Feiertage): 200 Handelstage ≈ 290 Kalendertage, Faktor 2 ist sicher.
VORLAUF_KALENDER_FAKTOR = 2


# ── Datenmodell ──────────────────────────────────────────────────────────────

class Simulation(Base):
    """Ein Simulationslauf: Konfiguration + Ergebnis-Kennzahlen."""
    __tablename__ = "simulation"

    id:      Mapped[int]   = mapped_column(primary_key=True)
    name:    Mapped[str]   = mapped_column(String)
    symbol:  Mapped[str]   = mapped_column(String, index=True)
    start:   Mapped[date]  = mapped_column(Date)
    ende:    Mapped[date]  = mapped_column(Date)          # ausschließend, wie überall
    kapital: Mapped[float] = mapped_column(Float)

    # Karenzzeit in Handelstagen: nach jedem ausgeführten Trade werden für so
    # viele Tage weder Kauf- noch Verkauf-Trigger geprüft (0 = keine Karenz).
    karenz_tage: Mapped[int] = mapped_column(default=0)

    # Aktuell wird immer in USD gehandelt; das Feld hält die Tür für weitere
    # Währungen offen.
    waehrung: Mapped[str] = mapped_column(String, default="USD")

    kauf_trigger:    Mapped[dict] = mapped_column(JSON)
    verkauf_trigger: Mapped[dict] = mapped_column(JSON)

    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    endstand:        Mapped[float] = mapped_column(Float)
    rendite_prozent: Mapped[float] = mapped_column(Float)
    anzahl_trades:   Mapped[int]

    tage: Mapped[list["SimulationsTag"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan",
        order_by="SimulationsTag.datum",
    )
    trades: Mapped[list["SimulationsTrade"]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan",
        order_by="SimulationsTrade.datum",
    )


class SimulationsTag(Base):
    """Tagesendstand eines Simulationslaufs an einem Handelstag."""
    __tablename__ = "simulations_tag"

    id:            Mapped[int]   = mapped_column(primary_key=True)
    simulation_id: Mapped[int]   = mapped_column(ForeignKey("simulation.id"), index=True)
    datum:         Mapped[date]  = mapped_column(Date)
    kurs:          Mapped[float] = mapped_column(Float)
    cash:          Mapped[float] = mapped_column(Float)
    anteile:       Mapped[float] = mapped_column(Float)
    endstand:      Mapped[float] = mapped_column(Float)   # cash + anteile * kurs

    simulation: Mapped["Simulation"] = relationship(back_populates="tage")


class SimulationsTrade(Base):
    """Ein ausgeführter Kauf oder Verkauf innerhalb eines Simulationslaufs."""
    __tablename__ = "simulations_trade"

    id:            Mapped[int]   = mapped_column(primary_key=True)
    simulation_id: Mapped[int]   = mapped_column(ForeignKey("simulation.id"), index=True)
    datum:         Mapped[date]  = mapped_column(Date)
    typ:           Mapped[str]   = mapped_column(String)   # "kauf" | "verkauf"
    kurs:          Mapped[float] = mapped_column(Float)
    anteile:       Mapped[float] = mapped_column(Float)
    betrag:        Mapped[float] = mapped_column(Float)

    simulation: Mapped["Simulation"] = relationship(back_populates="trades")


def _migriere_karenz_spalte() -> None:
    """Ergänzt 'karenz_tage' in bestehenden Datenbanken (Mini-Migration).

    create_all() legt nur fehlende Tabellen an, ergänzt aber keine Spalten —
    eine vor dieser Erweiterung angelegte kurse.db braucht daher das ALTER.
    Läuft die Datei frisch an (Tabelle existiert noch nicht), passiert nichts.
    """
    with engine.begin() as conn:
        spalten = [zeile[1] for zeile in conn.exec_driver_sql("PRAGMA table_info(simulation)")]
        if spalten and "karenz_tage" not in spalten:
            conn.exec_driver_sql(
                "ALTER TABLE simulation ADD COLUMN karenz_tage INTEGER NOT NULL DEFAULT 0")


_migriere_karenz_spalte()


# ── Engine ───────────────────────────────────────────────────────────────────

class SimulationsEngine:
    """Führt einen Simulationslauf gemäß Konfiguration aus.

    Konfiguration (dict):
      symbol           Yahoo-Finance-Symbol, z. B. "^GDAXI"
      start, ende      Zeitraum im Format JJJJ-MM-TT (ende ausschließend)
      kapital          Startkapital (> 0)
      karenz_tage      optional (Standard 0): Handelstage nach jedem Trade,
                       in denen kein weiterer Kauf/Verkauf geprüft wird
      waehrung         optional, aktuell nur "USD"
      kauf_trigger     z. B. {"typ": "sma_kreuzung", "periode": 200}
                       oder  {"typ": "immer"}
      verkauf_trigger  z. B. {"typ": "sma_kreuzung", "periode": 200},
                       {"typ": "stop_take", "stop_prozent": 10, "take_prozent": 20}
                       oder  {"typ": "nie"}
      name             optional, sonst wird einer erzeugt

    Wirft ValueError bei ungültiger Konfiguration oder fehlenden Kursen.
    """

    def __init__(self, config: dict):
        self.symbol = (config.get("symbol") or "").strip()
        if not self.symbol:
            raise ValueError("Kein Symbol angegeben.")

        try:
            self.start = datetime.strptime(config.get("start", ""), "%Y-%m-%d").date()
            self.ende  = datetime.strptime(config.get("ende",  ""), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Start und Ende müssen im Format JJJJ-MM-TT angegeben sein.")
        if self.start >= self.ende:
            raise ValueError("Das Startdatum muss vor dem Enddatum liegen.")

        try:
            self.kapital = float(config.get("kapital", 0))
        except (TypeError, ValueError):
            raise ValueError("Kapital muss eine Zahl sein.")
        if self.kapital <= 0:
            raise ValueError("Kapital muss größer als 0 sein.")

        try:
            self.karenz_tage = int(config.get("karenz_tage") or 0)
        except (TypeError, ValueError):
            raise ValueError("Karenzzeit muss eine ganze Zahl (Handelstage) sein.")
        if self.karenz_tage < 0:
            raise ValueError("Karenzzeit darf nicht negativ sein.")

        self.waehrung = (config.get("waehrung") or "USD").strip().upper()
        if self.waehrung != "USD":
            raise ValueError("Aktuell wird nur die Währung USD unterstützt.")

        self.kauf_trigger    = config.get("kauf_trigger") or {}
        self.verkauf_trigger = config.get("verkauf_trigger") or {}
        # Trigger sofort validieren (mit leerer Kursliste), damit Fehler in der
        # Konfiguration vor dem Kurse-Laden auffallen.
        erzeuge_kauf_bewerter(self.kauf_trigger, [])
        erzeuge_verkauf_bewerter(self.verkauf_trigger, [])

        self.name = (config.get("name") or "").strip() or (
            f"{self.symbol}: {self.kauf_trigger.get('typ')} → "
            f"{self.verkauf_trigger.get('typ')}"
        )

    def laufe(self) -> Simulation:
        """Führt den Lauf aus und liefert die (noch ungespeicherte) Simulation.

        Der Kern: der Tages-Loop, der kontinuierlich die Kurse nimmt und die
        Kauf-/Verkauf-Bewertung vornimmt.
        """
        # Kurse inkl. Vorlauf laden, damit SMA-Trigger am ersten Simulationstag
        # bereits Vorgeschichte haben (Cache mit Nachladen aus db.py).
        vorlauf = benoetigter_vorlauf(self.kauf_trigger, self.verkauf_trigger)
        lade_von = self.start - timedelta(days=vorlauf * VORLAUF_KALENDER_FAKTOR + 10)
        daten = hole_kurse_roh(lade_von.isoformat(), self.ende.isoformat(), self.symbol)

        kurse = [kurs for _, kurs in daten]
        sim_start = next(
            (i for i, (datum, _) in enumerate(daten) if datum >= self.start), None
        )
        if sim_start is None:
            raise ValueError(
                f"Keine Kurse für {self.symbol} im Zeitraum {self.start} bis {self.ende}."
            )

        kauf    = erzeuge_kauf_bewerter(self.kauf_trigger, kurse)
        verkauf = erzeuge_verkauf_bewerter(self.verkauf_trigger, kurse)

        sim = Simulation(
            name=self.name, symbol=self.symbol, start=self.start, ende=self.ende,
            kapital=self.kapital, karenz_tage=self.karenz_tage, waehrung=self.waehrung,
            kauf_trigger=self.kauf_trigger, verkauf_trigger=self.verkauf_trigger,
        )

        cash, anteile, kaufkurs = self.kapital, 0.0, None
        # Karenz: nach einem Trade am Tag i sind die Trigger bis einschließlich
        # Index (i + karenz_tage) gesperrt — bei 0 bleibt alles wie bisher.
        gesperrt_bis = -1
        for i in range(sim_start, len(daten)):
            datum, kurs = daten[i]

            if i <= gesperrt_bis:
                pass   # Karenzzeit läuft — keine Trigger-Prüfung
            elif anteile == 0 and kauf.pruefe(i, kurse, kaufkurs):
                anteile, kaufkurs = cash / kurs, kurs
                sim.trades.append(SimulationsTrade(
                    datum=datum, typ="kauf", kurs=kurs, anteile=anteile, betrag=cash))
                cash = 0.0
                gesperrt_bis = i + self.karenz_tage
            elif anteile > 0 and verkauf.pruefe(i, kurse, kaufkurs):
                cash = anteile * kurs
                sim.trades.append(SimulationsTrade(
                    datum=datum, typ="verkauf", kurs=kurs, anteile=anteile, betrag=cash))
                anteile, kaufkurs = 0.0, None
                gesperrt_bis = i + self.karenz_tage

            sim.tage.append(SimulationsTag(
                datum=datum, kurs=kurs, cash=cash, anteile=anteile,
                endstand=cash + anteile * kurs,
            ))

        sim.endstand        = sim.tage[-1].endstand
        sim.rendite_prozent = (sim.endstand - self.kapital) / self.kapital * 100
        sim.anzahl_trades   = len(sim.trades)
        return sim


# ── API-Einstiegspunkte ──────────────────────────────────────────────────────

def starte_simulation(config: dict) -> dict:
    """Validiert die Konfiguration, führt den Lauf aus und speichert ihn."""
    sim = SimulationsEngine(config).laufe()
    with Session(engine) as s:
        s.add(sim)
        s.commit()
        return _kennzahlen(sim)


def liste_simulationen() -> list[dict]:
    """Alle gespeicherten Simulationsläufe (neueste zuerst), ohne Tagesdaten."""
    with Session(engine) as s:
        return [
            _kennzahlen(sim)
            for sim in s.scalars(select(Simulation).order_by(Simulation.id.desc()))
        ]


def hole_simulation(sim_id: int) -> dict | None:
    """Ein Lauf im Detail: Kennzahlen, alle Trades und alle Tagesendstände."""
    with Session(engine) as s:
        sim = s.get(Simulation, sim_id)
        if sim is None:
            return None
        detail = _kennzahlen(sim)
        detail["trades"] = [
            {
                "datum":   t.datum.strftime("%d.%m.%Y"),
                "typ":     t.typ,
                "kurs":    round(t.kurs, 2),
                "anteile": round(t.anteile, 4),
                "betrag":  round(t.betrag, 2),
            }
            for t in sim.trades
        ]
        detail["tage"] = [
            {
                "datum":    tag.datum.strftime("%d.%m.%Y"),
                "kurs":     round(tag.kurs, 2),
                "endstand": round(tag.endstand, 2),
            }
            for tag in sim.tage
        ]
        return detail


def _kennzahlen(sim: Simulation) -> dict:
    return {
        "id":              sim.id,
        "name":            sim.name,
        "symbol":          sim.symbol,
        "start":           sim.start.strftime("%d.%m.%Y"),
        "ende":            sim.ende.strftime("%d.%m.%Y"),
        "kapital":         sim.kapital,
        "karenz_tage":     sim.karenz_tage,
        "waehrung":        sim.waehrung,
        "kauf_trigger":    sim.kauf_trigger,
        "verkauf_trigger": sim.verkauf_trigger,
        "erstellt_am":     sim.erstellt_am.strftime("%d.%m.%Y %H:%M") if sim.erstellt_am else None,
        "endstand":        round(sim.endstand, 2),
        "rendite_prozent": round(sim.rendite_prozent, 2),
        "anzahl_trades":   sim.anzahl_trades,
    }
