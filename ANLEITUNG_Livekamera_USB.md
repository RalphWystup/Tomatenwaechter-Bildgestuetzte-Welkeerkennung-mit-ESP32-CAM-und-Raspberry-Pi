# Umgebungskamera am Tomatenwächter

Eine gewöhnliche USB-Webcam am Raspberry Pi liefert ein flüssiges Livebild der
Umgebung. Eigenständige Anleitung; die übrigen Unterlagen werden nicht
gebraucht.

Stand 19.08.2026, eingerichtet und in Betrieb.

---

## 1. Wozu

Die ESP32-CAM beobachtet die Pflanze und liefert alle fünf Minuten ein
Einzelbild — sie ist solarbetrieben, funkt über WLAN und ist auf Sparsamkeit
ausgelegt, nicht auf Bewegtbild.

Für den Blick in die Umgebung ist das zu wenig: Steht die Gießkanne noch da,
läuft Wasser, ist jemand im Gewächshaus, hat der Wind etwas umgeworfen? Dafür
hängt eine USB-Webcam unmittelbar am Pi und zeigt ein Livebild im selben
Dashboard.

Beide Kameras stören einander nicht. Die Pflanzenauswertung arbeitet
unverändert mit den Bildern der ESP32-CAM.

---

## 2. Wie es funktioniert

Der entscheidende Kunstgriff heißt: nichts anfassen.

Fast jede USB-Kamera kann ihre Bilder bereits fertig gepackt als JPEG liefern,
im Format `MJPG`. Diese Bilder werden nicht entpackt und nicht neu gepackt,
sondern unverändert an den Browser durchgereicht. Der Pi sortiert nur Bytes,
und die Rechenlast bleibt vernachlässigbar — auf einem 3B+ mit 1 GB ist das
der Unterschied zwischen flüssig und unbrauchbar.

Beherrscht eine Kamera kein MJPG, packt `ffmpeg` die Bilder selbst. Das
funktioniert ebenfalls, kostet aber deutlich Rechenzeit. Das Programm merkt
das selbst und zeigt es im Dashboard an.

Übertragen wird als „motion JPEG": eine HTTP-Antwort, die nie endet und in der
ein Bild nach dem anderen steht. Jeder Browser stellt das ohne Zusatzsoftware
dar, es genügt ein Bildelement auf der Seite.

Der Datenstrom läuft nur, solange jemand zusieht. Wird das Häkchen im Dashboard
entfernt oder die Seite geschlossen, schaltet sich die Kamera nach zehn
Sekunden Nachlauf wieder ab. Das spart Rechenzeit, Strom und bei Mobilfunk
Datenvolumen.

---

## 3. Voraussetzungen

Auf dem Pi:

```
sudo apt install -y ffmpeg v4l-utils
```

Die Datei `livecam.py` gehört nach `/home/pi/tomate`, und `pflanzen_dashboard.py`
muss die Fassung mit der Kamerakarte sein. Nach dem Kopieren:

```
sudo systemctl restart pflanzen_waechter
```

Eine USB-Webcam beliebiger Herkunft genügt. Sie zieht bis zu 500 mA aus dem
USB-Anschluss — zusammen mit dem RS485-Wandler ist ein Netzteil mit 2,5 A
angebracht.

---

## 4. Kamera prüfen

Welche Videogeräte gibt es?

```
v4l2-ctl --list-devices
```

Der Raspberry Pi meldet ein gutes Dutzend, von denen die meisten interne
Bausteine sind: `bcm2835-codec` für das Kodieren, `bcm2835-isp` für die
Bildverarbeitung. Gesucht ist der Eintrag mit dem Namen der Kamera. Das
Programm siebt die internen Geräte selbst aus.

Was kann sie?

```
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Gesucht ist `MJPG` und darunter die Auflösungen mit ihren Bildraten. Die hier
verwendete „HD USB Camera" kann in MJPG:

| Auflösung | Bilder je Sekunde |
|---|---|
| 320×240, 640×480, 800×600, 1024×768 | 30 |
| 1280×960, 1600×1200, 2048×1536 | 15 |
| 2592×1944, 3264×2448 | 15 |

---

## 5. Einstellungen

Oben in `livecam.py`:

| Größe | Bedeutung |
|---|---|
| `GERAET` | `None` = erste echte Kamera nehmen, sonst z.B. `"/dev/video0"` |
| `BREITE`, `HOEHE` | Auflösung, Vorgabe 800 × 600 |
| `BILDRATE` | angeforderte Bilder je Sekunde, Vorgabe 15 |
| `QUALITAET` | nur wenn ffmpeg selbst packen muss: 2 (gut) bis 15 (grob) |
| `NACHLAUF` | Sekunden Weiterlauf nach dem letzten Zuschauer |

Nach jeder Änderung `sudo systemctl restart pflanzen_waechter`.

Zur Wahl der Auflösung: Sie kostet keine Rechenzeit, weil die Bilder ja nur
durchgereicht werden — sie kostet Datenmenge. Als Anhaltspunkt liefert
800 × 600 rund 25 bis 30 kB je Bild, bei 15 Bildern je Sekunde also etwa
400 kB/s oder 3 Mbit/s. Im WLAN ist das belanglos, über Mobilfunk merklich.
Wer von unterwegs zusieht, fährt mit 640 × 480 sparsamer.

---

## 6. Bedienung

Im Dashboard gibt es die Karte `Umgebungskamera` mit einem Häkchen
`Livebild einschalten`. Es ist bewusst nicht von selbst eingeschaltet, damit
nicht jeder Seitenaufruf ungefragt einen Datenstrom auslöst.

Über der Bildfläche steht der Zustand: Gerätename, tatsächliche Bildrate und
Größe je Bild. Erscheint dort der Zusatz „ffmpeg packt selbst", liefert die
Kamera kein MJPG und die Rechenlast ist deutlich höher.

Ein Einzelbild ohne Datenstrom gibt es unter:

```
http://<IP-des-Pi>:8083/kamera2.jpg
```

Das eignet sich für schnelle Blicke von unterwegs oder um es in andere Seiten
einzubinden.

---

## 7. Wenn etwas nicht geht

Die Karte meldet „keine USB-Kamera angeschlossen": Prüfen mit `ls /dev/video*`
und `lsusb`. Wurde die Kamera erst nach dem Programmstart angesteckt, muss der
Dienst neu gestartet werden — er sucht die Kamera nur beim Start.

Es kommt kein Bild, obwohl die Kamera erkannt wird: Auf dem Pi den Dienst
anhalten und die Kamera einzeln prüfen:

```
sudo systemctl stop pflanzen_waechter
python3 ~/tomate/livecam.py
sudo systemctl start pflanzen_waechter
```

Das Programm nimmt fünf Sekunden auf und zählt die Bilder. Dabei zeigt es auch,
ob ffmpeg selbst packen musste.

Das Bild ruckelt: Auflösung oder Bildrate verringern. Über Mobilfunk ist die
Leitung der Engpass, nicht der Pi.

Der Zusatz „ffmpeg packt selbst" erscheint, obwohl die Kamera MJPG kann: Dann
passt die eingestellte Kombination aus Auflösung und Bildrate nicht zu dem, was
die Kamera in MJPG anbietet. Die Liste aus Abschnitt 4 heranziehen und eine
dort aufgeführte Auflösung eintragen.

Zwei Programme gleichzeitig gehen nicht: Eine Kamera lässt sich nur von einem
Programm öffnen. Solange der Dienst läuft und jemand zusieht, ist sie belegt.

---

## 8. Zur Beachtung

Das Dashboard hat keine Anmeldung. Wer es erreicht, sieht auch das Livebild.
Erreichbar ist es für alle Geräte im Heimnetz und, sofern eingerichtet, über
den Fernzugriff.

Bei einer Kamera wiegt das schwerer als bei Messwerten. Wenn sie einen Bereich
zeigt, in dem sich Menschen aufhalten, gehört das bedacht — und spätestens dann
eine Anmeldung vor die Seite.
