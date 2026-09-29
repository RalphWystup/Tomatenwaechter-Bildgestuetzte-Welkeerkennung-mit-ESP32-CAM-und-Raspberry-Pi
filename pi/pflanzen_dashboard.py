# -*- coding: utf-8 -*-
"""
pflanzen_dashboard.py
Tomaten-Bewaesserungswaechter auf Basis von cam_dashboard.py:
Die ESP32-CAM (ESP32_CAM_Modbus_Snapshot.ino) beobachtet eine
Tomatenpflanze; die Bilder kommen wie gehabt blockweise und
CRC-gesichert ueber Modbus TCP. Neu ist die Bildauswertung:

  * Die Pflanze wird ueber den Gruenanteil vom Hintergrund getrennt
    (Excess-Green-Index ExG = 2G - R - B).
  * Welke Blaetter haengen durch -> die sichtbare Gruenflaeche
    schrumpft und der Schwerpunkt der Gruenmaske sinkt ab.
  * Beide Kennwerte werden mit einer REFERENZ verglichen, die man
    einmal direkt nach dem Giessen im Dashboard setzt
    (Knopf "Referenz setzen"). Daraus entsteht die Bewertung:
        GRUEN  Wasser ausreichend
        GELB   beobachten, bald giessen
        ROT    GIESSEN!
  * Alle Messwerte werden in pflanzen_log.csv protokolliert,
    das Dashboard zeigt Livebild, Gruenmaske, Kennwerte und
    den Verlauf der letzten Stunden.

Wichtig fuer verlaessliche Ergebnisse:
  - Kamera fest montieren (Stativ), Pflanze bildfuellend
  - moeglichst gleichmaessige Beleuchtung (notfalls Blitz einschalten)
  - Referenz immer nach dem Giessen bei derselben Beleuchtung setzen

Benoetigt numpy und Pillow (bei matplotlib bereits dabei):
    pip install numpy pillow
Aufruf:  python pflanzen_dashboard.py     Dashboard: Port 8083
"""
import io
import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    ANALYSE_MOEGLICH = True
except ImportError:
    ANALYSE_MOEGLICH = False

try:
    import waveshare_io                      # Relais, DI, AI, AO ueber RS485
    MODUL_A_MOEGLICH = True
except ImportError:
    MODUL_A_MOEGLICH = False

try:
    import livecam                           # USB-Kamera als Livebild
    LIVECAM_MOEGLICH = True
except ImportError:
    LIVECAM_MOEGLICH = False

# ------------- Einstellungen -------------
# Kamera ueber ihren NAMEN ansprechen - funktioniert auch, wenn sich die
# IP nach einem Neustart aendert (Solar-Abschaltung!). Falls der Name nicht
# aufgeloest wird: "tomatencam.local" versuchen, oder notfalls die IP eintragen.
ESP32CAM_IP        = "tomatencam.fritz.box"
TCP_PORT           = 502
INTERVALL          = 300.0               # s zwischen zwei Bildern (Pflanze: 5 min)
MAX_WIEDERHOLUNGEN = 5                   # Versuche je Block
WEB_PORT           = 8083
ORDNER             = "pflanzen_bilder"   # Speicherordner (leer = nicht speichern)
LOGDATEI           = "pflanzen_log.csv"
REFERENZDATEI      = "pflanzen_referenz.json"

# ---- Auswertung (bei Bedarf anpassen) ----
EXG_SCHWELLE       = 40      # ab diesem ExG-Wert gilt ein Pixel als "gruen"
MIN_GRUEN          = 60      # Mindest-Gruenkanal, unterdrueckt dunkles Rauschen
MIN_FLAECHE        = 2.0     # % Gruenanteil, darunter: "Pflanze nicht erkannt"
MIN_HELLIGKEIT     = 40      # mittlere Bildhelligkeit, darunter: "zu dunkel"
# Grenzen fuer die Bewertung (relativ zur Referenz):
GELB_FLAECHE       = 8.0     # % Flaechenabfall  -> gelb ab hier
ROT_FLAECHE        = 15.0    # % Flaechenabfall  -> rot ab hier
GELB_ABSINKEN      = 2.0     # % Bildhoehe Schwerpunkt-Absinken -> gelb
ROT_ABSINKEN       = 4.0     # % Bildhoehe Schwerpunkt-Absinken -> rot
GLAETTUNG          = 5       # Median ueber die letzten n Messungen
VERLAUF_MAX        = 576     # Punkte im Verlaufsdiagramm (2 Tage bei 5 min)

# ---- OLED-Anzeige vor Ort (Raspberry Pi, 128x64 ueber I2C) ----
OLED_AKTIV         = True    # False = ohne Display (z.B. auf dem PC)
OLED_TREIBER       = "ssd1306"   # "sh1106" bei vielen 1,3"-Modulen
OLED_BUS           = 1       # /dev/i2c-1
OLED_ADRESSE       = None    # None = 0x3C/0x3D selbst suchen
OLED_KOPFSTEHEND   = False   # True dreht das Bild um 180 Grad
OLED_SEITENZEIT    = 6.0     # s je Anzeigeseite

# ---- Modul A (Waveshare Modbus RTU) am USB-RS485-Wandler ----
MODUL_A_AKTIV      = True    # False = ohne Ein-/Ausgabemodul
GIESSZEIT          = 20      # s Vorgabe fuer den Giess-Knopf

# ---- Bildaufbereitung fuer die ANZEIGE (nicht fuer die Auswertung!) ----
# Stufe 0 = aus, 1 = sanft, 2 = mittel, 3 = stark. Im Dashboard umschaltbar.
AUFBEREITUNG       = 0
# Je Stufe: (Kontrastfaktor, Staerke der Unschaerfemaske in %, Radius)
STUFEN = {0: None, 1: (1.10, 60, 1.2), 2: (1.25, 110, 1.6), 3: (1.45, 180, 2.0)}

# ---- Umgebungskamera (USB-Webcam am Pi) ----
LIVECAM_AKTIV      = True    # False = ohne Livebild

# ---- Dauerbetrieb auf der SD-Karte ----
BILDER_TAGE        = 14      # Bilder aelter als n Tage loeschen (0 = nie)
# -----------------------------------------

BLOCK_BYTES = 240
BLOCK_REGS  = 120

buslock = threading.Lock()
datenschloss = threading.Lock()
sock = None
transaktions_nr = 0

zustand = {
    "verbunden": False, "meldung": "starte ...",
    "bildnummer": 0, "groesse": 0, "bloecke": 0,
    "dauer": 0.0, "rate_kbs": 0.0,
    "wiederholungen": 0, "wiederholungen_gesamt": 0, "fehlbilder": 0,
    "blitz": 0,
    "aufbereitung": AUFBEREITUNG,
    "web": "",                           # eigene Adresse, nur fuer die OLED-Anzeige
    "kamera": None,                    # {"betrieb_s","rssi","heap_kb"} (neuer Sketch)
    "verlauf": [],                       # letzte 10 Uebertragungen (Text)
    # ---- Pflanze ----
    "analyse_ok": ANALYSE_MOEGLICH,
    "pflanze": {
        "status": "keine Referenz",      # gruen / gelb / rot / Textmeldung
        "ampel": "grau",                 # gruen | gelb | rot | grau
        "flaeche": 0.0,                  # Gruenanteil in % des Bildes
        "schwerpunkt": 0.0,              # 0 = oben ... 100 = unten
        "helligkeit": 0.0,
        "flaechen_abfall": None,         # % gegenueber Referenz
        "absinken": None,                # % Bildhoehe gegenueber Referenz
        "referenz_zeit": None,
    },
    "punkte": [],                        # [[unixzeit, abfall, absinken], ...]
}
letztes_jpeg = b""          # Anzeigebild (mit Zeitstempel)
letztes_original = b""      # unveraendert von der Kamera - Grundlage der Aufbereitung
letzter_stempel = ""
aufbereitet = (None, None, b"")   # (Bildnummer, Stufe, Ergebnis) als Zwischenspeicher
letzte_maske = b""
referenz = None                          # {"flaeche":..,"schwerpunkt":..,"zeit":..}
mess_puffer = []                         # letzte Messungen fuer Median


def crc16(daten):
    crc = 0xFFFF
    for b in daten:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


# ---------------- Modbus TCP (unveraendert aus cam_dashboard.py) -----------

def verbinde():
    global sock
    sock = socket.create_connection((ESP32CAM_IP, TCP_PORT), timeout=8.0)
    sock.settimeout(8.0)


def empfange(n):
    daten = b""
    while len(daten) < n:
        teil = sock.recv(n - len(daten))
        if not teil:
            raise IOError("Verbindung geschlossen")
        daten += teil
    return daten


def transaktion(pdu):
    global transaktions_nr
    with buslock:
        transaktions_nr = (transaktions_nr + 1) & 0xFFFF
        kopf = struct.pack(">HHHB", transaktions_nr, 0, len(pdu) + 1, 1)
        sock.sendall(kopf + pdu)
        antwort_kopf = empfange(7)
        _tid, _proto, laenge, unit = struct.unpack(">HHHB", antwort_kopf)
        rest = empfange(laenge - 1)
    if rest[0] & 0x80:
        raise IOError("Modbus-Ausnahme %d" % rest[1])
    return rest


def lese_register(start, anzahl):
    a = transaktion(struct.pack(">BHH", 3, start, anzahl))
    n = a[1] // 2
    return list(struct.unpack(">%dH" % n, a[2:2 + 2 * n]))


def schreibe_register(adresse, wert):
    transaktion(struct.pack(">BHH", 6, adresse, wert & 0xFFFF))


def hole_block(index, nutzlaenge):
    for versuch in range(MAX_WIEDERHOLUNGEN):
        schreibe_register(6, index)
        regs = lese_register(99, 1 + BLOCK_REGS)
        crc_soll = regs[0]
        rohdaten = b"".join(struct.pack(">H", r) for r in regs[1:])
        block = rohdaten[:nutzlaenge]
        if crc16(block) == crc_soll:
            return block, versuch
    raise IOError("Block %d nach %d Versuchen defekt" % (index, MAX_WIEDERHOLUNGEN))


def hole_bild():
    start = time.time()
    schreibe_register(8, 1)
    kopf = lese_register(0, 11)
    nummer, status = kopf[0], kopf[1]
    groesse = (kopf[2] << 16) | kopf[3]
    bloecke, bild_crc = kopf[5], kopf[10]
    if status != 2 or groesse == 0:
        raise IOError("Kamera meldet Status %d" % status)
    daten = bytearray()
    wiederholungen = 0
    for b in range(bloecke):
        nutz = min(BLOCK_BYTES, groesse - b * BLOCK_BYTES)
        block, extra = hole_block(b, nutz)
        daten += block
        wiederholungen += extra
    if len(daten) != groesse:
        raise IOError("Laenge falsch: %d statt %d" % (len(daten), groesse))
    if crc16(daten) != bild_crc:
        raise IOError("Gesamt-CRC falsch")
    if daten[:2] != b"\xff\xd8" or daten[-2:] != b"\xff\xd9":
        raise IOError("kein gueltiges JPEG (Marker fehlen)")
    dauer = time.time() - start
    info = {"nummer": nummer, "groesse": groesse, "bloecke": bloecke,
            "dauer": dauer, "wiederholungen": wiederholungen,
            "rate_kbs": groesse / 1024.0 / dauer if dauer > 0 else 0.0}
    return bytes(daten), info


def lese_kamera_status():
    """Zusatzdaten der Kamera aus den Registern 11..14 (neuer Sketch).
    Ein alter Sketch liefert hier einfach Nullen -> wird ignoriert."""
    regs = lese_register(11, 4)
    betrieb = (regs[0] << 16) | regs[1]
    rssi = regs[2] - 65536 if regs[2] > 32767 else regs[2]   # Zweierkomplement
    return {"betrieb_s": betrieb, "rssi": rssi, "heap_kb": regs[3]}


def betriebszeit_text(sekunden):
    return "%d h %02d min" % (sekunden // 3600, (sekunden % 3600) // 60)


# ---------------- Pflanzenauswertung ----------------

def stempel_ins_bild(jpeg, text):
    """Schwarzen Balken mit Zeitstempel/Kameradaten unten ins Bild zeichnen.
    Wird NUR fuer Anzeige und Speicherung benutzt - die Gruenanalyse
    laeuft immer auf dem Originalbild."""
    bild = Image.open(io.BytesIO(jpeg)).convert("RGB")
    balken = max(18, bild.height // 20)
    schrift = None
    for name in ("DejaVuSans.ttf", "arial.ttf"):      # Linux, Windows
        try:
            schrift = ImageFont.truetype(name, balken - 6)
            break
        except Exception:
            pass
    if schrift is None:
        schrift = ImageFont.load_default()
    zeichner = ImageDraw.Draw(bild)
    zeichner.rectangle([0, bild.height - balken, bild.width, bild.height],
                       fill=(0, 0, 0))
    zeichner.text((6, bild.height - balken + 3), text,
                  fill=(255, 255, 255), font=schrift)
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=85)
    return puffer.getvalue()



def aufbereiten(jpeg, stufe, text=""):
    """Anzeigebild aufhellen und scharfzeichnen. Wird NUR fuer die Anzeige
    verwendet - die Pflanzenauswertung rechnet immer mit dem Originalbild,
    sonst wuerde man sich die Messwerte verfaelschen.

    Zwei Schritte: Erst eine massvolle Kontrastanhebung gegen den milchigen
    Schleier einer Regenhaube, dann die Unschaerfemaske, die Kanten anhebt.
    Die Unschaerfemaske kann keine verlorenen Einzelheiten zurueckholen, macht
    aber sichtbar, was noch im Bild steckt.

    Bewusst KEINE volle Kontrastspreizung (autocontrast): Die dehnt den
    Helligkeitsbereich bis an die Anschlaege und laesst Farben ausbrennen -
    aus brauner Erde wird dunkelrot, aus Blattgruen Neongruen. Ein fester,
    begrenzter Faktor kann nicht ausreissen."""
    werte = STUFEN.get(stufe)
    if not werte:
        return stempel_ins_bild(jpeg, text) if text else jpeg
    kontrast, staerke, radius = werte
    bild = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if kontrast != 1.0:
        bild = ImageEnhance.Contrast(bild).enhance(kontrast)
    bild = bild.filter(ImageFilter.UnsharpMask(radius=radius,
                                               percent=int(staerke), threshold=2))
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=88)
    ergebnis = puffer.getvalue()
    return stempel_ins_bild(ergebnis, text) if text else ergebnis


def gruenmaske(rgb):
    """Excess-Green-Maske: True = Pflanzenpixel."""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    exg = 2 * g - r - b
    return (exg > EXG_SCHWELLE) & (g > MIN_GRUEN)


def analysiere(jpeg):
    """Kennwerte des Bildes bestimmen. Rueckgabe: (kennwerte, masken_jpeg)."""
    rgb = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"))
    hoehe = rgb.shape[0]
    helligkeit = float(rgb.mean())
    maske = gruenmaske(rgb)
    flaeche = 100.0 * maske.mean()

    if maske.sum() > 0:
        zeilen = np.nonzero(maske.any(axis=1))[0]
        gewichte = maske.sum(axis=1)
        schwerpunkt = 100.0 * float(
            (np.arange(hoehe) * gewichte).sum() / gewichte.sum()) / hoehe
    else:
        schwerpunkt = 0.0

    # Kontrollbild: Pflanze farbig, Rest abgedunkelt
    kontrolle = (rgb * 0.25).astype(np.uint8)
    kontrolle[maske] = rgb[maske]
    puffer = io.BytesIO()
    Image.fromarray(kontrolle).save(puffer, "JPEG", quality=80)

    kennwerte = {"flaeche": round(flaeche, 2),
                 "schwerpunkt": round(schwerpunkt, 2),
                 "helligkeit": round(helligkeit, 1)}
    return kennwerte, puffer.getvalue()


def bewerte(kennwerte):
    """Vergleich mit der Referenz -> Ampel und Text."""
    global mess_puffer
    p = dict(kennwerte)
    p["flaechen_abfall"] = None
    p["absinken"] = None
    p["referenz_zeit"] = referenz["zeit"] if referenz else None

    if kennwerte["helligkeit"] < MIN_HELLIGKEIT:
        p["status"] = "zu dunkel fuer Auswertung (Nacht?)"
        p["ampel"] = "grau"
        return p, None
    if kennwerte["flaeche"] < MIN_FLAECHE:
        p["status"] = "Pflanze nicht erkannt (Gruenanteil %.1f %%)" % kennwerte["flaeche"]
        p["ampel"] = "grau"
        return p, None
    if referenz is None:
        p["status"] = "Referenz fehlt - nach dem Giessen setzen!"
        p["ampel"] = "grau"
        return p, None

    mess_puffer = (mess_puffer + [(kennwerte["flaeche"],
                                   kennwerte["schwerpunkt"])])[-GLAETTUNG:]
    fl = sorted(m[0] for m in mess_puffer)[len(mess_puffer) // 2]
    sp = sorted(m[1] for m in mess_puffer)[len(mess_puffer) // 2]

    abfall = max(0.0, 100.0 * (1.0 - fl / referenz["flaeche"]))
    absinken = max(0.0, sp - referenz["schwerpunkt"])
    p["flaechen_abfall"] = round(abfall, 1)
    p["absinken"] = round(absinken, 1)

    if abfall >= ROT_FLAECHE or absinken >= ROT_ABSINKEN:
        p["status"] = "GIESSEN! Blaetter haengen deutlich"
        p["ampel"] = "rot"
    elif abfall >= GELB_FLAECHE or absinken >= GELB_ABSINKEN:
        p["status"] = "beobachten - Pflanze wird schlapp"
        p["ampel"] = "gelb"
    else:
        p["status"] = "Wasser ausreichend"
        p["ampel"] = "gruen"
    return p, (abfall, absinken)


def schreibe_log(nummer, p):
    neu = not os.path.exists(LOGDATEI)
    with open(LOGDATEI, "a", encoding="utf-8") as f:
        if neu:
            f.write("zeit;bildnummer;helligkeit;flaeche_prozent;"
                    "schwerpunkt_prozent;flaechen_abfall;absinken;status\n")
        f.write("%s;%d;%.1f;%.2f;%.2f;%s;%s;%s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), nummer,
            p["helligkeit"], p["flaeche"], p["schwerpunkt"],
            p["flaechen_abfall"] if p["flaechen_abfall"] is not None else "",
            p["absinken"] if p["absinken"] is not None else "",
            p["status"]))


def raeume_bilder_auf():
    """Alte Bilder loeschen - im Dauerbetrieb laeuft sonst die SD-Karte voll
    (bei 5 min Takt rund 300 Bilder = 4 MB pro Tag)."""
    if not ORDNER or not BILDER_TAGE or not os.path.isdir(ORDNER):
        return 0
    grenze = time.time() - BILDER_TAGE * 86400.0
    geloescht = 0
    for name in os.listdir(ORDNER):
        pfad = os.path.join(ORDNER, name)
        try:
            if os.path.isfile(pfad) and os.path.getmtime(pfad) < grenze:
                os.remove(pfad)
                geloescht += 1
        except OSError:
            pass
    return geloescht


def lade_referenz():
    global referenz
    if os.path.exists(REFERENZDATEI):
        with open(REFERENZDATEI, encoding="utf-8") as f:
            referenz = json.load(f)


def setze_referenz():
    """Aktuelle (Median-)Kennwerte als frisch-gegossen-Referenz speichern."""
    global referenz, mess_puffer
    with datenschloss:
        p = zustand["pflanze"]
        if p["flaeche"] < MIN_FLAECHE:
            raise IOError("Pflanze derzeit nicht erkannt - Referenz nicht gesetzt")
        referenz = {"flaeche": p["flaeche"], "schwerpunkt": p["schwerpunkt"],
                    "zeit": time.strftime("%d.%m.%Y %H:%M")}
    mess_puffer = []
    with open(REFERENZDATEI, "w", encoding="utf-8") as f:
        json.dump(referenz, f)


# ---------------- Abfrageschleife ----------------

def abfrageschleife():
    global sock, letztes_jpeg, letzte_maske, letztes_original, letzter_stempel
    letzte_betriebszeit = None
    if ORDNER and not os.path.isdir(ORDNER):
        os.makedirs(ORDNER)
    lade_referenz()
    naechstes_aufraeumen = time.time()
    naechster = time.time()
    while True:
        try:
            if sock is None:
                verbinde()
                # Nach Stromausfall (Solarmodul!) startet die Kamera neu und
                # vergisst den Blitz-Zustand -> hier wiederherstellen.
                schreibe_register(9, zustand["blitz"])
            jpeg, info = hole_bild()

            # Zusatzdaten der Kamera (Register 11..14, nur neuer Sketch)
            kamera = None
            try:
                k = lese_kamera_status()
                if k["betrieb_s"] > 0:
                    kamera = k
            except Exception:
                pass
            neustart = (kamera is not None and letzte_betriebszeit is not None
                        and kamera["betrieb_s"] < letzte_betriebszeit)
            if kamera is not None:
                letzte_betriebszeit = kamera["betrieb_s"]

            pflanze, trend = (zustand["pflanze"], None)
            maske = b""
            if ANALYSE_MOEGLICH:
                kennwerte, maske = analysiere(jpeg)
                pflanze, trend = bewerte(kennwerte)
                schreibe_log(info["nummer"], pflanze)

            # Zeitstempel (+ Kameradaten) unten ins Anzeige-/Speicherbild
            anzeige_jpeg = jpeg
            if ANALYSE_MOEGLICH:
                text = time.strftime("%d.%m.%Y %H:%M:%S") + "  Bild %d" % info["nummer"]
                if kamera is not None:
                    text += "  |  %d dBm  |  Kamera an seit %s" % (
                        kamera["rssi"], betriebszeit_text(kamera["betrieb_s"]))
                try:
                    anzeige_jpeg = stempel_ins_bild(jpeg, text)
                except Exception:
                    pass

            with datenschloss:
                letztes_jpeg = anzeige_jpeg
                letztes_original = jpeg
                letzter_stempel = text if ANALYSE_MOEGLICH else ""
                letzte_maske = maske
                zustand["kamera"] = kamera
                if neustart:
                    zustand["verlauf"] = (["Kamera-Neustart erkannt "
                                           "(Solar-Abschaltung?)"] +
                                          zustand["verlauf"])[:10]
                zustand.update(verbunden=True, meldung="OK",
                               bildnummer=info["nummer"], groesse=info["groesse"],
                               bloecke=info["bloecke"],
                               dauer=round(info["dauer"], 2),
                               rate_kbs=round(info["rate_kbs"], 1),
                               wiederholungen=info["wiederholungen"])
                zustand["wiederholungen_gesamt"] += info["wiederholungen"]
                zustand["pflanze"] = pflanze
                if trend is not None:
                    zustand["punkte"] = (zustand["punkte"] +
                                         [[int(time.time()), trend[0], trend[1]]]
                                         )[-VERLAUF_MAX:]
                zeile = ("Bild %d: %.1f kB, %d Wdh. | Gruen %.1f %%, "
                         "Schwerpunkt %.1f %% -> %s" %
                         (info["nummer"], info["groesse"] / 1024.0,
                          info["wiederholungen"], pflanze.get("flaeche", 0),
                          pflanze.get("schwerpunkt", 0), pflanze["status"]))
                zustand["verlauf"] = ([zeile] + zustand["verlauf"])[:10]
            if ORDNER:
                # Zeitstempel im Namen: die Bildnummer faengt nach jedem
                # Stromausfall wieder bei 1 an und wuerde alte Bilder ueberschreiben.
                zeitstempel = time.strftime("%Y%m%d_%H%M%S")
                name = os.path.join(ORDNER, "bild_%s_%05d.jpg" % (zeitstempel, info["nummer"]))
                with open(name, "wb") as f:
                    f.write(anzeige_jpeg)        # mit Zeitstempel im Bild
            print(zeile)
        except Exception as e:
            with datenschloss:
                zustand["verbunden"] = False
                zustand["meldung"] = str(e) or e.__class__.__name__
                zustand["fehlbilder"] += 1
            print("Fehler:", zustand["meldung"])
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
            sock = None
            time.sleep(2.0)
        if time.time() >= naechstes_aufraeumen:
            naechstes_aufraeumen = time.time() + 86400.0
            weg = raeume_bilder_auf()
            if weg:
                print("Aufgeraeumt: %d Bilder aelter als %d Tage geloescht"
                      % (weg, BILDER_TAGE))
        naechster += INTERVALL
        pause = naechster - time.time()
        if pause > 0:
            time.sleep(pause)
        else:
            naechster = time.time()


# ---------------- Web-Dashboard ----------------

SEITE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tomaten-Bewaesserungswaechter</title>
<style>
:root{--flaeche:#fcfcfb;--seite:#f9f9f7;--tinte:#0b0b0b;--tinte2:#52514e;
 --gedaempft:#898781;--rand:rgba(11,11,11,.10);
 --serie:#2a78d6;--gut:#0ca30c;--warn:#d99b00;--kritisch:#d03b3b;}
@media (prefers-color-scheme:dark){:root{--flaeche:#1a1a19;--seite:#0d0d0d;
 --tinte:#fff;--tinte2:#c3c2b7;--rand:rgba(255,255,255,.10);--serie:#3987e5;}}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--seite);
 color:var(--tinte);padding:16px}
h1{font-size:1.15rem;font-weight:600}
h2{font-size:.95rem;font-weight:600;margin-bottom:8px}
.kopf{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.status{display:flex;align-items:center;gap:6px;font-size:.85rem;color:var(--tinte2)}
.punkt{width:9px;height:9px;border-radius:50%;background:var(--kritisch)}
.punkt.an{background:var(--gut)}
.karte{background:var(--flaeche);border:1px solid var(--rand);border-radius:10px;
 padding:14px 16px;margin-bottom:14px}
.zeilen{display:flex;gap:14px;flex-wrap:wrap}
.zeilen .karte{flex:1;min-width:280px}
img.bild{max-width:100%;border-radius:6px;display:block}
table{border-collapse:collapse;font-size:.85rem}
td{padding:2px 10px 2px 0;color:var(--tinte2)}
td:last-child{color:var(--tinte);font-variant-numeric:tabular-nums}
ul{font-size:.8rem;color:var(--tinte2);margin-left:18px;line-height:1.5}
button{font:inherit;border:1px solid var(--rand);border-radius:7px;padding:8px 16px;
 background:var(--flaeche);color:var(--tinte);cursor:pointer}
button:hover{border-color:var(--serie)}
button.an{background:var(--gut);border-color:var(--gut);color:#fff}
.fehlerband{color:var(--kritisch);font-size:.85rem;margin-bottom:10px;display:none}
.ampel{display:flex;align-items:center;gap:14px}
.lampe{width:46px;height:46px;border-radius:50%;background:#9a9a94;flex:none;
 box-shadow:inset 0 0 6px rgba(0,0,0,.25)}
.lampe.gruen{background:var(--gut)}.lampe.gelb{background:var(--warn)}
.lampe.rot{background:var(--kritisch);animation:blink 1s infinite}
@keyframes blink{50%{opacity:.35}}
.statuszeile{font-size:1.05rem;font-weight:600}
.unterzeile{font-size:.8rem;color:var(--tinte2);margin-top:2px}
svg{width:100%;height:150px}
.legende{font-size:.75rem;color:var(--tinte2)}
.legende b{font-weight:600}
</style></head><body>
<div class="kopf"><h1>&#127813; Tomaten-Bew&auml;sserungsw&auml;chter</h1>
 <span class="status"><span id="lampe" class="punkt"></span><span id="statustext">verbinde &hellip;</span></span></div>
<div id="fehlerband" class="fehlerband"></div>

<div class="karte"><div class="ampel">
 <div id="wasserlampe" class="lampe"></div>
 <div><div id="wasserstatus" class="statuszeile">&hellip;</div>
  <div id="wasserdetail" class="unterzeile">&ndash;</div>
  <div id="referenzinfo" class="unterzeile">&ndash;</div></div>
 <div style="margin-left:auto"><button onclick="referenz()">Referenz setzen<br>
  <small>(direkt nach dem Gie&szlig;en)</small></button></div>
</div></div>

<div class="zeilen">
 <div class="karte" style="flex:2"><h2>Kamerabild
   <label style="font-weight:400;font-size:.8rem;margin-left:10px">
    <input type="checkbox" id="maskschalter" onchange="bildwechsel()"> Gr&uuml;nmaske zeigen
   </label></h2>
  <div style="font-size:.8rem;color:var(--tinte2);margin-bottom:6px">
    Bildaufbereitung:
    <select id="aufbstufe" onchange="setzeAufbereitung()" style="font:inherit">
     <option value="0">aus (Originalbild)</option>
     <option value="1">sanft</option>
     <option value="2">mittel</option>
     <option value="3">stark</option>
    </select>
    <span style="margin-left:8px">nur die Anzeige &ndash; die Auswertung rechnet
     immer mit dem Original</span>
   </div>
  <img id="bild" class="bild" src="/bild.jpg" alt="noch kein Bild">
 </div>
 <div class="karte"><h2>Kennwerte</h2>
  <table>
   <tr><td>Gr&uuml;nfl&auml;che</td><td id="fl">&ndash;</td></tr>
   <tr><td>Schwerpunkt (0=oben)</td><td id="sp">&ndash;</td></tr>
   <tr><td>Fl&auml;chenabfall zur Referenz</td><td id="fa">&ndash;</td></tr>
   <tr><td>Absinken zur Referenz</td><td id="ab">&ndash;</td></tr>
   <tr><td>Bildhelligkeit</td><td id="he">&ndash;</td></tr>
  </table>
  <h2 style="margin-top:14px">&Uuml;bertragung</h2>
  <table>
   <tr><td>Bildnummer</td><td id="nr">&ndash;</td></tr>
   <tr><td>Gr&ouml;&szlig;e</td><td id="gr">&ndash;</td></tr>
   <tr><td>Dauer</td><td id="da">&ndash;</td></tr>
   <tr><td>Wiederholungen (Bild / gesamt)</td><td><span id="wd">&ndash;</span> / <span id="wg">&ndash;</span></td></tr>
   <tr><td>verworfene Bilder</td><td id="fb">&ndash;</td></tr>
   <tr><td>Kamera an seit</td><td id="kz">&ndash;</td></tr>
   <tr><td>WLAN-Signal</td><td id="rs">&ndash;</td></tr>
   <tr><td>freier Speicher</td><td id="hp">&ndash;</td></tr>
  </table>
  <p style="margin-top:10px"><button id="blitzknopf" onclick="blitz()">Blitz &ndash;</button></p>
 </div>
</div>

<div class="karte"><h2>Umgebungskamera
  <label style="font-weight:400;font-size:.8rem;margin-left:10px">
   <input type="checkbox" id="liveschalter" onchange="liveumschalten()"> Livebild einschalten
  </label></h2>
 <div id="livekopf" class="unterzeile">&ndash;</div>
 <img id="livebild" class="bild" style="display:none;margin-top:8px" alt="Livebild">
</div>

<div class="karte"><h2>Modul A &ndash; Ein- und Ausg&auml;nge</h2>
 <div id="iokopf" class="unterzeile">&ndash;</div>
 <table style="margin-top:8px">
  <tr><td>Analogeingang 1</td><td id="ai1">&ndash;</td></tr>
  <tr><td>Analogeingang 2</td><td id="ai2">&ndash;</td></tr>
  <tr><td>Digitaleing&auml;nge</td><td id="dizeile">&ndash;</td></tr>
  <tr><td>Relais 1 (frei)</td><td><button id="rel1knopf" onclick="relais(1)">&ndash;</button></td></tr>
  <tr><td>Relais 2 (Gie&szlig;en)</td><td>
      <span id="rel2text">&ndash;</span>
      <button onclick="giessen()" style="margin-left:10px">Gie&szlig;en</button>
      <input id="gsek" type="number" min="1" max="600" value="""+str(GIESSZEIT)+r"""
             style="width:64px;margin-left:6px"> s</td></tr>
  <tr><td>Analogausgang 1</td><td>
      <input id="ao1feld" type="number" min="0" max="20000" step="100" style="width:84px"> &micro;A
      <button onclick="setzeAO(1)">setzen</button></td></tr>
  <tr><td>Analogausgang 2</td><td>
      <input id="ao2feld" type="number" min="0" max="20000" step="100" style="width:84px"> &micro;A
      <button onclick="setzeAO(2)">setzen</button></td></tr>
 </table>
</div>

<div class="karte"><h2>Verlauf (Welke-Kennwerte)</h2>
 <svg id="diagramm" viewBox="0 0 600 150" preserveAspectRatio="none"></svg>
 <div class="legende"><b style="color:#d99b00">&#9644;</b> Fl&auml;chenabfall [%] &nbsp;
  <b style="color:#d03b3b">&#9644;</b> Absinken [% Bildh&ouml;he] &nbsp;|&nbsp;
  gestrichelt: Gie&szlig;-Schwellen</div>
</div>

<div class="karte"><h2>Meldungen</h2><ul id="verlauf"></ul></div>

<script>
let daten=null, letzte_nr=-1;
function bildwechsel(){letzte_nr=-1;}
async function hole(){
 try{daten=await(await fetch('/daten')).json();}catch(e){setStatus(false,'Server weg');return;}
 setStatus(daten.verbunden, daten.verbunden?'verbunden mit '+daten.port:daten.meldung);
 const p=daten.pflanze;
 wasserlampe.className='lampe '+p.ampel;
 wasserstatus.textContent=p.status;
 wasserdetail.textContent='Gruenflaeche '+p.flaeche+' %  |  Schwerpunkt '+p.schwerpunkt+' %';
 referenzinfo.textContent=p.referenz_zeit?('Referenz vom '+p.referenz_zeit):'noch keine Referenz gesetzt';
 fl.textContent=p.flaeche+' %';
 sp.textContent=p.schwerpunkt+' %';
 fa.textContent=p.flaechen_abfall===null?'–':p.flaechen_abfall+' %';
 ab.textContent=p.absinken===null?'–':p.absinken+' %';
 he.textContent=p.helligkeit;
 nr.textContent=daten.bildnummer;
 gr.textContent=(daten.groesse/1024).toFixed(1)+' kB';
 da.textContent=daten.dauer+' s';
 wd.textContent=daten.wiederholungen; wg.textContent=daten.wiederholungen_gesamt;
 fb.textContent=daten.fehlbilder;
 const k=daten.kamera;
 kz.textContent=k?Math.floor(k.betrieb_s/3600)+' h '+Math.floor(k.betrieb_s%3600/60)+' min':'–';
 rs.textContent=k?k.rssi+' dBm':'–';
 hp.textContent=k?k.heap_kb+' kB':'–';
 blitzknopf.className=daten.blitz?'an':'';
 blitzknopf.textContent='Blitz '+(daten.blitz?'EIN':'aus');
 const lv=daten.live;
 if(!lv||!lv.moeglich){livekopf.textContent='keine USB-Kamera angeschlossen';}
 else if(lv.laeuft){livekopf.textContent=lv.geraet+'   '+lv.bildrate+' Bilder/s   '
   +lv.groesse_kb+' kB je Bild'+(lv.packt_selbst?'   (ffmpeg packt selbst)':'');}
 else{livekopf.textContent=lv.geraet?(lv.geraet+' bereit \u2013 '+lv.meldung):lv.meldung;}
 const io=daten.io;
 if(!io||!io.vorhanden){iokopf.textContent='kein Modul angeschlossen';}
 else if(!io.verbunden){iokopf.textContent='Stoerung: '+io.meldung;}
 else{
  iokopf.textContent='Modul '+io.version+' an '+io.geraet;
  ai1.textContent=io.ai_text[0]+'   ('+io.ai_bereich[0]+')';
  ai2.textContent=io.ai_text[1]+'   ('+io.ai_bereich[1]+')';
  dizeile.textContent='DI1 '+(io.di[0]?'EIN':'aus')+'   |   DI2 '+(io.di[1]?'EIN':'aus');
  rel1knopf.className=io.relais[0]?'an':'';
  rel1knopf.textContent='Relais 1 '+(io.relais[0]?'EIN':'aus');
  rel2text.textContent=io.giesst?'giesst gerade ...':(io.relais[1]?'EIN':'aus');
  const f1=document.getElementById('ao1feld'), f2=document.getElementById('ao2feld');
  if(document.activeElement!==f1) f1.value=io.ao[0];
  if(document.activeElement!==f2) f2.value=io.ao[1];
 }
 verlauf.innerHTML=daten.verlauf.map(z=>'<li>'+z+'</li>').join('');
 zeichne(daten.punkte);
 if(!daten.analyse_ok) setStatus(false,'numpy/Pillow fehlen - bitte installieren');
 if(document.activeElement!==document.getElementById('aufbstufe'))
  document.getElementById('aufbstufe').value=daten.aufbereitung;
 if(daten.bildnummer!==letzte_nr){
  letzte_nr=daten.bildnummer;
  document.getElementById('bild').src=(maskschalter.checked?'/maske.jpg':'/bild.jpg')
    +'?nr='+letzte_nr+'&a='+daten.aufbereitung;
 }
}
function zeichne(punkte){
 const svg=document.getElementById('diagramm'); if(!punkte.length){svg.innerHTML='';return;}
 const W=600,H=150,R=20;                      // Zeichenflaeche
 const maxy=Math.max(20, ...punkte.map(p=>Math.max(p[1],p[2])))*1.15;
 const t0=punkte[0][0], t1=punkte[punkte.length-1][0], dt=Math.max(1,t1-t0);
 const X=t=> R+(W-2*R)*(t-t0)/dt;
 const Y=v=> (H-R)-(H-2*R)*v/maxy;
 const linie=(i,farbe)=>{
  const d=punkte.map((p,k)=>(k?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[i]).toFixed(1)).join(' ');
  return '<path d="'+d+'" fill="none" stroke="'+farbe+'" stroke-width="1.6"/>';};
 const schwelle=(v,farbe)=>'<line x1="'+R+'" x2="'+(W-R)+'" y1="'+Y(v)+'" y2="'+Y(v)+
  '" stroke="'+farbe+'" stroke-dasharray="5 4" stroke-width="1"/>';
 svg.innerHTML=
  schwelle("""+str(ROT_FLAECHE)+r""",'#d99b00')+schwelle("""+str(ROT_ABSINKEN)+r""",'#d03b3b')+
  linie(1,'#d99b00')+linie(2,'#d03b3b')+
  '<text x="'+R+'" y="12" font-size="10" fill="#898781">max '+maxy.toFixed(0)+' %</text>';
}
function setStatus(an,text){lampe.className='punkt'+(an?' an':'');
 statustext.textContent=text;
 fehlerband.style.display=an?'none':'block';
 fehlerband.textContent=an?'':'Stoerung: '+text+' (naechster Versuch laeuft)';}
async function blitz(){if(!daten)return;
 await fetch('/blitz?ein='+(daten.blitz?0:1)); hole();}
async function setzeAufbereitung(){
 const s=document.getElementById('aufbstufe').value;
 await fetch('/aufbereitung?stufe='+s);
 letzte_nr=-1;                     // Bild sofort neu holen
 hole();}
function liveumschalten(){
 const b=document.getElementById('livebild');
 if(document.getElementById('liveschalter').checked){
  b.src='/live.mjpg?'+Date.now(); b.style.display='block';
 }else{ b.src=''; b.style.display='none'; }}
async function relais(nr){
 if(!daten||!daten.io||!daten.io.verbunden)return;
 const ein=daten.io.relais[nr-1]?0:1;
 const a=await(await fetch('/relais?nr='+nr+'&ein='+ein)).json();
 if(!a.ok)alert('Fehler: '+a.fehler);
 hole();}
async function setzeAO(k){
 const wert=document.getElementById('ao'+k+'feld').value;
 const a=await(await fetch('/ao?kanal='+k+'&wert='+wert)).json();
 if(!a.ok)alert('Fehler: '+a.fehler);
 hole();}
async function giessen(){
 const s=document.getElementById('gsek').value;
 if(!confirm('Relais 2 fuer '+s+' s einschalten?'))return;
 const a=await(await fetch('/giessen?sekunden='+s)).json();
 if(!a.ok)alert('Fehler: '+a.fehler);
 hole();}
async function referenz(){
 const a=await(await fetch('/referenz')).json();
 alert(a.ok?'Referenz gesetzt - die Pflanze gilt jetzt als frisch gegossen.':'Fehler: '+a.fehler);
 hole();}
hole(); setInterval(hole,3000);
</script></body></html>"""


def hole_anzeigebild():
    """Bild fuer die Anzeige, je nach eingestellter Aufbereitungsstufe.
    Das Ergebnis wird zwischengespeichert, damit nicht bei jedem Abruf
    neu gerechnet wird - auf einem Pi 3B+ kostet das sonst spuerbar Zeit."""
    global aufbereitet
    with datenschloss:
        stufe = zustand["aufbereitung"]
        nummer = zustand["bildnummer"]
        fertig = letztes_jpeg
        roh = letztes_original
        text = letzter_stempel
    if not stufe or not roh or not ANALYSE_MOEGLICH:
        return fertig
    if aufbereitet[0] == nummer and aufbereitet[1] == stufe:
        return aufbereitet[2]
    try:
        ergebnis = aufbereiten(roh, stufe, text)
    except Exception:
        return fertig
    aufbereitet = (nummer, stufe, ergebnis)
    return ergebnis


class Handler(BaseHTTPRequestHandler):
    def antwort(self, inhalt, typ="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(inhalt)

    def sende_livestrom(self):
        """Motion JPEG: eine Antwort, die nie endet, mit einem Bild nach dem
        anderen darin. Der Browser zeigt das in einem <img> ohne Zusatz an."""
        grenze = b"bildgrenze"
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=bildgrenze")
        self.end_headers()
        livecam.anmelden()
        nummer = 0
        try:
            while True:
                nummer, bild = livecam.naechstes_bild(nummer, 5.0)
                if not bild:
                    continue
                self.wfile.write(b"--" + grenze + b"\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(bild))
                self.wfile.write(bild)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                  # Zuschauer hat das Bild zugemacht
        finally:
            livecam.abmelden()

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self.antwort(SEITE.encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/daten":
                with datenschloss:
                    paket = dict(zustand)
                    paket["port"] = "%s:%d" % (ESP32CAM_IP, TCP_PORT)
                paket["io"] = (waveshare_io.kopie()
                               if MODUL_A_MOEGLICH and MODUL_A_AKTIV
                               else {"vorhanden": False})
                paket["live"] = (livecam.kopie()
                                 if LIVECAM_MOEGLICH and LIVECAM_AKTIV
                                 else {"moeglich": False,
                                       "meldung": "abgeschaltet"})
                self.antwort(json.dumps(paket).encode("utf-8"))
            elif url.path == "/bild.jpg":
                jpeg = hole_anzeigebild()
                if jpeg:
                    self.antwort(jpeg, "image/jpeg")
                else:
                    self.send_error(404)
            elif url.path == "/maske.jpg":
                with datenschloss:
                    jpeg = letzte_maske or letztes_jpeg
                if jpeg:
                    self.antwort(jpeg, "image/jpeg")
                else:
                    self.send_error(404)
            elif url.path == "/referenz":
                setze_referenz()
                self.antwort(b'{"ok":true}')
            elif url.path == "/live.mjpg":
                self.sende_livestrom()
            elif url.path == "/kamera2.jpg":
                jpeg = livecam.letztes_bild()
                if jpeg:
                    self.antwort(jpeg, "image/jpeg")
                else:
                    self.send_error(503, "noch kein Livebild")
            elif url.path == "/relais":
                q = parse_qs(url.query)
                waveshare_io.schalte_relais(int(q["nr"][0]), int(q["ein"][0]) != 0)
                self.antwort(b'{"ok":true}')
            elif url.path == "/ao":
                q = parse_qs(url.query)
                wert = waveshare_io.setze_ao(int(q["kanal"][0]), int(q["wert"][0]))
                self.antwort(json.dumps({"ok": True, "wert": wert}).encode("utf-8"))
            elif url.path == "/giessen":
                q = parse_qs(url.query)
                dauer = waveshare_io.giesse(int(q["sekunden"][0]))
                print("Giessen ausgeloest: %d s" % dauer)
                self.antwort(json.dumps({"ok": True, "sekunden": dauer}).encode("utf-8"))
            elif url.path == "/aufbereitung":
                q = parse_qs(url.query)
                stufe = max(0, min(3, int(q["stufe"][0])))
                with datenschloss:
                    zustand["aufbereitung"] = stufe
                self.antwort(json.dumps({"ok": True, "stufe": stufe}).encode("utf-8"))
            elif url.path == "/blitz":
                q = parse_qs(url.query)
                ein = int(q["ein"][0]) != 0
                schreibe_register(9, 1 if ein else 0)
                with datenschloss:
                    zustand["blitz"] = 1 if ein else 0
                self.antwort(b'{"ok":true}')
            else:
                self.send_error(404)
        except Exception as e:
            self.antwort(json.dumps({"ok": False, "fehler": str(e)}).encode("utf-8"))

    def log_message(self, *args):
        pass


def eigene_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 1)); return s.getsockname()[0]
    except OSError:
        return "localhost"
    finally:
        s.close()


def zustand_fuer_anzeige():
    """Kopie des Zustands fuer die OLED-Anzeige (haelt das Schloss kurz)."""
    with datenschloss:
        paket = dict(zustand)
        paket["pflanze"] = dict(zustand["pflanze"])
        paket["punkte"] = list(zustand["punkte"])
    return paket


def starte_modul_a():
    """Ein- und Ausgabemodul am RS485-Wandler. Fehlt es, laeuft der Waechter
    unveraendert weiter - die Klemmen sind Zugabe."""
    if not MODUL_A_AKTIV:
        return
    if not MODUL_A_MOEGLICH:
        print("Modul A: waveshare_io.py nicht gefunden - Ein-/Ausgaenge entfallen")
        return
    waveshare_io.starte()


def starte_livecam():
    """USB-Kamera fuer das Livebild. Fehlt sie, entfaellt nur diese Karte."""
    if not LIVECAM_AKTIV:
        return
    if not LIVECAM_MOEGLICH:
        print("Livekamera: livecam.py nicht gefunden - Livebild entfaellt")
        return
    livecam.starte()


def starte_oled():
    """Kleines Display vor Ort. Fehlt es oder ist I2C aus, laeuft das
    Programm unveraendert weiter - die Anzeige ist reine Zugabe."""
    if not OLED_AKTIV:
        return
    try:
        import oled_anzeige
    except ImportError:
        print("OLED: oled_anzeige.py nicht gefunden - Anzeige entfaellt")
        return
    oled_anzeige.starte(zustand_fuer_anzeige,
                        bus=OLED_BUS, adresse=OLED_ADRESSE,
                        treiber=OLED_TREIBER, kopfstehend=OLED_KOPFSTEHEND,
                        seitenzeit=OLED_SEITENZEIT)


def main():
    if not ANALYSE_MOEGLICH:
        print("HINWEIS: numpy/Pillow fehlen -> nur Bilduebertragung,")
        print("         keine Pflanzenauswertung.  pip install numpy pillow")
    with datenschloss:
        zustand["web"] = "%s:%d" % (eigene_ip(), WEB_PORT)
    starte_oled()
    starte_modul_a()
    starte_livecam()
    threading.Thread(target=abfrageschleife, daemon=True).start()
    server = ThreadingHTTPServer(("", WEB_PORT), Handler)
    print("Pflanzen-Dashboard laeuft:  http://localhost:%d" % WEB_PORT)
    print("  im Netz:                  http://%s:%d" % (eigene_ip(), WEB_PORT))
    print("  spricht ESP32-CAM auf %s:%d, alle %.0f min ein Bild" %
          (ESP32CAM_IP, TCP_PORT, INTERVALL / 60.0))
    print("Ablauf: Pflanze giessen -> im Dashboard 'Referenz setzen' ->")
    print("        der Waechter meldet, wenn die Blaetter haengen.")
    print("Beenden mit Strg+C.")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if sock:
            sock.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBeendet.")
