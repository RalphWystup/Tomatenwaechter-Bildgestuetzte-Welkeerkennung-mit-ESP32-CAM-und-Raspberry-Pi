# -*- coding: utf-8 -*-
"""
waveshare_pi_test.py
Prueft das Waveshare "Modbus RTU Module (A)" am Raspberry Pi, angeschlossen
ueber einen USB-RS485-Konverter. Entspricht Waveshare_IO_Test.py vom PC,
nur mit Linux-Geraetenamen statt COM5.

Verdrahtung:  A <-> A,  B <-> B,  GND <-> GND
Modul:        Adresse 1, 9600 Baud, 8N1

Beim Waveshare "USB TO 4CH RS485" meldet sich EINE Schnittstelle je Kanal
(-if00-port0 = Kanal 1 ... -if03-port0 = Kanal 4). Ohne Angabe probiert das
Programm alle durch und nimmt die, an der das Modul antwortet.

Aufruf:   python3 waveshare_pi_test.py
          python3 waveshare_pi_test.py /dev/ttyUSB0     (Geraet erzwingen)

WICHTIG: Auf einem RS485-Bus darf nur EIN Master sprechen. Das RS485-TO-ETH-
Gateway muss abgeklemmt oder unbenutzt sein, solange der Pi Master ist.
"""
import glob
import sys
import time

try:
    import serial
except ImportError:
    raise SystemExit("pyserial fehlt:  sudo apt install -y python3-serial")

ADRESSE = 1
BAUD    = 9600
ZEITAUS = 1.0

# Registerplan laut Waveshare-Dokumentation
COIL_RELAIS   = 0x0000     # +0 = Relais 1, +1 = Relais 2   (FC05)
DI_START      = 0x0000     # 2 Bit                          (FC02)
AI_START      = 0x0000     # 2 Kanaele                      (FC04)
AO_START      = 0x0000     # 2 Kanaele, Wert in µA          (FC03/06)
REG_VERSION   = 0x8000     # Wert/100                       (FC03)


def crc16(daten):
    crc = 0xFFFF
    for b in daten:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def kandidaten():
    """Alle in Frage kommenden Schnittstellen. Bevorzugt die gleichbleibenden
    Namen unter /dev/serial/by-id/ - die Nummer in ttyUSB0/1 kann sich beim
    Einstecken aendern."""
    fest = sorted(glob.glob("/dev/serial/by-id/*"))
    if fest:
        return fest
    lose = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    if lose:
        return lose
    raise SystemExit("Kein USB-Seriell-Wandler gefunden. Steckt er? "
                     "Pruefen mit:  ls /dev/serial/by-id/   und   dmesg | tail")


def suche_modul():
    """Jede Schnittstelle anfragen, bis eine antwortet. Beim 4-Kanal-Wandler
    sind das bis zu vier - nur an einer haengt das Modul."""
    liste = kandidaten()
    print("Gefundene Schnittstellen: %d" % len(liste))
    for geraet in liste:
        kurz = geraet.split("/")[-1]
        try:
            m = Modul(geraet)
        except Exception as e:
            print("   %-46s nicht zu oeffnen (%s)" % (kurz, e))
            continue
        try:
            v = m.lese_holding(REG_VERSION, 1)[0]
            print("   %-46s ANTWORTET, Firmware V%.2f" % (kurz, v / 100.0))
            return m, geraet
        except Exception:
            print("   %-46s keine Antwort" % kurz)
            m.schliesse()
    raise SystemExit(
        "An keiner Schnittstelle antwortet ein Modul mit Adresse %d bei %d Baud.\n"
        "Pruefen: A und B vertauscht? Masse verbunden? Modul mit Spannung "
        "versorgt? Sendet noch ein zweiter Master (Gateway) auf dem Bus?"
        % (ADRESSE, BAUD))


class Modul:
    def __init__(self, geraet):
        self.port = serial.Serial(geraet, BAUD, timeout=ZEITAUS)
        time.sleep(0.1)

    def frage(self, pdu, antwortlaenge):
        rahmen = bytes([ADRESSE]) + pdu
        rahmen += crc16(rahmen).to_bytes(2, "little")
        self.port.reset_input_buffer()
        self.port.write(rahmen)
        antwort = self.port.read(antwortlaenge)
        if len(antwort) < antwortlaenge:
            raise IOError("keine oder zu kurze Antwort (%d von %d Byte) - "
                          "Adresse, Baudrate, A/B vertauscht?"
                          % (len(antwort), antwortlaenge))
        if crc16(antwort[:-2]) != int.from_bytes(antwort[-2:], "little"):
            raise IOError("CRC falsch - Stoerung auf dem Bus?")
        if antwort[1] & 0x80:
            raise IOError("Modul meldet Ausnahme %d" % antwort[2])
        return antwort

    def lese_holding(self, start, anzahl):
        a = self.frage(bytes([3]) + start.to_bytes(2, "big")
                       + anzahl.to_bytes(2, "big"), 5 + 2 * anzahl)
        return [int.from_bytes(a[3 + 2 * i:5 + 2 * i], "big") for i in range(anzahl)]

    def lese_eingang(self, start, anzahl):
        a = self.frage(bytes([4]) + start.to_bytes(2, "big")
                       + anzahl.to_bytes(2, "big"), 5 + 2 * anzahl)
        return [int.from_bytes(a[3 + 2 * i:5 + 2 * i], "big") for i in range(anzahl)]

    def lese_di(self, anzahl=2):
        a = self.frage(bytes([2]) + DI_START.to_bytes(2, "big")
                       + anzahl.to_bytes(2, "big"), 6)
        return [(a[3] >> i) & 1 for i in range(anzahl)]

    def schalte_relais(self, nummer, ein):
        """nummer 1 oder 2."""
        adresse = COIL_RELAIS + (nummer - 1)
        wert = 0xFF00 if ein else 0x0000
        self.frage(bytes([5]) + adresse.to_bytes(2, "big")
                   + wert.to_bytes(2, "big"), 8)

    def schliesse(self):
        self.port.close()


def main():
    if len(sys.argv) > 1:
        geraet = sys.argv[1]
        m = Modul(geraet)
        v = m.lese_holding(REG_VERSION, 1)[0]
        print("Geraet: %s   Firmware V%.2f" % (geraet, v / 100.0))
    else:
        print("1) Schnittstellen durchprobieren ...")
        m, geraet = suche_modul()
        print("   -> benutze %s" % geraet)
    try:
        print("2) Digitaleingaenge lesen ...")
        print("   DI1=%d  DI2=%d" % tuple(m.lese_di()))

        print("3) Analogeingaenge lesen ...")
        ai = m.lese_eingang(AI_START, 2)
        print("   AI1=%d  AI2=%d  (Einheit je nach Modus: mV oder µA)" % tuple(ai))

        print("4) Analogausgaenge lesen ...")
        ao = m.lese_holding(AO_START, 2)
        print("   AO1=%d µA  AO2=%d µA" % tuple(ao))

        print("5) Relais 1 schaltet zweimal - es muss hoerbar klicken ...")
        for _ in range(2):
            m.schalte_relais(1, True)
            time.sleep(0.6)
            m.schalte_relais(1, False)
            time.sleep(0.6)
        print("   fertig")
        print("\nAlles in Ordnung - das Modul haengt am Pi.")
    finally:
        m.schliesse()


if __name__ == "__main__":
    main()
