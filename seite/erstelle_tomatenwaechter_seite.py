#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""erstelle_tomatenwaechter_seite.py — die Seite „Tomatenwächter“ (Fassung aus VERSION): eine HTML mit Simulation und
eingebauter Dokumentation (Vorgabe des Verfassers vom 29.09.2026).

  * Simulation: eine gezeichnete Tomatenpflanze über Erde, deren Blätter mit dem Wasserdefizit hängen und kleiner werden;
    Licht, Wind (Bewegung), Folie (Unschärfe) einstellbar. Darauf läuft die Auswertung des Wächters Zeile für Zeile wie in
    pflanzen_dashboard.py: Excess-Green-Maske (2G − R − B > 40 und G > 60), Grünfläche, Schwerpunkt, Helligkeit, Median der
    letzten fünf Messungen, Vergleich mit der Referenz, Ampel (Schwellen 8/15 % Fläche, 2/4 % Absinken), die Texte des
    Programms. „Referenz setzen“ wie im Dashboard. Ein Tag im Zeitraffer (288 Bilder à 5 min) mit Tageslicht, wachsendem
    Defizit, Referenz, Gießen und der Solarabschaltung der Kamera (aus bei 10 %, an bei 50 % Akku); Verlaufsbild wie im Dashboard.
  * Display: die drei Seiten des OLED (128 × 64) aus dem Zustand gezeichnet, Layout wie oled_anzeige.py.
  * Dokumentation: Band 1 bis 3, Anleitung Raspberry Pi mit Display, Anleitung Umgebungskamera — Netzadressen und
    Zugangsdaten sind in der eingebetteten Fassung durch Platzhalter ersetzt (dieselbe Regel wie in der Ausfuhr).
Aufruf: python3 Seite/erstelle_tomatenwaechter_seite.py   → Seite/Tomatenwaechter_<VERSION>.html
"""
from __future__ import annotations
import base64, json, re, subprocess
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
D = P / "Aktuelle Daten"
VERSION = (H / "VERSION").read_text(encoding="utf-8").strip()
DATUM = "29.09.2026"
NAMENSNENNUNG = "Prof. Dr.-Ing. Ralph Wystup M.Sc. — erstellt mit KI und Agent (Claude Code, Anthropic)"
ZIEL = H / f"Tomatenwaechter_{VERSION}.html"

# Eine Regel je Ersetzung, nur in den Kopien (Arbeitsbereich bleibt unverändert). Gilt für Seite und Ausfuhr gleich.
NEUTRAL = [
    (r"192\.168\.178\.134", "<IP-des-Pi>"), (r"192\.168\.178\.117", "<IP-des-Gateways>"), (r"192\.168\.178\.55", "<IP-des-Pi>"),
    (r"192\.168\.178\.", "192.168.x."),
]
# Netzname und Kennwortwert des Aufbaus stehen nur in neutral_privat.json (nicht in der Ausfuhr), damit sie nicht im
# veröffentlichten Erzeuger selbst stehen; fehlt die Datei, gelten nur die Regeln oben.
if (H / "neutral_privat.json").is_file():
    NEUTRAL += [(re.escape(m), e) for m, e in json.loads((H / "neutral_privat.json").read_text(encoding="utf-8"))]


def neutral(text: str) -> str:
    for m, e in NEUTRAL: text = re.sub(m, e, text)
    return text


def daten_uri(pfad: Path) -> str:
    typ = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}[pfad.suffix.lower().lstrip(".")]
    return f"data:{typ};base64," + base64.b64encode(pfad.read_bytes()).decode()


DOKUMENTE = [("MANUSKRIPT_Tomatenwaechter.md", "Band 1 — Verfahren, Protokoll, Bildauswertung, Bedienung"),
             ("MANUSKRIPT_Tomatenwaechter_Pi.md", "Band 2 — vom Programm zum Gerät: Raspberry Pi, Display, RS485-Klemmenebene"),
             ("MANUSKRIPT_Tomatenwaechter_Betrieb.md", "Band 3 — Betrieb: Regenschutz, Bildaufbereitung, Stromversorgung"),
             ("ANLEITUNG_Pi_OLED.md", "Anleitung — Aufbau, Installation, Betrieb, Fehlersuche, Wiederaufbau"),
             ("ANLEITUNG_Livekamera_USB.md", "Anleitung — Umgebungskamera (USB) als Livebild")]


def dokument_html(name: str) -> str:
    md = neutral((D / name).read_text(encoding="utf-8"))
    kopf = re.match(r"---\n(.*?)\n---\n", md, re.S); md = md[kopf.end():] if kopf else md
    md = md.replace("\\newpage", "")
    return subprocess.run(["pandoc", "-f", "markdown", "-t", "html", "--mathml"], input=md, capture_output=True, text=True, check=True).stdout


SEITE_JS = r"""
// ---------------------------------------------------------------- Einstellungen des Wächters (Zeile für Zeile pflanzen_dashboard.py)
const EXG_SCHWELLE = 40, MIN_GRUEN = 60, MIN_FLAECHE = 2.0, MIN_HELLIGKEIT = 40, GELB_FLAECHE = 8.0, ROT_FLAECHE = 15.0, GELB_ABSINKEN = 2.0, ROT_ABSINKEN = 4.0, GLAETTUNG = 5;
const STUFEN = { 0: null, 1: [1.10, 60, 1.2], 2: [1.25, 110, 1.6], 3: [1.45, 180, 2.0] };
const SIM = { w: 480, h: 360 };
let referenz = null, messPuffer = [], zufallSaat = 11;
function zufall(saat) { let s = saat >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }

// ---------------------------------------------------------------- die gezeichnete Pflanze
// defizit 0 … 1: Blätter hängen (Winkel nach unten), werden kleiner und gelblicher; licht 0 … 1; wind: Zufallsbewegung; folie: Unschärfe
function pflanzeZeichnen(ctx, p, saat) {
  const { w, h } = SIM, zf = zufall(saat); ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  // Erde und Topf
  const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, '#6b4a34'); g.addColorStop(1, '#4e3423'); ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  for (let k = 0; k < 900; k++) { ctx.fillStyle = `rgba(${40 + zf() * 60 | 0},${25 + zf() * 40 | 0},${15 + zf() * 25 | 0},0.6)`; ctx.fillRect(zf() * w, zf() * h, 3 + zf() * 5, 2 + zf() * 4); }
  ctx.fillStyle = '#8a4b2c'; ctx.beginPath(); ctx.ellipse(w / 2, h - 30, 130, 26, 0, 0, 2 * Math.PI); ctx.fill();
  // Stängel und Blätter: sechs Triebe, je 5 Blätter; Hängen = Winkel um bis zu 55° nach unten, Fläche bis −40 %
  const triebe = 6, wind = (zf() - 0.5) * 2 * p.wind * 8;
  for (let tI = 0; tI < triebe; tI++) {
    const x0 = w / 2 + (tI - (triebe - 1) / 2) * 34 + wind, y0 = h - 40, hoehe = 200 - 20 * Math.abs(tI - (triebe - 1) / 2) - 40 * p.defizit;
    ctx.strokeStyle = '#3d6b2a'; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.quadraticCurveTo(x0 + wind, y0 - hoehe / 2, x0 + wind * 1.5, y0 - hoehe); ctx.stroke();
    for (let bI = 0; bI < 5; bI++) {
      const s = (bI + 1) / 5, bx = x0 + wind * s, by = y0 - hoehe * s, seite = bI % 2 ? 1 : -1;
      const haeng = p.defizit * 55 * Math.PI / 180, basis = -0.35 * Math.PI, a = seite * (basis) + (seite > 0 ? haeng : -haeng) * 0.0 ; // Blattrichtung
      const laenge = (34 - 6 * bI) * (1 - 0.4 * p.defizit), breite = (16 - 2 * bI) * (1 - 0.35 * p.defizit);
      const richtung = seite * 0.9 - (seite) * 0 + 0; const ang = seite > 0 ? (-0.35 + haeng) : (Math.PI + 0.35 - haeng);
      const gr = 120 - 40 * p.defizit + zf() * 25, rt = 40 + 70 * p.defizit + zf() * 20, bl = 30 + zf() * 20;
      ctx.fillStyle = `rgb(${rt | 0},${gr | 0},${bl | 0})`; ctx.save(); ctx.translate(bx, by); ctx.rotate(ang);
      ctx.beginPath(); ctx.ellipse(laenge / 2, 0, laenge / 2, breite / 2, 0, 0, 2 * Math.PI); ctx.fill();
      ctx.strokeStyle = `rgb(${rt * 0.6 | 0},${gr * 0.6 | 0},${bl * 0.6 | 0})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(laenge, 0); ctx.stroke(); ctx.restore();
    }
  }
  ctx.restore();
  // Folie (Unschärfe) und Licht
  const img = ctx.getImageData(0, 0, w, h), d = img.data;
  if (p.folie > 0) { const r = Math.round(1 + 3 * p.folie); boxblur(d, w, h, r); }
  const licht = 0.15 + 0.95 * p.licht;
  for (let i = 0; i < d.length; i += 4) { d[i] = Math.min(255, d[i] * licht); d[i + 1] = Math.min(255, d[i + 1] * licht); d[i + 2] = Math.min(255, d[i + 2] * licht); }
  ctx.putImageData(img, 0, 0);
}
function boxblur(d, w, h, r) {
  const t = new Uint8ClampedArray(d.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let s = [0, 0, 0], n = 0; for (let k = -r; k <= r; k++) { const xx = Math.min(w - 1, Math.max(0, x + k)), i = 4 * (y * w + xx); s[0] += d[i]; s[1] += d[i + 1]; s[2] += d[i + 2]; n++; } const o = 4 * (y * w + x); t[o] = s[0] / n; t[o + 1] = s[1] / n; t[o + 2] = s[2] / n; t[o + 3] = 255; }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let s = [0, 0, 0], n = 0; for (let k = -r; k <= r; k++) { const yy = Math.min(h - 1, Math.max(0, y + k)), i = 4 * (yy * w + x); s[0] += t[i]; s[1] += t[i + 1]; s[2] += t[i + 2]; n++; } const o = 4 * (y * w + x); d[o] = s[0] / n; d[o + 1] = s[1] / n; d[o + 2] = s[2] / n; }
}

// ---------------------------------------------------------------- die Auswertung des Wächters
function analysiere(d, w, h) {                     // gruenmaske + analysiere aus pflanzen_dashboard.py
  let summe = 0, treffer = 0, gewSumme = 0, gewY = 0; const maske = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) { let zeile = 0; for (let x = 0; x < w; x++) { const i = 4 * (y * w + x), R = d[i], G = d[i + 1], B = d[i + 2]; summe += R + G + B; if (2 * G - R - B > EXG_SCHWELLE && G > MIN_GRUEN) { maske[y * w + x] = 1; zeile++; } } treffer += zeile; gewSumme += zeile; gewY += y * zeile; }
  const flaeche = 100 * treffer / (w * h), schwerpunkt = gewSumme > 0 ? 100 * (gewY / gewSumme) / h : 0, helligkeit = summe / (3 * w * h);
  return { flaeche: +flaeche.toFixed(2), schwerpunkt: +schwerpunkt.toFixed(2), helligkeit: +helligkeit.toFixed(1), maske };
}
function bewerte(k) {                               // bewerte() aus pflanzen_dashboard.py, mit denselben Texten
  const p = Object.assign({}, k, { flaechen_abfall: null, absinken: null, referenz_zeit: referenz ? referenz.zeit : null });
  if (k.helligkeit < MIN_HELLIGKEIT) { p.status = 'zu dunkel fuer Auswertung (Nacht?)'; p.ampel = 'grau'; return p; }
  if (k.flaeche < MIN_FLAECHE) { p.status = `Pflanze nicht erkannt (Gruenanteil ${k.flaeche.toFixed(1)} %)`; p.ampel = 'grau'; return p; }
  if (!referenz) { p.status = 'Referenz fehlt - nach dem Giessen setzen!'; p.ampel = 'grau'; return p; }
  messPuffer = messPuffer.concat([[k.flaeche, k.schwerpunkt]]).slice(-GLAETTUNG);
  const fl = messPuffer.map(m => m[0]).sort((a, b) => a - b)[messPuffer.length >> 1], sp = messPuffer.map(m => m[1]).sort((a, b) => a - b)[messPuffer.length >> 1];
  const abfall = Math.max(0, 100 * (1 - fl / referenz.flaeche)), absinken = Math.max(0, sp - referenz.schwerpunkt);
  p.flaechen_abfall = +abfall.toFixed(1); p.absinken = +absinken.toFixed(1);
  if (abfall >= ROT_FLAECHE || absinken >= ROT_ABSINKEN) { p.status = 'GIESSEN! Blaetter haengen deutlich'; p.ampel = 'rot'; }
  else if (abfall >= GELB_FLAECHE || absinken >= GELB_ABSINKEN) { p.status = 'beobachten - Pflanze wird schlapp'; p.ampel = 'gelb'; }
  else { p.status = 'Wasser ausreichend'; p.ampel = 'gruen'; }
  return p;
}
function kontrollbild(ctx, d, maske, w, h) {        // Pflanze farbig, Rest abgedunkelt (× 0,25)
  const img = ctx.createImageData(w, h); for (let i = 0; i < w * h; i++) { const f = maske[i] ? 1 : 0.25; img.data[4 * i] = d[4 * i] * f; img.data[4 * i + 1] = d[4 * i + 1] * f; img.data[4 * i + 2] = d[4 * i + 2] * f; img.data[4 * i + 3] = 255; }
  ctx.putImageData(img, 0, 0);
}
function aufbereiten(ctx, d, w, h, stufe) {         // Anzeige-Aufbereitung wie im Dashboard: begrenzter Kontrastfaktor + Unschärfemaske (Stärke %, Radius)
  const s = STUFEN[stufe]; const img = ctx.createImageData(w, h); const o = img.data;
  if (!s) { o.set(d); ctx.putImageData(img, 0, 0); return; }
  const [kontrast, staerke, radius] = s; const weich = new Uint8ClampedArray(d); boxblur(weich, w, h, Math.round(radius));
  for (let i = 0; i < d.length; i += 4) for (let c = 0; c < 3; c++) { let v = d[i + c] + (d[i + c] - weich[i + c]) * staerke / 100; v = 128 + (v - 128) * kontrast; o[i + c] = Math.min(255, Math.max(0, v)); }
  for (let i = 3; i < o.length; i += 4) o[i] = 255; ctx.putImageData(img, 0, 0);
}

// ---------------------------------------------------------------- OLED 128 × 64, Layout wie oled_anzeige.py
function oledSeite(canvas, nummer, zustand) {
  const W = 128, Hh = 64; canvas.width = W * 3; canvas.height = Hh * 3; const c = canvas.getContext('2d'); c.setTransform(3, 0, 0, 3, 0, 0); c.imageSmoothingEnabled = false;
  c.fillStyle = '#000'; c.fillRect(0, 0, W, Hh); c.fillStyle = '#fff'; c.strokeStyle = '#fff'; c.lineWidth = 1;
  const text = (x, y, t, px, invers) => { c.font = `${px}px "DejaVu Sans", sans-serif`; c.textBaseline = 'top'; if (invers) { const b = c.measureText(t).width; c.fillRect(x - 2, y - 1, b + 4, px + 3); c.fillStyle = '#000'; c.fillText(t, x, y); c.fillStyle = '#fff'; } else c.fillText(t, x, y); };
  const breite = (t, px) => { c.font = `${px}px "DejaVu Sans", sans-serif`; return c.measureText(t).width; };
  const kopf = (titel, gestoert) => { text(0, 0, titel, 8); const uhr = zustand.uhr || '12:00'; text(W - breite(uhr, 8), 0, uhr, 8); if (gestoert) text(W / 2 - 4, 0, '(!)', 7); c.fillRect(0, 10, W, 1); };
  const p = zustand.pflanze || {}, gestoert = !zustand.verbunden;
  if (nummer === 0) {
    kopf('Tomate', gestoert);
    const lage = p.ampel === 'rot' ? ['GIESSEN!', true] : p.ampel === 'gelb' ? ['bald giessen', false] : p.ampel === 'gruen' ? ['Wasser ok', false]
      : (p.status || '').includes('dunkel') ? ['Nacht', false] : (p.status || '').includes('Referenz') ? ['keine Referenz', false] : (p.status || '').includes('nicht erkannt') ? ['keine Pflanze', false] : ['wartet ...', false];
    let px = 16; while (px > 8 && breite(lage[0], px) > W - 4) px -= 2; const bw = breite(lage[0], px); text((W - bw) / 2, 12 + (20 - px) / 2, lage[0], px, lage[1]);
    const wert = (x, n = 1) => x === null || x === undefined ? '--' : x.toFixed(n);
    text(0, 34, `Gruen ${wert(p.flaeche)} %`, 10); text(0, 46, `Abfall ${wert(p.flaechen_abfall)}%  Sinkt ${wert(p.absinken)}%`, 8);
    let fuss = gestoert ? 'keine Verbindung zur Kamera' : p.referenz_zeit ? 'Ref ' + p.referenz_zeit : 'Referenz nach Giessen setzen'; while (breite(fuss, 8) > W && fuss.length > 4) fuss = fuss.slice(0, -1); text(0, 55, fuss, 8);
  } else if (nummer === 1) {
    kopf('Technik', gestoert); const k = zustand.kamera;
    const zeilen = [`Bild ${zustand.bildnummer || 0}   ${((zustand.groesse || 0) / 1024).toFixed(0)} kB`, `Kamera an ${k ? Math.floor(k.betrieb_s / 3600) + ' h ' + String(Math.floor(k.betrieb_s % 3600 / 60)).padStart(2, '0') : '--'}`,
      `${k ? k.rssi + ' dBm' : 'WLAN --'}   Heap ${k ? k.heap_kb + ' k' : '--'}`, `Wdh ${zustand.wiederholungen || 0}   Fehler ${zustand.fehlbilder || 0}`, zustand.web || ''];
    let y = 13; for (const z of zeilen) { text(0, y, z, breite(z, 8) <= W ? 8 : 7); y += 10; }
  } else {
    kopf('Verlauf', gestoert); const pts = zustand.punkte || [];
    if (pts.length < 2) { text((W - breite('noch keine Daten', 10)) / 2, 30, 'noch keine Daten', 10); return; }
    const oben = 21, unten = 52, hoch = Math.max(5, Math.max(...pts.map(q => Math.max(q[1], q[2])))) * 1.15, t0 = pts[0][0], t1 = pts[pts.length - 1][0], spanne = Math.max(1, t1 - t0);
    const X = t => (W - 1) * (t - t0) / spanne, Y = v => unten - (unten - oben) * Math.min(v, hoch) / hoch;
    c.beginPath(); pts.forEach((q, i) => i ? c.lineTo(X(q[0]) + 0.5, Y(q[1]) + 0.5) : c.moveTo(X(q[0]) + 0.5, Y(q[1]) + 0.5)); c.stroke();
    for (let i = 0; i < pts.length; i += 2) c.fillRect(Math.round(X(pts[i][0])), Math.round(Y(pts[i][2])), 1, 1);
    c.fillRect(0, unten + 1, W, 1); text(0, 12, `max ${hoch.toFixed(0)} %`, 7); text(0, 54, `${((t1 - t0) / 3600).toFixed(0)} h    - Abfall   . Sinkt`, 7);
  }
}

// ---------------------------------------------------------------- Bedienung
const $ = id => document.getElementById(id);
let ZUSTAND = { verbunden: true, bildnummer: 0, groesse: 21000, kamera: { betrieb_s: 3600 * 5 + 720, rssi: -61, heap_kb: 168 }, wiederholungen: 0, fehlbilder: 0, web: 'tomate.local:8083', punkte: [], uhr: '12:00', pflanze: {} };
let LETZT = null;
function parameter() { return { defizit: +$('defizit').value, licht: +$('licht').value, wind: +$('wind').value, folie: +$('folie').value, stufe: +$('stufe').value }; }
function messen(p, saat, anzeigen) {
  const c = $('cBild'); c.width = SIM.w; c.height = SIM.h; const ctx = c.getContext('2d'); pflanzeZeichnen(ctx, p, saat);
  const d = ctx.getImageData(0, 0, SIM.w, SIM.h).data; const k = analysiere(d, SIM.w, SIM.h); const b = bewerte(k); ZUSTAND.pflanze = b; ZUSTAND.bildnummer++;
  if (anzeigen) {
    aufbereiten(ctx, d, SIM.w, SIM.h, p.stufe);
    const cm = $('cMaske'); cm.width = SIM.w; cm.height = SIM.h; kontrollbild(cm.getContext('2d'), d, k.maske, SIM.w, SIM.h);
    const farbe = { gruen: '#2e7d32', gelb: '#d99b00', rot: '#c62828', grau: '#888' }[b.ampel];
    $('ampel').style.background = farbe; $('status').textContent = b.status;
    $('kenn').innerHTML = [['Grünfläche A', k.flaeche.toFixed(2) + ' %'], ['Schwerpunkt y_s', k.schwerpunkt.toFixed(2) + ' % der Bildhöhe (0 = oben)'], ['mittlere Helligkeit', k.helligkeit.toFixed(1)],
      ['Referenz', referenz ? `A = ${referenz.flaeche.toFixed(2)} %, y_s = ${referenz.schwerpunkt.toFixed(2)} % (${referenz.zeit})` : 'nicht gesetzt'],
      ['Flächenabfall ΔA (Median 5)', b.flaechen_abfall === null ? '—' : b.flaechen_abfall.toFixed(1) + ' %  (gelb ≥ 8, rot ≥ 15)'], ['Absinken Δy (Median 5)', b.absinken === null ? '—' : b.absinken.toFixed(1) + ' %  (gelb ≥ 2, rot ≥ 4)'],
      ['Ampel', b.ampel]].map(([a, v]) => `<tr><td>${a}</td><td>${v}</td></tr>`).join('');
    for (let s = 0; s < 3; s++) oledSeite($('oled' + s), s, ZUSTAND);
  }
  LETZT = { p, k, b }; return b;
}
function referenzSetzen() { const k = LETZT ? LETZT.k : null; if (!k || k.flaeche < MIN_FLAECHE) { alert('Pflanze derzeit nicht erkannt - Referenz nicht gesetzt'); return; } referenz = { flaeche: k.flaeche, schwerpunkt: k.schwerpunkt, zeit: ZUSTAND.uhr }; messPuffer = []; messen(parameter(), zufallSaat, true); }
function tagSimulieren() {
  // 288 Bilder à 5 min: Licht folgt dem Tag (Sonnenaufgang 6 h, Untergang 20 h), Defizit wächst 0,05 je Stunde, Gießen um 18:00 (Referenz um 6:30 gesetzt),
  // Akku: lädt bei Licht, entlädt sonst; Kamera aus bei 10 %, wieder an bei 50 % — dann Betriebszeit-Rücksprung im Status
  referenz = null; messPuffer = []; ZUSTAND.punkte = []; const pts = [], ereignisse = []; let defizit = 0.15, akku = 0.22, kameraAn = true, betrieb = 0;
  const p0 = parameter(); let k = 0; $('tagStand').textContent = 'Tag läuft …';
  (function schritt() {
    if (k >= 288) { zeichneTag(pts, ereignisse); $('tagStand').textContent = `Tag durch: ${pts.filter(q => q.ampel === 'rot').length} rote, ${pts.filter(q => q.ampel === 'gelb').length} gelbe, ${pts.filter(q => q.ampel === 'grau').length} graue Bilder (Nacht/aus); ${ereignisse.length} Ereignisse`; window.LABOR.tagErgebnis = { pts, ereignisse }; return; }
    const t = k * 5 / 60, uhr = `${String(Math.floor(t)).padStart(2, '0')}:${String(Math.round((t % 1) * 60)).padStart(2, '0')}`; ZUSTAND.uhr = uhr;
    const licht = Math.max(0, Math.sin(Math.PI * (t - 6) / 14)) ** 0.7 * (t > 6 && t < 20 ? 1 : 0);
    akku = Math.min(1, Math.max(0, akku + (licht * 0.25 - 0.05) / 12));   // lädt am Tag rund fünfmal so schnell, wie er nachts entlädt
    if (kameraAn && akku < 0.10) { kameraAn = false; ereignisse.push({ t, text: 'Kamera stromlos (Akku 10 %)' }); }
    if (!kameraAn && akku > 0.50) { kameraAn = true; betrieb = 0; ereignisse.push({ t, text: 'Kamera wieder an — Neustart erkannt (Betriebszeit springt zurück)' }); }
    if (k === 216) { defizit = 0.0; ereignisse.push({ t, text: 'gegossen (18:00)' }); }
    defizit = Math.min(1, defizit + (t > 6 && t < 20 ? 0.05 / 12 : 0.01 / 12));
    ZUSTAND.verbunden = kameraAn; if (kameraAn) betrieb += 300; ZUSTAND.kamera = kameraAn ? { betrieb_s: betrieb, rssi: -58 - Math.round(licht * 6), heap_kb: 168 } : null;
    let b;
    if (kameraAn) { b = messen({ defizit, licht, wind: p0.wind, folie: p0.folie, stufe: p0.stufe }, zufallSaat + k, k % 12 === 0); if (t >= 8 && !referenz && LETZT.k.flaeche >= MIN_FLAECHE) { referenz = { flaeche: LETZT.k.flaeche, schwerpunkt: LETZT.k.schwerpunkt, zeit: uhr }; messPuffer = []; ereignisse.push({ t, text: 'Referenz gesetzt (erstes helles Bild nach 8:00)' }); } }
    else { b = { ampel: 'grau', status: 'keine Verbindung zur Kamera', flaechen_abfall: null, absinken: null }; ZUSTAND.fehlbilder++; }
    pts.push({ t, ampel: b.ampel, abfall: b.flaechen_abfall, absinken: b.absinken, licht, akku, defizit, an: kameraAn });
    if (b.flaechen_abfall !== null) { ZUSTAND.punkte.push([t * 3600, b.flaechen_abfall, b.absinken]); }
    k++; if (k % 12 === 0) zeichneTag(pts, ereignisse); setTimeout(schritt, 0);
  })();
}
function zeichneTag(pts, ereignisse) {
  const c = $('cTag'); const ctx = c.getContext('2d'); c.width = c.clientWidth * devicePixelRatio; c.height = 300 * devicePixelRatio; ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const W = c.clientWidth, Hh = 300, L = 44, R = 12, T = 14, B = 42; ctx.clearRect(0, 0, W, Hh);
  const X = t => L + (W - L - R) * t / 24, Y = v => Hh - B - (Hh - T - B) * Math.min(v, 30) / 30;
  ctx.font = '11px sans-serif'; ctx.fillStyle = '#555'; ctx.textAlign = 'center'; for (let h = 0; h <= 24; h += 3) ctx.fillText(h + ' h', X(h), Hh - 28);
  for (const q of pts) { ctx.fillStyle = { gruen: '#2e7d32', gelb: '#d99b00', rot: '#c62828', grau: '#bbb' }[q.ampel]; ctx.fillRect(X(q.t), Hh - 22, Math.max(1, (W - L - R) / 288), 8); }
  ctx.fillStyle = '#555'; ctx.textAlign = 'left'; ctx.fillText('Ampel je Bild', L, Hh - 10);
  ctx.strokeStyle = '#ccc'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(L, Y(ROT_FLAECHE)); ctx.lineTo(W - R, Y(ROT_FLAECHE)); ctx.stroke(); ctx.beginPath(); ctx.moveTo(L, Y(ROT_ABSINKEN)); ctx.lineTo(W - R, Y(ROT_ABSINKEN)); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = '#d99b00'; ctx.textAlign = 'right'; ctx.fillText('rot ab 15 % Abfall', W - R, Y(ROT_FLAECHE) - 3); ctx.fillStyle = '#d03b3b'; ctx.fillText('rot ab 4 % Absinken', W - R, Y(ROT_ABSINKEN) - 3);
  const linie = (schl, farbe) => { ctx.strokeStyle = farbe; ctx.lineWidth = 1.8; ctx.beginPath(); let erst = true; for (const q of pts) { if (q[schl] === null || q[schl] === undefined) { erst = true; continue; } const x = X(q.t), y = Y(q[schl]); erst ? ctx.moveTo(x, y) : ctx.lineTo(x, y); erst = false; } ctx.stroke(); };
  linie('abfall', '#d99b00'); linie('absinken', '#d03b3b');
  ctx.strokeStyle = '#1b3a8f'; ctx.lineWidth = 1; ctx.beginPath(); pts.forEach((q, i) => { const x = X(q.t), y = Y(q.akku * 30); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  ctx.strokeStyle = '#999'; ctx.beginPath(); pts.forEach((q, i) => { const x = X(q.t), y = Y(q.licht * 30); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  ctx.fillStyle = '#333'; ctx.textAlign = 'left'; ctx.fillText('gelb: Flächenabfall ΔA [%] · rot: Absinken Δy [%] · blau: Akku (0 … 100 % auf 0 … 30) · grau: Licht', L, 10);
  for (const e of ereignisse) { ctx.strokeStyle = '#1b3a8f'; ctx.setLineDash([2, 2]); ctx.beginPath(); ctx.moveTo(X(e.t), T); ctx.lineTo(X(e.t), Hh - B); ctx.stroke(); ctx.setLineDash([]); }
  const liste = $('ereignisse'); liste.innerHTML = ereignisse.map(e => `<li>${String(Math.floor(e.t)).padStart(2, '0')}:${String(Math.round((e.t % 1) * 60)).padStart(2, '0')} — ${e.text}</li>`).join('');
}
window.addEventListener('DOMContentLoaded', () => {
  for (const id of ['defizit', 'licht', 'wind', 'folie', 'stufe']) { const el = $(id), out = $(id + 'Wert'); const z = () => { if (out) out.textContent = id === 'stufe' ? el.value : (+el.value).toFixed(2); }; el.addEventListener('input', () => { z(); messen(parameter(), zufallSaat, true); }); z(); }
  $('messen').onclick = () => { zufallSaat++; messen(parameter(), zufallSaat, true); }; $('referenz').onclick = referenzSetzen; $('tag').onclick = tagSimulieren;
  messen(parameter(), zufallSaat, true);
  window.LABOR = { analysiere, bewerte, messen, referenzSetzen, tagSimulieren, get letzt() { return LETZT; }, get referenz() { return referenz; }, ZUSTAND, EXG_SCHWELLE, MIN_GRUEN };
});
"""


def seite() -> str:
    doku = "".join(f'<details class="doku"><summary>{titel}</summary><article class="documentation">{dokument_html(n)}</article></details>\n' for n, titel in DOKUMENTE)
    oled_bild = daten_uri(D / "oled_vorschau.png"); aufb_bild = daten_uri(D / "aufbereitung_vergleich.png")
    css = """
:root { --tinte:#1a1a1a; --leise:#666; --blau:#1b3a8f; --rot:#b0171f; --gruen:#2e7d32; --karte:#fff; --grund:#fbfaf7; --linie:#d8d4cc; }
body { font-family: "DejaVu Serif", Georgia, serif; color: var(--tinte); background: var(--grund); margin: 0; line-height: 1.45; }
header { padding: 14px 24px 6px; border-bottom: 1px solid var(--linie); background: #f3f1ea; }
h1 { margin: 0 0 4px; font-size: 22px; } h2 { font-size: 17px; margin: 18px 0 8px; } h3 { font-size: 15px; margin: 14px 0 6px; }
.small { color: var(--leise); font-size: 13px; }
main { display: grid; grid-template-columns: 400px 1fr; gap: 16px; padding: 16px 24px; }
@media (max-width: 1000px) { main { grid-template-columns: 1fr; } }
.karte { background: var(--karte); border: 1px solid var(--linie); border-radius: 8px; padding: 12px 16px; }
label.zeile { display: grid; grid-template-columns: 150px 1fr 60px; gap: 8px; align-items: center; font-size: 14px; margin: 4px 0; }
input[type=range] { width: 100%; }
button { font: inherit; padding: 6px 12px; margin: 4px 6px 4px 0; border: 1px solid var(--blau); background: #eef2fa; border-radius: 6px; cursor: pointer; }
button.haupt { background: var(--blau); color: #fff; }
canvas.bild { width: 100%; max-width: 480px; border: 1px solid var(--linie); background: #fff; display: block; }
canvas.oled { width: 100%; max-width: 384px; border: 4px solid #222; border-radius: 4px; background: #000; display: block; image-rendering: pixelated; }
table { border-collapse: collapse; font-size: 13px; } td, th { border-bottom: 1px solid var(--linie); padding: 3px 8px; text-align: left; vertical-align: top; }
details.doku { margin: 16px 24px; background: var(--karte); border: 1px solid var(--linie); border-radius: 8px; padding: 8px 16px; }
details.doku > summary { cursor: pointer; font-weight: bold; }
article.documentation { max-width: 900px; } article.documentation img { max-width: 100%; height: auto; } article.documentation table { font-size: 13px; }
.ampel { display: inline-block; width: 22px; height: 22px; border-radius: 50%; vertical-align: middle; margin-right: 8px; border: 1px solid #555; }
.drei { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; } @media (max-width: 1000px) { .drei { grid-template-columns: 1fr; } }
"""
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Tomatenwächter · Fassung {VERSION}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{css}</style></head>
<body>
<header>
<h1>Der Tomaten-Bewässerungswächter: Bild, Grünmaske, Ampel — Simulation, Display, Dokumentation</h1>
<p class="small" id="fassung">Fassung {VERSION} · {DATUM} · {NAMENSNENNUNG}</p>
<p class="small">Eine solarbetriebene ESP32-CAM fotografiert eine Tomatenpflanze, ein Raspberry Pi holt das Bild über Modbus TCP, trennt die Pflanze mit dem Excess-Green-Index vom Hintergrund und liest an Grünfläche und Schwerpunkt ab, ob die Blätter hängen. Hier läuft dieselbe Auswertung im Browser an einer gezeichneten Pflanze, dazu die drei Seiten des Displays und ein Tag im Zeitraffer mit Solarabschaltung. Alles rechnet ohne Netz.</p>
</header>
<main>
  <section class="karte">
    <h2 style="margin-top:0">Einstellen</h2>
    <button id="messen" class="haupt">Bild aufnehmen</button><button id="referenz">Referenz setzen</button><button id="tag">Ein Tag im Zeitraffer</button>
    <label class="zeile">Wasserdefizit <input type="range" id="defizit" min="0" max="1" step="0.02" value="0.1"><span id="defizitWert"></span></label>
    <label class="zeile">Licht <input type="range" id="licht" min="0" max="1" step="0.02" value="0.9"><span id="lichtWert"></span></label>
    <label class="zeile">Wind (Bewegung) <input type="range" id="wind" min="0" max="1" step="0.05" value="0.2"><span id="windWert"></span></label>
    <label class="zeile">Folie (Unschärfe) <input type="range" id="folie" min="0" max="1" step="0.05" value="0"><span id="folieWert"></span></label>
    <label class="zeile">Aufbereitung (Anzeige) <input type="range" id="stufe" min="0" max="3" step="1" value="0"><span id="stufeWert"></span></label>
    <h3>Bewertung</h3>
    <p><span class="ampel" id="ampel"></span><b id="status"></b></p>
    <table><tbody id="kenn"></tbody></table>
    <p class="small">Ablauf wie am Gerät: Pflanze gießen (Defizit auf 0), „Referenz setzen“, dann das Defizit wachsen lassen — die Ampel schaltet bei 8 % / 15 % Flächenabfall oder 2 % / 4 % Absinken des Schwerpunkts, jeweils auf dem Median der letzten fünf Messungen. Unter Helligkeit 40 ist Nacht, unter 2 % Grünanteil gilt die Pflanze als nicht erkannt.</p>
  </section>
  <section class="karte">
    <h2 style="margin-top:0">Kamerabild und Grünmaske</h2>
    <div class="drei" style="grid-template-columns:1fr 1fr">
      <div><canvas id="cBild" class="bild"></canvas><p class="small">Kamerabild (mit der gewählten Aufbereitungsstufe, nur Anzeige)</p></div>
      <div><canvas id="cMaske" class="bild"></canvas><p class="small">Kontrollbild: Pflanzenpixel (2G − R − B &gt; 40 und G &gt; 60) farbig, Rest abgedunkelt — analysiert wird immer das Original</p></div>
    </div>
    <h2>Das Display (128 × 64), drei Seiten im Wechsel</h2>
    <div class="drei">
      <div><canvas id="oled0" class="oled"></canvas><p class="small">Seite 1: die Antwort auf die einzige Frage — gießen?</p></div>
      <div><canvas id="oled1" class="oled"></canvas><p class="small">Seite 2: läuft die Übertragung sauber?</p></div>
      <div><canvas id="oled2" class="oled"></canvas><p class="small">Seite 3: Verlauf der Welke-Kennwerte</p></div>
    </div>
    <h2>Ein Tag im Zeitraffer</h2>
    <canvas id="cTag" style="width:100%;height:300px;border:1px solid var(--linie);background:#fff"></canvas>
    <p class="small" id="tagStand">288 Bilder à 5 min: Tageslicht, wachsendes Wasserdefizit, Referenz beim ersten hellen Bild nach 8:00, Gießen um 18:00; der Akku lädt bei Licht und entlädt nachts, die Versorgung schaltet die Kamera bei 10 % ab und bei 50 % wieder ein — der Wächter erkennt den Neustart am Rücksprung der Betriebszeit.</p>
    <ul class="small" id="ereignisse"></ul>
  </section>
</main>
<section class="karte" style="margin:0 24px 16px">
  <h2 style="margin-top:0">Vom Gerät</h2>
  <div class="drei" style="grid-template-columns:1fr 1fr">
    <div><img src="{oled_bild}" style="max-width:100%"><p class="small">Rendervorschau der Displayseiten aus oled_anzeige.py</p></div>
    <div><img src="{aufb_bild}" style="max-width:100%"><p class="small">Bildaufbereitung gegen die Regenhaube: Original, wie durch die Folie, Stufen 1 bis 3 (Kontrastfaktor und Unschärfemaske)</p></div>
  </div>
</section>
{doku}
<script>
{SEITE_JS}
</script>
</body></html>
"""


if __name__ == "__main__":
    t = seite(); ZIEL.write_text(t, encoding="utf-8")
    print(f"{ZIEL.name}: {len(t.encode('utf-8'))/1024/1024:.2f} MB (Fassung {VERSION}, {DATUM})")
