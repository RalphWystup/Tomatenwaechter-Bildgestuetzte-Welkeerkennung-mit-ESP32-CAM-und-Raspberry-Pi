# Prüfplan — Seite „Tomatenwächter“ (Fassung 1.0, 29.09.2026)

Prof. Dr.-Ing. Ralph Wystup M.Sc. — erstellt mit KI und Agent (Claude Code, Anthropic)

Die Seite trägt die Auswertung des Wächters (`pflanzen_dashboard.py`: Excess-Green-Maske, Grünfläche, Schwerpunkt, Median über fünf Bilder, Ampelschwellen 8/15 % und 2/4 %, Nachtgrenze 40, Mindestfläche 2 %) als JavaScript an einer gezeichneten Pflanze, die drei Displayseiten, einen Tag im Zeitraffer mit Solarabschaltung und die fünf Dokumente als Dokumentation. Die Bewertungstexte sind wörtlich die des Geräts. Jede Zeile hat eine Schranke.

| Nr. | Kriterium | Prüfmittel | Schranke | Ergebnis |
|:--|:--|:--|:--|:--|
| T1 | keine Konsolenfehler | `pruefe_seite.mjs` (Playwright, Chromium) | keine | ok |
| T2 | Werkzeug vor Text: Knopf bei 233 px | `pruefe_seite.mjs` (Playwright, Chromium) | erster Knopf oberhalb 400 px | ok |
| T3 | nach Gießen und Referenz: gruen, ΔA 0 %, Δy 0 % | `pruefe_seite.mjs` (Playwright, Chromium) | grün, ΔA = Δy = 0 | ok |
| T4 | Defizit 0,30 (Median über 5 Bilder): rot, ΔA 16.6 %, Δy 2.2 % — Status „GIESSEN! Blaetter haengen deutlich“ | `pruefe_seite.mjs` (Playwright, Chromium) | rot (ΔA ≥ 15 %) | ok |
| T5 | Defizit 0,70 (Median über 5 Bilder): rot, ΔA 40.1 %, Δy 4.7 % — „GIESSEN! Blaetter haengen deutlich“ | `pruefe_seite.mjs` (Playwright, Chromium) | rot | ok |
| T6 | Licht 0,05: grau — „zu dunkel fuer Auswertung (Nacht?)“ | `pruefe_seite.mjs` (Playwright, Chromium) | grau, Text „zu dunkel“ | ok |
| T7 | Tag im Zeitraffer: 288 Bilder, Ereignisse: Kamera stromlos (Akku 10 %) | Kamera wieder an — Neustart erkannt (Betriebszeit springt zurück) | Referenz gesetzt (erstes helles Bild nach 8:00) | gegossen (18:00) | `pruefe_seite.mjs` (Playwright, Chromium) | 288 Bilder, Ereignisse: stromlos, wieder an, Referenz, gegossen | ok |
| T8 | Ampel im Tag: rot 35, gelb 19, grün 35, grau 199 | `pruefe_seite.mjs` (Playwright, Chromium) | rot, gelb, grün und grau je > 0 | ok |
| T9 | Display-Seite 1 gezeichnet (6397 helle Bildpunkte) | `pruefe_seite.mjs` (Playwright, Chromium) | > 500 helle Bildpunkte | ok |
| T10 | Dokumentation: Band 1 bis 3 und Anleitungen in der Seite | `pruefe_seite.mjs` (Playwright, Chromium) | vorhanden, keine Heimnetzadresse, kein Netzname | ok |
| T11 | Dokumentation neutralisiert: keine Heimnetzadresse, kein WLAN-Name, kein Kennwortwert | `pruefe_seite.mjs` (Playwright, Chromium) | vorhanden, keine Heimnetzadresse, kein Netzname | ok |
| T12 | Kopf: Fassung 1.0 · 29.09.2026 · Prof. Dr.-Ing. Ralph Wystup M.Sc. | `pruefe_seite.mjs` (Playwright, Chromium) | Fassung, Datum, Name | ok |

Stand: 2026-09-29T17:11 · 0 Beanstandung(en). Bildschirmfotos angesehen (Kamerabild und Maske, Display-Seiten, Tagesverlauf mit Akku, Licht, ΔA, Δy und Ampelleiste; Ereignisse 02:20 stromlos, 11:00 wieder an und Referenz, 18:00 gegossen).
