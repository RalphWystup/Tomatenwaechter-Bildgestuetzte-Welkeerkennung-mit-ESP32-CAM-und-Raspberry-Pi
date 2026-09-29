# -*- coding: utf-8 -*-
"""
livecam.py
Zweite Kamera am Raspberry Pi: eine gewoehnliche USB-Webcam, die die
Umgebung als fluessiges Livebild zeigt. Ergaenzt die ESP32-CAM, die nur
alle fuenf Minuten ein Einzelbild fuer die Pflanzenauswertung liefert.

Der Kunstgriff fuer Fluessigkeit auf schwacher Hardware: Fast jede USB-Kamera
liefert ihre Bilder bereits als fertige JPEG (Format MJPG). Diese Bilder
werden NICHT entpackt und neu gepackt, sondern unveraendert an den Browser
durchgereicht. Damit hat der Pi kaum Arbeit - er sortiert nur Bytes.
Beherrscht die Kamera kein MJPG, packt ffmpeg die Bilder selbst; das kostet
Rechenzeit und ist die Rueckfallebene.

Uebertragen wird als "motion JPEG": eine nie endende HTTP-Antwort, in der ein
Bild nach dem anderen steht. Jeder Browser kann das ohne Zusatzsoftware
anzeigen, es genuegt ein <img>-Element.

Der Datenstrom laeuft NUR, solange jemand zusieht. Meldet sich der letzte
Zuschauer ab, wird die Kamera nach kurzer Nachlaufzeit wieder abgeschaltet -
das schont Rechenzeit, Strom und bei Mobilfunk das Datenvolumen.

Voraussetzung:  sudo apt install -y ffmpeg v4l-utils

Einzeln pruefen:
    python3 livecam.py            Kamera suchen, 5 s aufnehmen, Bilder zaehlen
    python3 livecam.py test       dasselbe mit einem erzeugten Testbild
"""
import glob
import os
import subprocess
import threading
import time

# ------------- Einstellungen -------------
GERAET      = None      # None = erste echte Kamera nehmen, sonst z.B. "/dev/video0"
# Was die angeschlossene "HD USB Camera" in MJPG kann:
#   640x480, 800x600, 1024x768 mit 30 B/s | 1280x960, 1600x1200 mit 15 B/s
# Groesser heisst mehr Datenmenge, nicht mehr Rechenlast - die Bilder werden
# ja nur durchgereicht. Ueber Mobilfunk ist 640x480 die sparsame Wahl.
BREITE      = 800
HOEHE       = 600
BILDRATE    = 15        # angeforderte Bilder je Sekunde
QUALITAET   = 6         # nur wenn ffmpeg selbst packen muss: 2 (gut) .. 15 (grob)
NACHLAUF    = 10.0      # s weiterlaufen, nachdem der letzte Zuschauer ging
NEUSTART    = 3.0       # s Wartezeit nach einem Abbruch
# -----------------------------------------

_sperre = threading.Lock()
_neues_bild = threading.Condition(_sperre)
_letztes = b""
_nummer = 0
_zuschauer = 0
_prozess = None
_laeuft = False

zustand = {
    "moeglich": False,      # ffmpeg und Kamera vorhanden?
    "laeuft": False,
    "geraet": "",
    "meldung": "nicht gestartet",
    "zuschauer": 0,
    "bilder": 0,
    "bildrate": 0.0,
    "groesse_kb": 0.0,
    "packt_selbst": False,  # True = ffmpeg muss JPEG erzeugen (mehr Last)
    "name": "",
}


def _geraetename(pfad):
    """Klarname eines Videogeraets, z.B. 'HD USB Camera'."""
    try:
        with open("/sys/class/video4linux/%s/name" % os.path.basename(pfad)) as f:
            return f.read().strip()
    except OSError:
        return ""


def kameras():
    """Echte Kameras. Der Raspberry Pi meldet ein gutes Dutzend Videogeraete,
    von denen die meisten interne Bausteine sind (bcm2835-codec fuer das
    Kodieren, bcm2835-isp fuer die Bildverarbeitung). Die werden hier
    ausgesiebt, sonst landet man beim Suchen im falschen Geraet.
    Auch eine einzelne USB-Kamera meldet oft zwei Geraete; das erste ist
    die Bildquelle, das zweite ein Zusatzkanal."""
    gefunden = []
    for pfad in sorted(glob.glob("/dev/video*"),
                       key=lambda s: int(s.rsplit("video", 1)[1] or 0)):
        name = _geraetename(pfad)
        if "bcm2835" in name.lower():
            continue
        gefunden.append(pfad)
    return gefunden


def _geraet_waehlen():
    if GERAET:
        return GERAET
    liste = kameras()
    return liste[0] if liste else None


def _befehl(geraet, mjpg_direkt, testquelle=False):
    grund = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if testquelle:
        grund += ["-re", "-f", "lavfi", "-i",
                  "testsrc=size=%dx%d:rate=%d" % (BREITE, HOEHE, BILDRATE)]
        return grund + ["-f", "mjpeg", "-q:v", str(QUALITAET), "-"]
    if mjpg_direkt:
        # Bilder unveraendert durchreichen - der billigste Weg
        grund += ["-f", "v4l2", "-input_format", "mjpeg",
                  "-video_size", "%dx%d" % (BREITE, HOEHE),
                  "-framerate", str(BILDRATE), "-i", geraet]
        return grund + ["-c:v", "copy", "-f", "mjpeg", "-"]
    # Rueckfallebene: ffmpeg packt selbst
    grund += ["-f", "v4l2", "-video_size", "%dx%d" % (BREITE, HOEHE),
              "-framerate", str(BILDRATE), "-i", geraet]
    return grund + ["-f", "mjpeg", "-q:v", str(QUALITAET), "-"]


def _lies_bilder(prozess):
    """Den Datenstrom in einzelne JPEG zerlegen. Ein JPEG beginnt mit
    FF D8 und endet mit FF D9 - dazwischen wird nichts angefasst."""
    global _letztes, _nummer
    puffer = b""
    letzte_zeit = time.time()
    zaehler = 0
    while True:
        stueck = prozess.stdout.read(16384)
        if not stueck:
            return
        puffer += stueck
        while True:
            anfang = puffer.find(b"\xff\xd8")
            if anfang < 0:
                break
            ende = puffer.find(b"\xff\xd9", anfang + 2)
            if ende < 0:
                if anfang > 0:
                    puffer = puffer[anfang:]      # Schrott davor verwerfen
                break
            bild = puffer[anfang:ende + 2]
            puffer = puffer[ende + 2:]
            with _neues_bild:
                _letztes = bild
                _nummer += 1
                _neues_bild.notify_all()
            zaehler += 1
            jetzt = time.time()
            if jetzt - letzte_zeit >= 2.0:
                zustand["bildrate"] = round(zaehler / (jetzt - letzte_zeit), 1)
                zustand["groesse_kb"] = round(len(bild) / 1024.0, 1)
                zustand["bilder"] = _nummer
                zaehler = 0
                letzte_zeit = jetzt


def _versorger():
    """Haelt die Kamera am Laufen, solange jemand zusieht."""
    global _prozess, _laeuft
    leerlauf_seit = None
    while True:
        with _sperre:
            gewuenscht = _zuschauer > 0
        if gewuenscht:
            leerlauf_seit = None
            if not _laeuft:
                _starte_aufnahme()
        else:
            if _laeuft:
                if leerlauf_seit is None:
                    leerlauf_seit = time.time()
                elif time.time() - leerlauf_seit > NACHLAUF:
                    _stoppe_aufnahme("keine Zuschauer")
                    leerlauf_seit = None
        time.sleep(0.5)


def _starte_aufnahme():
    global _prozess, _laeuft
    geraet = _geraet_waehlen()
    if not geraet:
        zustand["meldung"] = "keine Kamera gefunden (/dev/video*)"
        time.sleep(NEUSTART)
        return
    zustand["geraet"] = geraet
    zustand["name"] = _geraetename(geraet)
    for mjpg_direkt in (True, False):
        try:
            _prozess = subprocess.Popen(_befehl(geraet, mjpg_direkt),
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        bufsize=0)
        except FileNotFoundError:
            zustand["meldung"] = "ffmpeg fehlt (sudo apt install -y ffmpeg)"
            time.sleep(NEUSTART)
            return
        # Kurz abwarten, ob er ueberhaupt Bilder liefert
        anfang = _nummer
        _laeuft = True
        zustand.update(laeuft=True, packt_selbst=not mjpg_direkt, meldung="laeuft")
        faden = threading.Thread(target=_lies_bilder, args=(_prozess,), daemon=True)
        faden.start()
        for _ in range(30):
            time.sleep(0.1)
            if _nummer > anfang:
                return                      # es kommen Bilder, alles gut
            if _prozess.poll() is not None:
                break
        fehler = b""
        try:
            fehler = _prozess.stderr.read(400)
        except Exception:
            pass
        _stoppe_aufnahme("kein Bild" + (": " + fehler.decode(errors="replace")
                                        if fehler else ""))
        if mjpg_direkt:
            continue                        # zweiter Versuch: selbst packen
        time.sleep(NEUSTART)


def _stoppe_aufnahme(grund):
    global _prozess, _laeuft
    if _prozess:
        try:
            _prozess.terminate()
            _prozess.wait(timeout=2)
        except Exception:
            try:
                _prozess.kill()
            except Exception:
                pass
    _prozess = None
    _laeuft = False
    zustand.update(laeuft=False, meldung=grund, bildrate=0.0)


# ---------------- Schnittstelle fuer das Dashboard ----------------

def anmelden():
    global _zuschauer
    with _sperre:
        _zuschauer += 1
        zustand["zuschauer"] = _zuschauer


def abmelden():
    global _zuschauer
    with _sperre:
        _zuschauer = max(0, _zuschauer - 1)
        zustand["zuschauer"] = _zuschauer


def naechstes_bild(letzte_nummer, wartezeit=5.0):
    """Wartet auf ein Bild, das neuer ist als die uebergebene Nummer.
    Langsame Zuschauer bekommen dadurch von selbst weniger Bilder,
    statt dass sich ein Rueckstau bildet."""
    with _neues_bild:
        if _nummer <= letzte_nummer:
            _neues_bild.wait(wartezeit)
        return _nummer, _letztes


def letztes_bild():
    with _sperre:
        return _letztes


def kopie():
    p = dict(zustand)
    p["kameras"] = kameras()
    return p


def starte():
    """Versorgerfaden starten. Die Kamera selbst laeuft erst, wenn jemand
    zusieht."""
    if not kameras():
        zustand["meldung"] = "keine Kamera angeschlossen"
        print("Livekamera: " + zustand["meldung"])
        return False
    zustand["moeglich"] = True
    zustand["meldung"] = "bereit"
    threading.Thread(target=_versorger, daemon=True).start()
    return True


# ---------------- Einzeltest ----------------

if __name__ == "__main__":
    import sys
    test = len(sys.argv) > 1 and sys.argv[1] == "test"
    if test:
        print("Testbild statt Kamera")
        _prozess = subprocess.Popen(_befehl(None, False, testquelle=True),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=_lies_bilder, args=(_prozess,), daemon=True).start()
    else:
        print("Gefundene Videogeraete:", ", ".join(kameras()) or "keine")
        if not starte():
            raise SystemExit(1)
        anmelden()
    zeit = time.time()
    while time.time() - zeit < 5.0:
        time.sleep(0.5)
        print("  Bilder %d, %.1f/s, %.1f kB, %s"
              % (_nummer, zustand["bildrate"], zustand["groesse_kb"],
                 zustand["meldung"]))
    if _prozess:
        _prozess.terminate()
    print("Ergebnis: %d Bilder in 5 s%s" %
          (_nummer, "" if not zustand["packt_selbst"]
           else "  (ffmpeg musste selbst packen - hoehere Last)"))
