import random
import string

# ANSI-Escape-Codes färben Text im Terminal ein.
# Das Format ist \033[<code>m — 91-96 sind helle Farben.
FARBEN = [
    "\033[91m",  # Rot
    "\033[92m",  # Grün
    "\033[93m",  # Gelb
    "\033[94m",  # Blau
    "\033[95m",  # Magenta
    "\033[96m",  # Cyan
]
# RESET setzt die Farbe nach jeder Zeile zurück auf den Standard.
RESET = "\033[0m"


def zufallstext(laenge: int = 35) -> str:
    """Erzeugt einen zufälligen Text aus Buchstaben, Ziffern und Sonderzeichen."""
    zeichen = string.ascii_letters + string.digits + " !?#@"
    # random.choices zieht 'laenge' Zeichen mit Zurücklegen aus dem Zeichenpool.
    return "".join(random.choices(zeichen, k=laenge))


if __name__ == "__main__":
    anzahl = int(input("Wie oft ausgeben? "))
    for i in range(anzahl):
        # Modulo sorgt dafür, dass die Farben sich wiederholen,
        # wenn 'anzahl' größer als die Anzahl der Farben ist.
        farbe = FARBEN[i % len(FARBEN)]
        print(f"{farbe}{zufallstext()}{RESET}")
