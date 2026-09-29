# -*- coding: utf-8 -*-
"""
waveshare_wandler_test.py
Prueft den Waveshare "USB TO 4CH RS485" OHNE angeschlossenes Modul.

Zwei Betriebsarten:

  python3 waveshare_wandler_test.py
        Nur nachsehen: welche Schnittstellen gibt es, lassen sie sich
        oeffnen, stimmen die Rechte. Kein Draht noetig.

  python3 waveshare_wandler_test.py schleife
        Echter Sendetest zwischen zwei Kanaelen. Dafuer vorher
        verdrahten:   Kanal 1 A  <->  Kanal 2 A
                      Kanal 1 B  <->  Kanal 2 B
        Das Programm sendet auf Kanal 1 und liest auf Kanal 2 mit,
        danach umgekehrt. Damit sind Treiber, Rechte, Sende- und
        Empfangszweig beider Kanaele geprueft - alles ausser dem Modul.
"""
import glob
import sys
import time

try:
    import serial
except ImportError:
    raise SystemExit("pyserial fehlt:  sudo apt install -y python3-serial")

BAUD = 9600


def schnittstellen():
    liste = sorted(glob.glob("/dev/serial/by-id/*"))
    if not liste:
        liste = sorted(glob.glob("/dev/ttyUSB*"))
    return liste


def uebersicht():
    liste = schnittstellen()
    if not liste:
        raise SystemExit("Keine Schnittstelle gefunden. Steckt der Wandler? "
                         "Pruefen mit:  lsusb   und   dmesg | tail -20")
    print("Gefundene Schnittstellen: %d" % len(liste))
    for geraet in liste:
        try:
            p = serial.Serial(geraet, BAUD, timeout=0.2)
            p.close()
            zustand = "laesst sich oeffnen"
        except Exception as e:
            zustand = "FEHLER: %s" % e
        print("   %-52s %s" % (geraet.split("/")[-1], zustand))
    if len(liste) == 4:
        print("\nVier Kanaele - das ist beim USB TO 4CH RS485 richtig so.")
    return liste


def schleife():
    liste = uebersicht()
    if len(liste) < 2:
        raise SystemExit("Fuer den Sendetest werden zwei Kanaele gebraucht.")
    a, b = serial.Serial(liste[0], BAUD, timeout=1.0), \
           serial.Serial(liste[1], BAUD, timeout=1.0)
    try:
        for hin, (sender, empfaenger, name) in enumerate(
                [(a, b, "Kanal 1 -> Kanal 2"), (b, a, "Kanal 2 -> Kanal 1")]):
            probe = b"RS485-Probe-%d" % hin
            empfaenger.reset_input_buffer()
            sender.write(probe)
            sender.flush()
            time.sleep(0.2)
            zurueck = empfaenger.read(len(probe))
            if zurueck == probe:
                print("%s:  in Ordnung (%d Byte unveraendert)" % (name, len(probe)))
            elif zurueck:
                print("%s:  VERFAELSCHT - gesendet %r, empfangen %r"
                      % (name, probe, zurueck))
                print("   Verdacht: Baudrate oder Stoerung auf der Leitung")
            else:
                print("%s:  NICHTS empfangen" % name)
                print("   Verdacht: A und B vertauscht, Draht lose, oder "
                      "falsche Klemmen erwischt")
    finally:
        a.close()
        b.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].startswith("schleife"):
        schleife()
    else:
        uebersicht()
        print("\nFuer den echten Sendetest zwei Draehte zwischen Kanal 1 und 2 "
              "legen (A-A, B-B) und aufrufen mit:  python3 %s schleife"
              % sys.argv[0].split("/")[-1])
