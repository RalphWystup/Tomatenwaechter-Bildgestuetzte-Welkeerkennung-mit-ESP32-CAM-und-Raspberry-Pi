# -*- coding: utf-8 -*-
"""
waveshare_io.py
Anbindung des Waveshare "Modbus RTU Module (A)" an den Tomatenwaechter.
Modbus RTU ueber einen USB-RS485-Wandler am Raspberry Pi.

Das Modul haelt einen eigenen Abfragefaden, der laufend

    2 Digitaleingaenge, 2 Analogeingaenge, 2 Analogausgaenge, 2 Relais

liest und in einem Zustandswoerterbuch bereitstellt. Das Dashboard holt sich
daraus seine Anzeige; Schaltbefehle laufen ueber dieselbe Sperre, damit sich
Abfrage und Befehl auf der seriellen Leitung nicht ins Gehege kommen.

Faellt der Wandler aus oder wird er abgezogen, meldet das Modul das im
Zustand und versucht es alle paar Sekunden erneut. Der Waechter laeuft
davon unberuehrt weiter - die Ein- und Ausgaenge sind Zugabe.

Registerplan laut Waveshare-Dokumentation:
  Relais       Coils 0x0000/0x0001   FC01 lesen, FC05 schreiben
                                     (0xFF00 = ein, 0x0000 = aus)
  Dig.eingang  0x0000, 2 Bit         FC02
  Ana.eingang  0x0000, 2 Kanaele     FC04
  Ana.ausgang  0x0000, 2 Kanaele     FC03/FC06, Wert in µA (0..20000)
  Messbereich  0x3000/0x3001         FC03
  Version      0x8000                FC03 (Wert/100)

Einzeln pruefen:  python3 waveshare_io.py
"""
import glob
import threading
import time

try:
    import serial
    SERIELL_DA = True
except ImportError:
    SERIELL_DA = False

# ------------- Einstellungen -------------
ADRESSE      = 1        # Modbus-Adresse des Moduls
BAUD         = 9600
ZEITAUS      = 0.5      # s Wartezeit auf Antwort
ABFRAGETAKT  = 1.0      # s zwischen zwei Abfragen (Anzeige in Echtzeit)
WARTEN_NACH_FEHLER = 5.0
AO_MAX       = 20000    # µA
GIESSEN_MAX  = 600      # s - harte Obergrenze, damit nichts ueberlaeuft

# Messbereich der Analogeingaenge. Wird beim Verbinden ins Modul geschrieben,
# falls es anders eingestellt ist. None = so lassen, wie es im Modul steht.
#   0 = 0-10 V (Anzeige in Volt)      2 = 0-20 mA
#   1 = 2-10 V                        3 = 4-20 mA      4 = ADC roh
# ACHTUNG: Fuer Spannungsmessung muessen zusaetzlich die Schiebeschalter der
# beiden AI-Kanaele auf dem Modul auf OFF stehen (Shunt getrennt).
AI_MODUS     = 0
# -----------------------------------------

COIL_RELAIS = 0x0000
DI_START    = 0x0000
AI_START    = 0x0000
AO_START    = 0x0000
REG_MODUS   = 0x3000
REG_VERSION = 0x8000

# Messbereiche der Analogeingaenge (Holding 0x3000/0x3001)
BEREICHE = {
    0: ("0-5/10 V", "mV"),
    1: ("1-5/2-10 V", "mV"),
    2: ("0-20 mA", "µA"),
    3: ("4-20 mA", "µA"),
    4: ("ADC roh", ""),
}

_sperre = threading.Lock()
_port = None
_geraet = None
_giesst = threading.Event()

zustand = {
    "vorhanden": False,          # Modul ueberhaupt angeschlossen?
    "verbunden": False,
    "meldung": "nicht gestartet",
    "geraet": "",
    "version": "",
    "di": [0, 0],
    "ai": [0, 0],
    "ai_text": ["-", "-"],
    "ai_bereich": ["", ""],
    "ao": [0, 0],
    "relais": [0, 0],
    "giesst": False,
    "giess_ende": 0.0,
    "letzte_abfrage": 0.0,
}


def crc16(daten):
    crc = 0xFFFF
    for b in daten:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


# ---------------- Modbus RTU ----------------

def _frage(pdu, antwortlaenge):
    """Ein Telegramm senden und die Antwort pruefen. Aufrufer haelt die Sperre."""
    rahmen = bytes([ADRESSE]) + pdu
    rahmen += crc16(rahmen).to_bytes(2, "little")
    _port.reset_input_buffer()
    _port.write(rahmen)
    antwort = _port.read(antwortlaenge)
    if len(antwort) < antwortlaenge:
        raise IOError("keine Antwort (%d von %d Byte)" % (len(antwort), antwortlaenge))
    if crc16(antwort[:-2]) != int.from_bytes(antwort[-2:], "little"):
        raise IOError("CRC falsch")
    if antwort[1] & 0x80:
        raise IOError("Modul meldet Ausnahme %d" % antwort[2])
    return antwort


def _lese_worte(fc, start, anzahl):
    a = _frage(bytes([fc]) + start.to_bytes(2, "big") + anzahl.to_bytes(2, "big"),
               5 + 2 * anzahl)
    return [int.from_bytes(a[3 + 2 * i:5 + 2 * i], "big") for i in range(anzahl)]


def _lese_bits(fc, start, anzahl):
    a = _frage(bytes([fc]) + start.to_bytes(2, "big") + anzahl.to_bytes(2, "big"), 6)
    return [(a[3] >> i) & 1 for i in range(anzahl)]


def _schreibe_coil(adresse, ein):
    _frage(bytes([5]) + adresse.to_bytes(2, "big")
           + (0xFF00 if ein else 0x0000).to_bytes(2, "big"), 8)


def _schreibe_register(adresse, wert):
    _frage(bytes([6]) + adresse.to_bytes(2, "big") + wert.to_bytes(2, "big"), 8)


# ---------------- Verbindung ----------------

def _schnittstellen():
    liste = sorted(glob.glob("/dev/serial/by-id/*"))
    if liste:
        return liste
    return sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))


def _verbinde():
    """Alle Schnittstellen durchprobieren, bis das Modul antwortet.
    Beim Vierfachwandler sind das bis zu vier."""
    global _port, _geraet
    for geraet in _schnittstellen():
        try:
            _port = serial.Serial(geraet, BAUD, timeout=ZEITAUS)
        except Exception:
            continue
        try:
            version = _lese_worte(3, REG_VERSION, 1)[0]
            modi = _lese_worte(3, REG_MODUS, 2)
            if AI_MODUS is not None and modi != [AI_MODUS, AI_MODUS]:
                # Messbereich stellen und zur Sicherheit zurueckgelesen
                for kanal in (0, 1):
                    _schreibe_register(REG_MODUS + kanal, AI_MODUS)
                    time.sleep(0.05)
                modi = _lese_worte(3, REG_MODUS, 2)
                print("Modul A: Messbereich der Analogeingaenge auf %s gestellt"
                      % BEREICHE.get(AI_MODUS, ("?",))[0])
            _geraet = geraet
            zustand["geraet"] = geraet.split("/")[-1]
            zustand["version"] = "V%.2f" % (version / 100.0)
            zustand["ai_bereich"] = [BEREICHE.get(m, ("?", ""))[0] for m in modi]
            zustand["_einheiten"] = [BEREICHE.get(m, ("?", ""))[1] for m in modi]
            return True
        except Exception:
            try:
                _port.close()
            except Exception:
                pass
            _port = None
    return False


def _trenne(grund):
    global _port
    try:
        if _port:
            _port.close()
    except Exception:
        pass
    _port = None
    zustand["verbunden"] = False
    zustand["meldung"] = grund


def _messwert_text(wert, einheit):
    """Rohwert lesbar machen: mV -> V, µA -> mA."""
    if einheit == "mV":
        return "%.3f V" % (wert / 1000.0)
    if einheit == "µA":
        return "%.2f mA" % (wert / 1000.0)
    return str(wert)


# ---------------- Abfragefaden ----------------

def _schleife():
    while True:
        if _port is None:
            with _sperre:
                erfolg = _verbinde()
            if erfolg:
                zustand["vorhanden"] = True
                zustand["verbunden"] = True
                zustand["meldung"] = "OK"
            else:
                zustand["verbunden"] = False
                zustand["meldung"] = ("kein Modul auf dem Bus (Adresse %d, %d Baud)"
                                      % (ADRESSE, BAUD))
                time.sleep(WARTEN_NACH_FEHLER)
                continue
        try:
            with _sperre:
                di = _lese_bits(2, DI_START, 2)
                ai = _lese_worte(4, AI_START, 2)
                ao = _lese_worte(3, AO_START, 2)
                relais = _lese_bits(1, COIL_RELAIS, 2)
            einheiten = zustand.get("_einheiten", ["", ""])
            zustand.update(di=di, ai=ai, ao=ao, relais=relais,
                           ai_text=[_messwert_text(ai[i], einheiten[i])
                                    for i in range(2)],
                           verbunden=True, meldung="OK",
                           letzte_abfrage=time.time(),
                           giesst=_giesst.is_set())
        except Exception as e:
            _trenne(str(e) or e.__class__.__name__)
            time.sleep(WARTEN_NACH_FEHLER)
        time.sleep(ABFRAGETAKT)


# ---------------- Befehle fuer das Dashboard ----------------

def schalte_relais(nummer, ein):
    """nummer 1 oder 2."""
    if _port is None:
        raise IOError("Modul nicht verbunden")
    with _sperre:
        _schreibe_coil(COIL_RELAIS + (nummer - 1), ein)
    zustand["relais"][nummer - 1] = 1 if ein else 0


def setze_ao(kanal, mikroampere):
    """kanal 1 oder 2, Wert 0..20000 µA (das Modul kann nur Strom)."""
    if _port is None:
        raise IOError("Modul nicht verbunden")
    wert = max(0, min(AO_MAX, int(mikroampere)))
    with _sperre:
        _schreibe_register(AO_START + (kanal - 1), wert)
    zustand["ao"][kanal - 1] = wert
    return wert


def giesse(sekunden, relais=2):
    """Relais 2 fuer die angegebene Zeit einschalten (Pumpe/Ventil).
    Laeuft im Hintergrund, damit das Dashboard nicht stehenbleibt.
    Ein zweiter Aufruf waehrend des Giessens wird abgewiesen."""
    sekunden = max(1, min(GIESSEN_MAX, int(sekunden)))
    if _giesst.is_set():
        raise IOError("es wird bereits gegossen")
    if _port is None:
        raise IOError("Modul nicht verbunden")

    def lauf():
        _giesst.set()
        zustand["giesst"] = True
        zustand["giess_ende"] = time.time() + sekunden
        try:
            schalte_relais(relais, True)
            time.sleep(sekunden)
        finally:
            # Ausschalten notfalls mehrfach versuchen - offen bleiben waere
            # der einzige wirklich schaedliche Fehler in diesem Programm.
            for _ in range(5):
                try:
                    schalte_relais(relais, False)
                    break
                except Exception:
                    time.sleep(1.0)
            _giesst.clear()
            zustand["giesst"] = False
            zustand["giess_ende"] = 0.0

    threading.Thread(target=lauf, daemon=True).start()
    return sekunden


def kopie():
    """Zustand fuer die Anzeige (ohne die internen Felder)."""
    p = {k: v for k, v in zustand.items() if not k.startswith("_")}
    p["di"] = list(zustand["di"])
    p["ai"] = list(zustand["ai"])
    p["ao"] = list(zustand["ao"])
    p["relais"] = list(zustand["relais"])
    p["ai_text"] = list(zustand["ai_text"])
    p["ai_bereich"] = list(zustand["ai_bereich"])
    return p


def starte():
    """Abfragefaden starten. Rueckgabe: True, wenn pyserial vorhanden ist."""
    if not SERIELL_DA:
        zustand["meldung"] = "pyserial fehlt (sudo apt install python3-serial)"
        print("Modul A: " + zustand["meldung"])
        return False
    threading.Thread(target=_schleife, daemon=True).start()
    return True


# ---------------- Einzeltest ----------------

if __name__ == "__main__":
    if not starte():
        raise SystemExit(1)
    print("Abfrage laeuft, Ende mit Strg+C")
    try:
        while True:
            time.sleep(1.0)
            z = kopie()
            if z["verbunden"]:
                print("%s %s | DI %d %d | AI %s / %s | AO %d %d µA | Relais %d %d"
                      % (z["geraet"], z["version"], z["di"][0], z["di"][1],
                         z["ai_text"][0], z["ai_text"][1],
                         z["ao"][0], z["ao"][1], z["relais"][0], z["relais"][1]))
            else:
                print("nicht verbunden: %s" % z["meldung"])
    except KeyboardInterrupt:
        print("\nBeendet.")
