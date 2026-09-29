# -*- coding: utf-8 -*-
"""
oled_anzeige.py
Vor-Ort-Anzeige fuer den Tomaten-Bewaesserungswaechter auf einem
128x64-OLED (I2C).  Gedacht fuer den Raspberry Pi 3B+, laeuft aber
auf jedem Linux mit /dev/i2c-*.

Warum ein eigener Treiber statt luma.oled / Adafruit-Blinka?
  Das Display braucht nur SCHREIBZUGRIFFE ueber I2C.  Die macht der
  Kernel-Treiber i2c-dev direkt - ein os.write() auf /dev/i2c-1 genuegt.
  Damit haengt die Anzeige an KEINER Zusatzbibliothek (kein pip,
  kein "externally-managed-environment"-Aerger unter Bookworm).
  Gezeichnet wird mit Pillow, das fuer die Bildauswertung ohnehin da ist.

Unterstuetzt beide ueblichen Controller:
  SSD1306  - fast alle 0,96"-Module (Standard)
  SH1106   - viele 1,3"-Module (128 von 132 Spalten, Versatz 2)
Wenn das Bild verschoben oder gestreift erscheint: TREIBER umstellen.

Anschluss am Raspberry Pi (I2C-1):
  Display        Pi-Stiftleiste
  VCC   ->  Pin 1  (3,3 V)      Achtung: die meisten Module vertragen
                                 3,3 V; nur bei ausdruecklich 5-V-faehigen
                                 Modulen Pin 2 (5 V) benutzen.
  GND   ->  Pin 6
  SDA   ->  Pin 3  (GPIO 2)
  SCL   ->  Pin 5  (GPIO 3)

I2C muss eingeschaltet sein:
  sudo raspi-config nonint do_i2c 0      (oder Menue: Interface Options)
  Pruefen:  i2cdetect -y 1     -> zeigt 3c (oder 3d)

Einzeln testen:
  python3 oled_anzeige.py            Testbild
  python3 oled_anzeige.py demo       Seitenwechsel mit Beispieldaten
"""
import fcntl
import os
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_DA = True
except ImportError:
    PIL_DA = False

try:
    import numpy as np
except ImportError:
    np = None

# ------------- Einstellungen -------------
BUS_NUMMER   = 1          # /dev/i2c-1 (Pi-Stiftleiste)
ADRESSE      = None       # None = selbst suchen (0x3C, dann 0x3D)
TREIBER      = "ssd1306"  # "ssd1306" (0,96") oder "sh1106" (oft 1,3")
BREITE       = 128
HOEHE        = 64
KOPFSTEHEND  = False      # True dreht die Anzeige um 180 Grad
KONTRAST     = 0x8F       # 0x00 ... 0xFF
SEITENZEIT   = 6.0        # s je Anzeigeseite
TAKT         = 1.0        # s zwischen zwei Bildaufbauten
# -----------------------------------------

I2C_SLAVE = 0x0703        # ioctl-Nummer aus linux/i2c-dev.h

_BEFEHL = 0x00            # Steuerbyte: es folgen Befehle
_DATEN  = 0x40            # Steuerbyte: es folgen Bilddaten


class I2CSchreiber:
    """Minimaler I2C-Schreibzugriff ueber /dev/i2c-N."""

    def __init__(self, bus, adresse):
        self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE, adresse)

    def schreibe(self, steuerbyte, nutzdaten):
        # In Haeppchen schreiben: manche I2C-Adapter mucken bei sehr
        # langen Uebertragungen, 256 Byte gehen ueberall.
        for i in range(0, len(nutzdaten), 256):
            os.write(self.fd, bytes([steuerbyte]) + bytes(nutzdaten[i:i + 256]))

    def schliesse(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def _init_folge(treiber, kopfstehend, kontrast):
    """Einschaltfolge des jeweiligen Controllers."""
    seg = 0xA0 if kopfstehend else 0xA1        # Spaltenrichtung
    com = 0xC0 if kopfstehend else 0xC8        # Zeilenrichtung
    if treiber == "sh1106":
        return [0xAE,                          # aus
                0xD5, 0x80,                    # Taktteiler
                0xA8, 0x3F,                    # Multiplex 64
                0xD3, 0x00, 0x40,              # Versatz / Startzeile
                0xAD, 0x8B, 0x32,              # Ladungspumpe ein, 8 V
                seg, com,
                0xDA, 0x12,                    # COM-Verdrahtung
                0x81, kontrast,
                0xD9, 0x1F, 0xDB, 0x40,        # Vorlade-/VCOM-Pegel
                0xA4, 0xA6,                    # RAM anzeigen, normal
                0xAF]                          # ein
    return [0xAE,
            0xD5, 0x80,
            0xA8, 0x3F,
            0xD3, 0x00, 0x40,
            0x8D, 0x14,                        # Ladungspumpe ein
            0x20, 0x00,                        # waagerechte Adressierung
            seg, com,
            0xDA, 0x12,
            0x81, kontrast,
            0xD9, 0xF1, 0xDB, 0x40,
            0xA4, 0xA6,
            0xAF]


class OLED:
    """128x64-OLED, angesprochen mit einem Pillow-Bild."""

    def __init__(self, bus=BUS_NUMMER, adresse=ADRESSE, treiber=TREIBER,
                 kopfstehend=KOPFSTEHEND, kontrast=KONTRAST):
        if not PIL_DA:
            raise RuntimeError("Pillow fehlt (sudo apt install python3-pil)")
        self.treiber = treiber
        self.adresse = adresse
        if adresse is None:
            self.bus, self.adresse = self._suche(bus)
        else:
            self.bus = I2CSchreiber(bus, adresse)
        self.bus.schreibe(_BEFEHL, _init_folge(treiber, kopfstehend, kontrast))
        self.loesche()

    @staticmethod
    def _suche(bus):
        letzter = None
        for adr in (0x3C, 0x3D):
            try:
                s = I2CSchreiber(bus, adr)
                s.schreibe(_BEFEHL, [0xAE])       # Display aus = harmloser Test
                return s, adr
            except OSError as e:
                letzter = e
        raise IOError("kein OLED auf /dev/i2c-%d gefunden (0x3C/0x3D): %s "
                      "- I2C eingeschaltet? Verdrahtung? (i2cdetect -y %d)"
                      % (bus, letzter, bus))

    # ---- Bild -> Seitenpuffer (8 Seiten a 128 Byte, Bit 0 = oberste Zeile) ----
    @staticmethod
    def _packe(bild):
        bild = bild.convert("1")
        if np is not None:
            a = (np.asarray(bild, dtype=np.uint8) > 0).astype(np.uint8)
            a = a.reshape(HOEHE // 8, 8, BREITE)
            gewichte = (1 << np.arange(8)).astype(np.uint16).reshape(1, 8, 1)
            return bytes((a * gewichte).sum(axis=1).astype(np.uint8).ravel())
        px = bild.load()                              # Notweg ohne numpy
        puffer = bytearray(BREITE * HOEHE // 8)
        for seite in range(HOEHE // 8):
            for x in range(BREITE):
                b = 0
                for bit in range(8):
                    if px[x, seite * 8 + bit]:
                        b |= 1 << bit
                puffer[seite * BREITE + x] = b
        return bytes(puffer)

    def zeige(self, bild):
        puffer = self._packe(bild)
        if self.treiber == "sh1106":
            for seite in range(8):
                self.bus.schreibe(_BEFEHL, [0xB0 + seite, 0x02, 0x10])
                self.bus.schreibe(_DATEN, puffer[seite * BREITE:(seite + 1) * BREITE])
        else:
            self.bus.schreibe(_BEFEHL, [0x21, 0, BREITE - 1, 0x22, 0, 7])
            self.bus.schreibe(_DATEN, puffer)

    def loesche(self):
        self.zeige(Image.new("1", (BREITE, HOEHE), 0))

    def aus(self):
        try:
            self.loesche()
            self.bus.schreibe(_BEFEHL, [0xAE])
        except OSError:
            pass

    def schliesse(self):
        self.aus()
        self.bus.schliesse()


# ---------------- Schriften ----------------

def _schrift(groesse, fett=False):
    namen = (["DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if fett else
             ["DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for name in namen:
        try:
            return ImageFont.truetype(name, groesse)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


class Schriften:
    """Auf 64 Bildpunkten Hoehe ist jede Zeile gezaehlt:
    Groesse 8 = 10 Punkte Zeilenhoehe, Groesse 10 = 13, fett 16 = 19."""

    def __init__(self):
        self.winzig = _schrift(7)
        self.klein = _schrift(8)
        self.normal = _schrift(10)
        self.mittel = _schrift(12, fett=True)
        self.gross = _schrift(16, fett=True)


def _breite(zeichner, text, schrift):
    try:
        return zeichner.textlength(text, font=schrift)
    except AttributeError:                       # sehr alte Pillow-Fassung
        return zeichner.textsize(text, font=schrift)[0]


def _passend(zeichner, text, kandidaten):
    """Groesste Schrift waehlen, mit der der Text noch aufs Display passt."""
    for schrift in kandidaten:
        if _breite(zeichner, text, schrift) <= BREITE - 4:
            return schrift
    return kandidaten[-1]


def _mitte(zeichner, text, schrift, oben, unten, invers=False):
    """Text waagerecht und senkrecht in ein Band setzen. Bei invers wird
    das Band gefuellt und die Schrift ausgespart - das faellt auf einem
    einfarbigen Display sofort ins Auge (fuer GIESSEN!)."""
    if invers:
        zeichner.rectangle([0, oben, BREITE - 1, unten], fill=1)
    kasten = zeichner.textbbox((0, 0), text, font=schrift)
    x = (BREITE - (kasten[2] - kasten[0])) / 2 - kasten[0]
    y = oben + (unten - oben - (kasten[3] - kasten[1])) / 2 - kasten[1]
    zeichner.text((x, y), text, font=schrift, fill=0 if invers else 1)


# ---------------- Seiten zeichnen ----------------

def _kopfzeile(z, s, titel, gestoert):
    """Kopfzeile 0..9, Trennstrich auf 10. Ein Rufzeichen in der Mitte
    heisst: keine Verbindung zur Kamera."""
    z.text((0, 0), titel, font=s.klein, fill=1)
    uhr = time.strftime("%H:%M")
    z.text((BREITE - _breite(z, uhr, s.klein), 0), uhr, font=s.klein, fill=1)
    if gestoert:
        z.text((BREITE / 2 - 4, 0), "(!)", font=s.winzig, fill=1)
    z.line([(0, 10), (BREITE - 1, 10)], fill=1)


def _lage(pflanze):
    """Ampel -> (Klartext fuers grosse Feld, invers darstellen?)"""
    ampel = pflanze.get("ampel", "grau")
    if ampel == "rot":
        return "GIESSEN!", True
    if ampel == "gelb":
        return "bald giessen", False
    if ampel == "gruen":
        return "Wasser ok", False
    text = pflanze.get("status", "")
    if "dunkel" in text:
        return "Nacht", False
    if "Referenz" in text:
        return "keine Referenz", False
    if "nicht erkannt" in text:
        return "keine Pflanze", False
    return "wartet ...", False


def seite_pflanze(zustand, s):
    """Seite 1: die Antwort auf die einzige Frage, die zaehlt - giessen?"""
    bild = Image.new("1", (BREITE, HOEHE), 0)
    z = ImageDraw.Draw(bild)
    p = zustand.get("pflanze", {})
    gestoert = not zustand.get("verbunden", False)
    _kopfzeile(z, s, "Tomate", gestoert)

    text, invers = _lage(p)
    _mitte(z, text, _passend(z, text, [s.gross, s.mittel, s.normal, s.klein]),
           12, 32, invers)

    def wert(x, form="%.1f"):
        return "--" if x is None else (form % x)

    z.text((0, 34), "Gruen %s %%" % wert(p.get("flaeche")),
           font=s.normal, fill=1)                       # 34..46
    z.text((0, 46), "Abfall %s%%  Sinkt %s%%"
           % (wert(p.get("flaechen_abfall")), wert(p.get("absinken"))),
           font=s.klein, fill=1)                        # 46..55
    if gestoert:
        fuss = "keine Verbindung zur Kamera"
    elif p.get("referenz_zeit"):
        fuss = "Ref " + str(p["referenz_zeit"])
    else:
        fuss = "Referenz nach Giessen setzen"
    while _breite(z, fuss, s.klein) > BREITE and len(fuss) > 4:
        fuss = fuss[:-1]
    z.text((0, 55), fuss, font=s.klein, fill=1)         # 55..64
    return bild


def seite_technik(zustand, s):
    """Seite 2: laeuft die Uebertragung sauber?"""
    bild = Image.new("1", (BREITE, HOEHE), 0)
    z = ImageDraw.Draw(bild)
    _kopfzeile(z, s, "Technik", not zustand.get("verbunden", False))
    k = zustand.get("kamera") or {}
    zeilen = [
        "Bild %d   %.0f kB" % (zustand.get("bildnummer", 0),
                               zustand.get("groesse", 0) / 1024.0),
        "Kamera an %s" % (("%d h %02d" % (k["betrieb_s"] // 3600,
                                          k["betrieb_s"] % 3600 // 60))
                          if k else "--"),
        "%s   Heap %s" % (("%d dBm" % k["rssi"]) if k else "WLAN --",
                          ("%d k" % k["heap_kb"]) if k else "--"),
        "Wdh %d   Fehler %d" % (zustand.get("wiederholungen_gesamt", 0),
                                zustand.get("fehlbilder", 0)),
        zustand.get("web", ""),
    ]
    y = 13                                              # 13,23,33,43,53 .. 63
    for zeile in zeilen:
        schrift = s.klein if _breite(z, zeile, s.klein) <= BREITE else s.winzig
        z.text((0, y), zeile, font=schrift, fill=1)
        y += 10
    return bild


def seite_verlauf(zustand, s):
    """Seite 3: Welke-Kennwerte der letzten Stunden als Strichbild."""
    bild = Image.new("1", (BREITE, HOEHE), 0)
    z = ImageDraw.Draw(bild)
    _kopfzeile(z, s, "Verlauf", not zustand.get("verbunden", False))
    punkte = zustand.get("punkte") or []
    if len(punkte) < 2:
        _mitte(z, "noch keine Daten", s.normal, 11, 63)
        return bild

    oben, unten = 21, 52
    hoch = max(5.0, max(max(p[1], p[2]) for p in punkte)) * 1.15
    t0, t1 = punkte[0][0], punkte[-1][0]
    spanne = max(1, t1 - t0)

    def X(t):
        return (BREITE - 1) * (t - t0) / spanne

    def Y(v):
        return unten - (unten - oben) * min(v, hoch) / hoch

    # Flaechenabfall durchgezogen, Absinken gepunktet (mehr Unterschied
    # gibt ein einfarbiges Display nicht her)
    z.line([(X(p[0]), Y(p[1])) for p in punkte], fill=1)
    for p in punkte[::2]:
        z.point((X(p[0]), Y(p[2])), fill=1)
    z.line([(0, unten + 1), (BREITE - 1, unten + 1)], fill=1)
    z.text((0, 12), "max %.0f %%" % hoch, font=s.winzig, fill=1)   # 12..20
    z.text((0, 54), "%.0f h    - Abfall   . Sinkt" % ((t1 - t0) / 3600.0),
           font=s.winzig, fill=1)                                   # 54..62
    return bild


SEITEN = (seite_pflanze, seite_technik, seite_verlauf)


def baue_seite(zustand, s, nummer, versatz=(0, 0)):
    """Eine Seite zeichnen; der kleine Versatz beugt Einbrennen vor."""
    inhalt = SEITEN[nummer % len(SEITEN)](zustand, s)
    if versatz == (0, 0):
        return inhalt
    rahmen = Image.new("1", (BREITE, HOEHE), 0)
    rahmen.paste(inhalt, versatz)
    return rahmen


# ---------------- Betriebsschleife ----------------

def schleife(hole_zustand, oled=None, seitenzeit=SEITENZEIT, takt=TAKT):
    """Laeuft bis zum Programmende. hole_zustand() liefert das Zustandsdictionary."""
    if oled is None:
        oled = OLED()
    schriften = Schriften()
    seite = 0
    letzter_wechsel = time.time()
    versatz = (0, 0)
    try:
        while True:
            try:
                bild = baue_seite(hole_zustand(), schriften, seite, versatz)
                oled.zeige(bild)
            except OSError as e:
                print("OLED: Schreibfehler (%s) - versuche weiter" % e)
                time.sleep(2.0)
            time.sleep(takt)
            if time.time() - letzter_wechsel >= seitenzeit:
                seite += 1
                letzter_wechsel = time.time()
                versatz = ((versatz[0] + 1) % 2, (versatz[1] + 1) % 2)
    finally:
        oled.aus()


def starte(hole_zustand, **kw):
    """Anzeige in einem Hintergrundfaden starten.
    Rueckgabe: True, wenn das Display gefunden wurde."""
    import threading
    try:
        oled = OLED(bus=kw.pop("bus", BUS_NUMMER),
                    adresse=kw.pop("adresse", ADRESSE),
                    treiber=kw.pop("treiber", TREIBER),
                    kopfstehend=kw.pop("kopfstehend", KOPFSTEHEND),
                    kontrast=kw.pop("kontrast", KONTRAST))
    except Exception as e:
        print("OLED nicht in Betrieb: %s" % e)
        return False
    threading.Thread(target=schleife, args=(hole_zustand, oled),
                     kwargs=kw, daemon=True).start()
    print("OLED laeuft auf /dev/i2c-%d, Adresse 0x%02X (%s)"
          % (BUS_NUMMER, oled.adresse, oled.treiber))
    return True


# ---------------- Eigenstaendiger Test ----------------

def _beispiel():
    jetzt = int(time.time())
    return {
        "verbunden": True, "bildnummer": 123, "groesse": 48000,
        "wiederholungen_gesamt": 7, "fehlbilder": 1,
        "web": "tomate.local:8083",
        "kamera": {"betrieb_s": 43380, "rssi": -67, "heap_kb": 118},
        "pflanze": {"ampel": "gelb", "status": "beobachten",
                    "flaeche": 12.3, "schwerpunkt": 44.0,
                    "flaechen_abfall": 9.4, "absinken": 2.1,
                    "referenz_zeit": "14.08. 19:30"},
        "punkte": [[jetzt - 3600 * (40 - i), i * 0.3, i * 0.08] for i in range(40)],
    }


if __name__ == "__main__":
    import sys
    if not PIL_DA:
        raise SystemExit("Pillow fehlt:  sudo apt install python3-pil")
    d = OLED()
    print("Display gefunden: Adresse 0x%02X, Treiber %s" % (d.adresse, d.treiber))
    s = Schriften()
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        print("Seitenwechsel mit Beispieldaten - Ende mit Strg+C")
        try:
            schleife(_beispiel, d, seitenzeit=3.0)
        except KeyboardInterrupt:
            print("\nBeendet.")
    else:
        d.zeige(baue_seite(_beispiel(), s, 0))
        print("Testbild steht 10 s auf dem Display.")
        time.sleep(10)
        d.schliesse()
