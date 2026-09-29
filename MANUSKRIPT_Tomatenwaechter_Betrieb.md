# Der Tomaten-Bewässerungswächter im Betrieb

Band 3: Regenschutz, Bildaufbereitung und Stromversorgung

Ralph Wystup, August 2026

---

## Einordnung

Die ersten beiden Bände beschreiben das Verfahren und das Gerät. Dieser dritte
handelt von dem, was danach kommt und in keiner Entwurfszeichnung steht: Regen,
der auf die Kamera fällt, und Strom, der nicht ausreicht.

Beide Themen haben eine Gemeinsamkeit, die sie lehrreich macht. Sie erzeugen
Fehlerbilder, die auf etwas ganz anderes hindeuten. Eine Folie vor dem Objektiv
sieht aus wie eine welkende Pflanze. Ein zu schwaches Netzteil sieht aus wie ein
Software- oder Netzwerkfehler. Wer die Zusammenhänge nicht kennt, sucht an der
falschen Stelle — und zwar lange.

---

## 1. Die Regenhaube

### 1.1 Was eine Folie mit dem Bild macht

Über die ESP32-CAM wurde bei Regen eine dünne, durchsichtige Tüte gezogen,
etwa drei Zentimeter vor dem Objektiv, unten offen. Das Bild wurde daraufhin
weich und kontrastarm, die Pflanze blieb aber erkennbar.

Der Grund ist nicht der Abstand, sondern die Beschaffenheit der Fläche. Zwei
Wirkungen überlagern sich:

Eine faltige Folie besteht aus lauter gekrümmten Flächen. Jede Krümmung wirkt
als kleine Linse mit eigener Brennweite und lenkt das Licht in eine andere
Richtung. Was das Objektiv erreicht, ist ein Gemisch aus Strahlen, die aus
verschiedenen Richtungen kommen — also ein verwaschenes Bild.

Dazu kommt Streulicht. Ein Teil des Lichts wird an der Folie diffus gestreut
und legt sich als gleichmäßiger Schleier über das ganze Bild. Die Schwärzen
werden angehoben, der Kontrast sinkt.

Daraus folgt die wichtigste Konstruktionsregel: **Entscheidend ist die
Ebenheit, nicht der Abstand.** Eine glatte, straff gespannte Fläche stört kaum,
selbst dicht vor der Linse — nach demselben Prinzip arbeitet jedes Schutzglas
vor einem Objektiv. Eine faltige Tüte stört auch aus zehn Zentimetern.

### 1.2 Warum Unschärfe der Auswertung wenig ausmacht

Die Pflanzenauswertung braucht keine Schärfe. Sie zählt Pixel, deren
Excess-Green-Index über einer Schwelle liegt:

$$ \mathrm{ExG} = 2G - R - B $$

Ein weiches Bild verschiebt lediglich die Ränder der Grünmaske um wenige
Pixel; die Fläche in der Mitte bleibt unverändert. Für Flächenanteil und
Schwerpunkt ist das nahezu belanglos.

Was dagegen sehr wohl wirkt, ist der Schleier. Streulicht ist annähernd
unbunt, es hebt also alle drei Farbkanäle um denselben Betrag $s$ an:

$$ \mathrm{ExG}' = 2(G+s) - (R+s) - (B+s) = \mathrm{ExG} $$

Rechnerisch bleibt der Index also gleich — solange die Streuung wirklich
unbunt ist und additiv wirkt. In der Wirklichkeit kommt jedoch hinzu, dass die
Kamera ihre Belichtung nachregelt und die Sättigung durch die Aufhellung
insgesamt sinkt: Die Farben rücken näher zusammen, $G-R$ und $G-B$ werden
kleiner, und damit sinkt ExG doch. Pixel, die vorher knapp über der Schwelle
lagen, fallen aus der Maske.

Die Folge ist heimtückisch: Die gemessene Grünfläche schrumpft, ohne dass sich
an der Pflanze etwas geändert hätte. Der Wächter deutet das als Welke.

Die zweite Gefahr ist Bewegung. Eine lose Tüte flattert im Wind, und damit
ändert sich die Streuung von Bild zu Bild. Für die Auswertung ist ein
gleichbleibend weiches Bild deutlich besser als ein mal scharfes, mal weiches —
Rauschen in den Messwerten ist schlimmer als ein systematischer Versatz, denn
den fängt die Referenz auf.

### 1.3 Was daraus folgt

Für den Aufbau, nach Wirksamkeit geordnet:

Ein starres, flaches Fenster ist die beste Lösung — ein Stück Acrylglas, das
Glas aus einem Bilderrahmen oder der Deckel einer CD-Hülle, rechtwinklig zur
Blickrichtung. Bequemer noch ist eine durchsichtige Dose, in der die Kamera
sitzt und deren glatte Wand als Fenster dient; das ist zugleich der bessere
Regenschutz, weil es formstabil ist.

Bleibt es bei der Folie, gehört sie straff und unbeweglich befestigt. Nicht
wegen der Schärfe, sondern wegen der Gleichmäßigkeit.

Die Haube sollte unten offen bleiben. Regen kommt von oben; die Öffnung unten
lässt warme, feuchte Luft entweichen und verhindert, dass sich beim Abkühlen
alles beschlägt. Ein Beutelchen Trockenmittel hilft zusätzlich. Ein leicht
geneigtes Fenster lässt Tropfen ablaufen, die sonst als helle Flecken die
Grünerkennung stören.

Für die Auswertung:

Fällt der gemessene Grünanteil durch die Haube deutlich ab, wird die Schwelle
`EXG_SCHWELLE` von 40 auf etwa 30 herabgesetzt. Prüfen lässt sich das, indem
man den Wert im Dashboard mit und ohne Haube vergleicht.

Und in jedem Fall gilt: **Nach jeder Änderung an der Optik muss die Referenz
neu gesetzt werden.** Sie ist der Maßstab, mit dem alle späteren Messungen
verglichen werden, und muss aus demselben Aufbau stammen. Eine Referenz von
vor dem Regen und Messwerte von nach dem Regen vergleichen zwei verschiedene
Kameras.

---

## 2. Die elektronische Bildaufbereitung

### 2.1 Was Rechnen kann und was nicht

Für die Anzeige — nicht für die Auswertung — lässt sich das weiche Bild
nachbessern. Die Grenze ist klar zu benennen: Rechnen kann nur betonen, was
noch im Bild steckt. Was die Streuung vernichtet hat, ist verloren; kein
Verfahren holt es zurück.

Zwei Schritte helfen trotzdem spürbar.

Die **Kontrastanhebung** wirkt gegen den Schleier. Sie spreizt die
Helligkeiten um einen festen Faktor um den Mittelwert herum, hebt also die
Unterschiede an, die die Streuung eingeebnet hat.

Die **Unschärfemaske** wirkt gegen die Weichheit. Ihr Prinzip ist eine
Subtraktion: Vom Bild wird eine verwischte Fassung seiner selbst abgezogen,
und die Differenz — das sind gerade die Kanten — wird verstärkt wieder
aufaddiert:

$$ B' = B + k\,\bigl(B - G_\sigma(B)\bigr) $$

Dabei ist $G_\sigma$ eine Glättung mit dem Radius $\sigma$ und $k$ die Stärke.
Der Name kommt daher, dass zur Schärfung ausgerechnet ein unscharfes Bild
gebraucht wird.

Im Dashboard sind vier Stufen wählbar, von `aus` bis `stark`:

| Stufe | Kontrastfaktor | Stärke | Radius |
|---|---|---|---|
| 1 sanft | 1,10 | 60 % | 1,2 |
| 2 mittel | 1,25 | 110 % | 1,6 |
| 3 stark | 1,45 | 180 % | 2,0 |

Die Vorgabe ist `aus`. Das Bild bleibt also unverändert, solange man es nicht
ausdrücklich anders einstellt.

### 2.2 Ein Fehlversuch als Lehrstück

Der erste Entwurf verwendete statt der begrenzten Kontrastanhebung eine volle
Kontrastspreizung, wie sie viele Bildbearbeitungen als „Autokontrast"
anbieten: Der genutzte Helligkeitsbereich wird auf den vollen Umfang von 0 bis
255 gedehnt.

Das Ergebnis war unbrauchbar. Der übliche Autokontrast dehnt jeden Farbkanal
für sich, und weil die Kanäle unterschiedlich weit reichen, verschieben sich
dabei die Farben. Aus brauner Erde wurde Magenta.

Der zweite Versuch mit tonwerterhaltender Spreizung behob das Farbkippen, doch
das Bild brannte aus: Die Dehnung bis an die Anschläge machte aus Blattgrün
Neongrün und aus Erde ein dunkles Rot. Der Grund ist, dass eine steile
Kennlinie die Unterschiede zwischen den Kanälen mitverstärkt und damit die
Sättigung hochtreibt.

Erst der dritte Ansatz taugte: ein fester, begrenzter Kontrastfaktor. Er kann
nicht ausreißen, weil er nicht vom Bildinhalt abhängt.

Die Lehre daraus ist allgemeiner Natur: Ein Verfahren, das sich selbst an den
Bildinhalt anpasst, verhält sich bei ungewöhnlichem Inhalt ungewöhnlich. Für
eine Anlage, die unbeaufsichtigt läuft und deren Bilder von Tageslicht,
Wetter und Jahreszeit abhängen, ist das Vorhersehbare dem Optimalen vorzuziehen.

### 2.3 Die Trennung von Anzeige und Auswertung

Die Aufbereitung wirkt ausschließlich auf das angezeigte Bild. Die
Pflanzenauswertung rechnet unverändert mit dem Originalbild der Kamera.

Diese Trennung ist keine Formsache. Würde die Auswertung auf dem aufbereiteten
Bild rechnen, hinge jeder Messwert davon ab, welche Stufe gerade eingestellt
ist — und ein Griff ins Dashboard würde die Messreihe unbrauchbar machen. Aus
demselben Grund wird auch der Zeitstempel erst nach der Auswertung ins Bild
gestempelt.

Technisch wird dafür das Originalbild getrennt vom Anzeigebild vorgehalten und
das aufbereitete Ergebnis nach Bildnummer und Stufe zwischengespeichert, damit
nicht bei jedem Abruf neu gerechnet wird.

---

## 3. Die Stromversorgung

### 3.1 Ein Fehlerbild, das in die Irre führt

Nach dem Anschluss der USB-Kamera trat folgendes auf: Das Dashboard war nicht
mehr erreichbar, SSH lief in eine Zeitüberschreitung — aber das OLED zeigte
weiterhin an, und die Uhr in seiner Kopfzeile lief. Ein Ping an den Pi wurde
beantwortet.

Diese Kombination wirkt widersprüchlich und ist es nicht. Ping beantwortet der
Betriebssystemkern selbst; dafür muss kein Programm laufen. Die Anzeige wird
von einem Faden bedient, der bereits läuft und nur wenig Rechenzeit braucht.
Was fehlschlug, war das Annehmen neuer Verbindungen — die aufwendigste dieser
drei Tätigkeiten.

Die Ursache war Unterspannung. Sinkt die Versorgung unter etwa 4,63 Volt,
drosselt der Pi seinen Takt; bei stärkeren Einbrüchen wird das System so zäh,
dass es neue Verbindungen nicht mehr in vertretbarer Zeit bedient. Nach außen
sieht das aus wie ein Netzwerk- oder Softwarefehler.

### 3.2 Der Beweis

Der Pi führt darüber Buch. Abzufragen mit:

```
vcgencmd get_throttled
```

Der zurückgegebene Wert ist ein Bitmuster. Die hinteren Stellen beschreiben
den Zustand von jetzt, die vorderen sind Merker seit dem Einschalten:

| Bit | Wert | Bedeutung |
|---|---|---|
| 0 | 0x1 | Unterspannung, jetzt |
| 1 | 0x2 | Takt begrenzt, jetzt |
| 2 | 0x4 | gedrosselt, jetzt |
| 3 | 0x8 | weiche Temperaturgrenze, jetzt |
| 16 | 0x10000 | Unterspannung ist vorgekommen |
| 17 | 0x20000 | Taktbegrenzung ist vorgekommen |
| 18 | 0x40000 | Drosselung ist vorgekommen |
| 19 | 0x80000 | Temperaturgrenze ist vorgekommen |

Gemessen wurde `throttled=0x50000`: Unterspannung und Drosselung waren
vorgekommen, aber nicht mehr aktuell. Damit war die Ursache belegt, ohne ein
Messgerät anzulegen.

Die Merker lassen sich nur durch einen Neustart zurücksetzen. Wer prüfen will,
ob eine Maßnahme geholfen hat, muss deshalb zuerst neu starten und dann unter
Last messen — sonst sieht er weiterhin den alten Eintrag.

### 3.3 Warum das Kabel wichtiger ist als das Netzteil

Der Spannungsabfall auf der Zuleitung ist der meistunterschätzte Anteil. Er
folgt schlicht dem ohmschen Gesetz, wobei Hin- und Rückleiter zählen:

$$ \Delta U = I \cdot 2 \cdot \frac{\rho\,l}{A} $$

Für ein Meter Kabel mit den üblichen dünnen Adern der Stärke 28 AWG beträgt
der Widerstand je Leiter rund 0,21 Ohm, zusammen also 0,43 Ohm. Bei 1,5 Ampere
ergibt das:

$$ \Delta U = 1{,}5\ \mathrm{A} \cdot 0{,}43\ \Omega \approx 0{,}64\ \mathrm{V} $$

Aus 5,2 Volt am Netzteil werden damit 4,56 Volt am Pi — unterhalb der
Erkennungsschwelle. Das Netzteil ist tadellos, das Gerät läuft trotzdem in
Unterspannung.

Mit einer kräftigen Ader von 20 AWG sinkt der Widerstand auf 0,033 Ohm je
Meter und Leiter, der Abfall bei denselben 1,5 Ampere auf etwa 0,1 Volt. Der
Unterschied zwischen brauchbar und unbrauchbar liegt also allein im Kabel.

Praktische Folgerung: kurz und dick. Und im Zweifel am Pi messen, nicht am
Netzteil.

### 3.4 Die Auslegung

Angeschlossen wurde ein Netzteil mit 5,2 Volt Klemmenspannung und 5 Ampere.

Zur Stromstärke: Reserve schadet nicht. Ein Netzteil drückt keinen Strom in
das Gerät, es stellt ihn bereit; der Pi nimmt sich, was er braucht. Der Nutzen
der Reserve liegt darin, dass die Spannung bei Lastspitzen nicht einbricht,
weil das Netzteil weit von seiner Grenze entfernt arbeitet.

Zur Spannung: Der Pi ist auf 5 Volt mit ±5 Prozent ausgelegt, also 4,75 bis
5,25 Volt. Die 5,2 Volt liegen innerhalb und gleichen zugleich den Abfall auf
der Leitung aus — aus demselben Grund liefert das Originalnetzteil 5,1 Volt
statt 5,0. Nach oben ist bei 5,25 Volt am Gerät Schluss; einen
Überspannungsschutz gibt es nicht, und angeschlossene USB-Geräte vertragen
ebenfalls nur 5 Volt ±5 Prozent.

Wer über eine einstellbare Quelle einspeist, stellt nicht nach Gefühl ein,
sondern misst am Pi unter Last. An der Klemme über 5,5 Volt zu gehen ist auch
dann nicht vertretbar, denn beim Wegfall der Last liegt diese Spannung
ungedämpft am Gerät an.

Ein Hinweis zur Einspeisung über die Stiftleiste: Wer die 5 Volt an Pin 2 oder
4 legt, umgeht die Sicherung und den Verpolungsschutz der Micro-USB-Buchse.
Mechanisch bequem, im Fehlerfall tödlich für die Platine.

### 3.5 Das Ergebnis

Nach dem Wechsel wurde neu gestartet und unter Last geprüft — Livebild
eingeschaltet und alle vier Rechenkerne beschäftigt:

| Messung | Wert |
|---|---|
| direkt nach dem Start | `throttled=0x0` |
| unter voller Last | `throttled=0x80008` |
| Temperatur dabei | 61,2 °C |

Die Unterspannungsbits sind verschwunden. Was übrig bleibt, ist Bit 3 und sein
Merker Bit 19: die weiche Temperaturgrenze. Der Pi 3B+ nimmt oberhalb von etwa
60 Grad den Takt geringfügig zurück, von 1,4 auf 1,2 GHz. Das ist vorgesehenes
Verhalten und für diese Anlage bedeutungslos — ernsthaft gedrosselt wird erst
ab 80 Grad, und die künstliche Volllast liegt weit über allem, was im Betrieb
auftritt. Der Wächter holt alle fünf Minuten ein Bild und ruht dazwischen.

Nebenbei ist damit auch die Speicherkarte sicherer: Unterspannung ist eine der
häufigsten Ursachen für beschädigte Dateisysteme.

---

## 4. Prüfliste

Bei jedem unerklärlichen Verhalten des Geräts zuerst diese drei Fragen:

Läuft die Uhr auf dem Display? Dann arbeitet das Programm, und das Problem
liegt im Netz oder in der Versorgung.

Was sagt `vcgencmd get_throttled`? Alles außer `0x0` weist auf Strom oder
Wärme. Endet der Wert auf 1, 4 oder 5, ist es die Versorgung.

Was sagt `ping` auf den Pi? Antwortet er, während SSH nicht durchkommt, ist
das kein Netzwerkfehler, sondern ein überlastetes oder unterversorgtes Gerät.

Bei jeder Änderung an der Optik der Kamera — Haube, Ausrichtung, Reinigung —
gehört anschließend die Referenz neu gesetzt.
