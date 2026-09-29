// Prüfung der Tomatenwächter-Seite im Browser: T1 lädt ohne Fehler, Werkzeug vor Text; T2 Auswertung stimmt mit der Regel überein
// (Referenz bei Defizit 0 → grün, Defizit 0,6 → rot; Licht 0,1 → „zu dunkel“); T3 Tag im Zeitraffer läuft durch mit Gießen und
// Solarabschaltung; T4 Display-Seiten gezeichnet; T5 Dokumentation vorhanden und neutralisiert (keine Heimnetzadresse, kein Netzname).
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require('/tmp/node_modules/playwright');
const H = '/workspace/Tomate/Seite/'; const V = fs.readFileSync(H + 'VERSION', 'utf8').trim();
const S = '/tmp/claude-1000/-workspace/905236e7-aea4-4c03-805a-5e5668f5230d/scratchpad/';
let fehler = 0; const BEF = []; const sage = (gut, t) => { console.log(`  ${gut ? 'ok    ' : 'FEHLER'} ${t}`); BEF.push({ gut, text: t }); if (!gut) fehler++; };
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 1000 } });
const konsole = []; p.on('pageerror', e => konsole.push(e.message)); p.on('console', m => { if (m.type() === 'error') konsole.push(m.text()); });
await p.goto(`file://${H}Tomatenwaechter_${V}.html`, { waitUntil: 'load', timeout: 180000 }); await p.waitForTimeout(1200);
sage(konsole.length === 0, 'keine Konsolenfehler' + (konsole.length ? ': ' + konsole[0].slice(0, 120) : ''));
const lage = await p.evaluate(() => document.getElementById('messen').getBoundingClientRect().top); sage(lage < 900, `Werkzeug vor Text: Knopf bei ${lage.toFixed(0)} px`);
const setze = async (id, v) => { await p.evaluate(([id, v]) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('input')); }, [id, v]); };
await setze('defizit', 0); await p.click('#referenz'); await p.waitForTimeout(200);
let e = await p.evaluate(() => window.LABOR.letzt.b); sage(e.ampel === 'gruen' && e.flaechen_abfall === 0, `nach Gießen und Referenz: ${e.ampel}, ΔA ${e.flaechen_abfall} %, Δy ${e.absinken} %`);
for (let k = 0; k < 4; k++) { await setze('defizit', 0.3); await p.waitForTimeout(60); } e = await p.evaluate(() => window.LABOR.letzt.b);
sage(['gelb', 'rot'].includes(e.ampel), `Defizit 0,30 (Median über 5 Bilder): ${e.ampel}, ΔA ${e.flaechen_abfall} %, Δy ${e.absinken} % — Status „${e.status}“`);
for (let k = 0; k < 6; k++) { await setze('defizit', 0.7); await p.waitForTimeout(60); } e = await p.evaluate(() => window.LABOR.letzt.b);
sage(e.ampel === 'rot' && (e.flaechen_abfall >= 15 || e.absinken >= 4), `Defizit 0,70 (Median über 5 Bilder): ${e.ampel}, ΔA ${e.flaechen_abfall} %, Δy ${e.absinken} % — „${e.status}“`);
await setze('licht', 0.05); await p.waitForTimeout(100); e = await p.evaluate(() => window.LABOR.letzt.b); sage(e.ampel === 'grau' && e.status.includes('dunkel'), `Licht 0,05: ${e.ampel} — „${e.status}“`);
await setze('licht', 0.9); await setze('defizit', 0.1); await p.waitForTimeout(150); await p.screenshot({ path: S + 'tomate_seite.png' });
await p.click('#tag'); await p.waitForFunction(() => window.LABOR.tagErgebnis, null, { timeout: 300000 });
const t = await p.evaluate(() => window.LABOR.tagErgebnis); const ev = t.ereignisse.map(x => x.text).join(' | ');
sage(t.pts.length === 288 && ev.includes('gegossen') && ev.includes('Referenz gesetzt') && ev.includes('stromlos') && ev.includes('wieder an'), `Tag im Zeitraffer: ${t.pts.length} Bilder, Ereignisse: ${ev}`);
sage(t.pts.some(q => q.ampel === 'rot') && t.pts.some(q => q.ampel === 'gruen') && t.pts.some(q => q.ampel === 'grau'), `Ampel im Tag: rot ${t.pts.filter(q => q.ampel === 'rot').length}, gelb ${t.pts.filter(q => q.ampel === 'gelb').length}, grün ${t.pts.filter(q => q.ampel === 'gruen').length}, grau ${t.pts.filter(q => q.ampel === 'grau').length}`);
await p.evaluate(() => window.scrollTo(0, document.getElementById('oled0').getBoundingClientRect().top + window.scrollY - 80)); await p.waitForTimeout(300); await p.screenshot({ path: S + 'tomate_tag.png' });
const oledPix = await p.evaluate(() => { const c = document.getElementById('oled0'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 128) n++; return n; });
sage(oledPix > 500, `Display-Seite 1 gezeichnet (${oledPix} helle Bildpunkte)`);
const doku = (await p.evaluate(() => document.body.textContent)).replace(/\s+/g, ' ');
sage(doku.includes('Excess-Green-Index') && doku.includes('Registerplan') && doku.includes('Wiederaufbau') && doku.includes('Umgebungskamera'), 'Dokumentation: Band 1 bis 3 und Anleitungen in der Seite');
sage(!/192\.168\.178\.\d/.test(doku) && doku.includes('<WLAN-Name>') && doku.includes('xxxxxxxxx'), 'Dokumentation neutralisiert: keine Heimnetzadresse, kein WLAN-Name, kein Kennwortwert');
const kopf = await p.$eval('#fassung', e => e.textContent); sage(kopf.includes(`Fassung ${V}`) && kopf.includes('Ralph Wystup'), `Kopf: ${kopf.slice(0, 60)}`);
await b.close();
fs.writeFileSync(H + 'pruefe_seite.json', JSON.stringify({ datum: new Date().toISOString(), fassung: V, befunde: BEF, fehler }, null, 1));
console.log(fehler ? `${fehler} Beanstandung(en)` : 'alles in Ordnung'); process.exit(fehler ? 1 : 0);
