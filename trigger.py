"""Trigger-Bewertung für die Handelssimulation.

Zwei Familien von Bewertern:

  Kauf-Bewerter    — entscheiden pro Handelstag, ob (ohne bestehende Position)
                     gekauft wird.
  Verkauf-Bewerter — entscheiden pro Handelstag, ob eine bestehende Position
                     verkauft wird.

Alle Bewerter haben dieselbe Schnittstelle:

    pruefe(i, kurse, kaufkurs) -> bool

  i        — Index des aktuellen Handelstags in der Kursliste
  kurse    — die vollständige Kursliste (inkl. Vorlauf für Indikatoren)
  kaufkurs — Einstandskurs der offenen Position (None, wenn keine besteht)

Konfiguriert wird ein Bewerter über ein dict {"typ": ..., <parameter>};
erzeuge_kauf_bewerter() / erzeuge_verkauf_bewerter() bauen daraus die Instanz.
Neue Trigger-Typen werden dort als weiterer Zweig ergänzt — die Engine in
simulation.py muss dafür nicht angefasst werden.
"""


def berechne_sma(kurse: list[float], n: int) -> list[float | None]:
    """Einfacher gleitender Mittelwert über n Werte (laufende Summe).

    Die ersten (n-1) Einträge sind None, solange das Fenster noch nicht voll ist.
    """
    out: list[float | None] = []
    summe = 0.0
    for i, kurs in enumerate(kurse):
        summe += kurs
        if i >= n:
            summe -= kurse[i - n]
        out.append(summe / n if i >= n - 1 else None)
    return out


class SmaKreuzung:
    """Feuert, wenn der Kurs den SMA(periode) kreuzt.

    richtung +1: von unten nach oben (typischer Kauf-Trigger),
    richtung -1: von oben nach unten (typischer Verkauf-Trigger).
    """

    def __init__(self, kurse: list[float], periode: int, richtung: int):
        self.sma = berechne_sma(kurse, periode)
        self.richtung = richtung

    def pruefe(self, i: int, kurse: list[float], kaufkurs: float | None = None) -> bool:
        if i == 0 or self.sma[i] is None or self.sma[i - 1] is None:
            return False
        if self.richtung > 0:
            return kurse[i - 1] <= self.sma[i - 1] and kurse[i] > self.sma[i]
        return kurse[i - 1] >= self.sma[i - 1] and kurse[i] < self.sma[i]


class Immer:
    """Kauft am ersten möglichen Tag — zusammen mit „nie" ergibt das Buy & Hold."""

    def pruefe(self, i: int, kurse: list[float], kaufkurs: float | None = None) -> bool:
        return True


class Nie:
    """Verkauft nie — die Position wird bis zum Ende gehalten."""

    def pruefe(self, i: int, kurse: list[float], kaufkurs: float | None = None) -> bool:
        return False


class StopTake:
    """Verkauft bei Verlust >= stop_prozent oder Gewinn >= take_prozent seit Kauf."""

    def __init__(self, stop_prozent: float | None, take_prozent: float | None):
        self.stop = stop_prozent
        self.take = take_prozent

    def pruefe(self, i: int, kurse: list[float], kaufkurs: float | None = None) -> bool:
        if not kaufkurs:
            return False
        rendite = (kurse[i] - kaufkurs) / kaufkurs * 100
        return (self.stop is not None and rendite <= -self.stop) or \
               (self.take is not None and rendite >= self.take)


def _periode(config: dict) -> int:
    try:
        periode = int(config.get("periode", 200))
    except (TypeError, ValueError):
        raise ValueError("SMA-Periode muss eine ganze Zahl sein.")
    if periode < 2:
        raise ValueError("SMA-Periode muss mindestens 2 sein.")
    return periode


def _prozent(config: dict, feld: str) -> float | None:
    wert = config.get(feld)
    if wert in (None, ""):
        return None
    try:
        wert = float(wert)
    except (TypeError, ValueError):
        raise ValueError(f"„{feld}“ muss eine Zahl sein.")
    if wert <= 0:
        raise ValueError(f"„{feld}“ muss größer als 0 sein.")
    return wert


def erzeuge_kauf_bewerter(config: dict, kurse: list[float]):
    """Baut den Kauf-Bewerter aus der Trigger-Konfiguration (ValueError bei Fehlern)."""
    typ = (config or {}).get("typ", "")
    if typ == "sma_kreuzung":
        return SmaKreuzung(kurse, _periode(config), +1)
    if typ == "immer":
        return Immer()
    raise ValueError(f"Unbekannter Kauf-Trigger „{typ}“.")


def erzeuge_verkauf_bewerter(config: dict, kurse: list[float]):
    """Baut den Verkauf-Bewerter aus der Trigger-Konfiguration (ValueError bei Fehlern)."""
    typ = (config or {}).get("typ", "")
    if typ == "sma_kreuzung":
        return SmaKreuzung(kurse, _periode(config), -1)
    if typ == "stop_take":
        stop = _prozent(config, "stop_prozent")
        take = _prozent(config, "take_prozent")
        if stop is None and take is None:
            raise ValueError("Stop-Loss/Take-Profit braucht mindestens einen Prozentwert.")
        return StopTake(stop, take)
    if typ == "nie":
        return Nie()
    raise ValueError(f"Unbekannter Verkauf-Trigger „{typ}“.")


def benoetigter_vorlauf(*configs: dict) -> int:
    """Wie viele Handelstage Vorlauf die Trigger vor dem Simulationsstart brauchen.

    SMA-Trigger brauchen 'periode' Tage Vorgeschichte, damit der Durchschnitt
    schon am ersten Simulationstag definiert ist; alle anderen Typen keinen.
    """
    return max(
        (_periode(c) for c in configs if (c or {}).get("typ") == "sma_kreuzung"),
        default=0,
    )
