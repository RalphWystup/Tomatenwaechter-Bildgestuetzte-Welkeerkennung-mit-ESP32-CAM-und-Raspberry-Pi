/*
 * ESP32_CAM_Modbus_Snapshot.ino
 * ESP32-CAM (AI Thinker) als Modbus-TCP-Slave: Schnappschuesse auf Anforderung,
 * Bilduebertragung blockweise ueber Holding-Register -- mit CRC je Block und
 * CRC uebers ganze Bild, damit der Master (cam_dashboard.py) gestoerte Bloecke
 * erkennen und einzeln neu anfordern kann.
 *
 * Board: "AI Thinker ESP32-CAM" (Board-Package "esp32 by Espressif Systems").
 * WLAN-Zugangsdaten unten eintragen. Die IP meldet der serielle Monitor
 * (115200 Baud) -- sie gehoert in cam_dashboard.py bei ESP32CAM_IP.
 *
 * ---------------------------------------------------------------------------
 * REGISTERPLAN (Holding-Register, Modbus TCP Port 502, eine Verbindung)
 * ---------------------------------------------------------------------------
 *   0  Bildnummer      zaehlt bei jeder Aufnahme hoch                (lesen)
 *   1  Status          0=kein Bild  2=Bild bereit  3=Kamerafehler    (lesen)
 *   2  Bildgroesse Hi  Bildgroesse in Bytes, High-Word               (lesen)
 *   3  Bildgroesse Lo  Bildgroesse in Bytes, Low-Word                (lesen)
 *   4  Blockgroesse    Bytes je Block (fest 240)                     (lesen)
 *   5  Blockanzahl     Anzahl Bloecke des aktuellen Bilds            (lesen)
 *   6  Blockindex      welcher Block in 99..219 liegt        (lesen+schreiben)
 *   7  reserviert
 *   8  Kommando        1 schreiben = neue Aufnahme ausloesen      (schreiben)
 *   9  Blitz-LED       0/1 = Blitz (GPIO4) aus/ein            (lesen+schreiben)
 *  10  Bild-CRC16      CRC16 (Polynom 0xA001) ueber das ganze JPEG   (lesen)
 *  11  Betriebszeit Hi Sekunden seit Einschalten, High-Word          (lesen)
 *  12  Betriebszeit Lo Sekunden seit Einschalten, Low-Word           (lesen)
 *                      (kleiner Wert = Kamera wurde gerade neu
 *                       eingeschaltet, z. B. durch die Solar-Abschaltung)
 *  13  WLAN-RSSI       Signalstaerke in dBm, Zweierkomplement        (lesen)
 *  14  freier Heap     freier Arbeitsspeicher in kB                  (lesen)
 *  99  Block-CRC16     CRC16 des aktuellen Blocks                    (lesen)
 * 100..219  Blockdaten 120 Register = 240 Bytes, High-Byte zuerst;
 *           der letzte Block ist mit Nullen aufgefuellt              (lesen)
 *
 * Master-Ablauf: Reg 8 = 1 schreiben (Antwort kommt erst NACH der Aufnahme,
 * Timeout >= 5 s waehlen) -> Reg 0..10 lesen -> je Block: Reg 6 = Index
 * schreiben, dann Reg 99..219 in EINEM FC03 lesen (121 Register), CRC
 * pruefen, bei Fehler denselben Block wiederholen -> am Ende Laenge,
 * Bild-CRC und JPEG-Marker (FFD8...FFD9) pruefen.
 *
 * Funktionscodes: FC03/FC04 lesen, FC06 schreiben. Unit-Kennung ungeprueft.
 * ---------------------------------------------------------------------------
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <ArduinoOTA.h>   // Sketch-Update ueber WLAN (Netzwerk-Port in der IDE)

// =============================================
//   WLAN-ZUGANGSDATEN - HIER ANPASSEN
// =============================================
const char* WIFI_SSID     = "MeinNetz";       // eigenen Netznamen eintragen
const char* WIFI_PASSWORT = "xxxxxxxx";   // hier das eigene Kennwort eintragen (im Quelltext steht keines)

const uint16_t TCP_PORT   = 502;
const int      BLOCK_BYTES = 240;   // 120 Register je Block
const int      BLOCK_REGS  = 120;

// Aufloesung/Qualitaet: FRAMESIZE_VGA (640x480) ist ein guter Kompromiss.
// Schneller: FRAMESIZE_QVGA (320x240, ~4x kleiner). jpeg_quality 0..63,
// niedriger = besser/groesser.
#define BILD_GROESSE   FRAMESIZE_VGA
#define BILD_QUALITAET 10

#define BLITZ_PIN 4                 // weisse Blitz-LED des AI-Thinker-Boards

// =============================================
//   KAMERA-PINS (AI Thinker ESP32-CAM)
// =============================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// =============================================
//   ZUSTAND
// =============================================
WiFiServer server(TCP_PORT);
WiFiClient client;                  // eine Verbindung (wie beim Gateway)

camera_fb_t* fb = NULL;             // aktuelles Bild (bleibt bis zur naechsten Aufnahme gueltig)
uint16_t bildnummer  = 0;
uint16_t status_reg  = 0;           // 0=kein Bild, 2=bereit, 3=Kamerafehler
uint16_t blockindex  = 0;
uint16_t blockanzahl = 0;
uint16_t bild_crc    = 0;
uint16_t blitz       = 0;

uint8_t  puffer[300];               // MBAP-Empfangspuffer
int      puffer_len = 0;

// =============================================
//   HILFSFUNKTIONEN
// =============================================
uint16_t crc16(const uint8_t* d, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= d[i];
    for (int b = 0; b < 8; b++)
      crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
  }
  return crc;
}

int blocklaenge(uint16_t idx) {     // Nutzbytes im Block idx (letzter ist kuerzer)
  if (!fb || idx >= blockanzahl) return 0;
  size_t rest = fb->len - (size_t)idx * BLOCK_BYTES;
  return rest >= (size_t)BLOCK_BYTES ? BLOCK_BYTES : (int)rest;
}

uint8_t blockbyte(uint16_t idx, int i) {  // Byte i des Blocks idx (0 = Fuellung)
  if (!fb) return 0;
  size_t pos = (size_t)idx * BLOCK_BYTES + i;
  return (i < blocklaenge(idx)) ? fb->buf[pos] : 0;
}

void aufnahme() {
  status_reg = 0;
  if (fb) { esp_camera_fb_return(fb); fb = NULL; }
  camera_fb_t* alt = esp_camera_fb_get();       // einen Frame verwerfen ->
  if (alt) esp_camera_fb_return(alt);           // wirklich aktuelles Bild
  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[FEHLER] Kein Kamerabild");
    status_reg = 3;
    blockanzahl = 0;
    return;
  }
  blockanzahl = (fb->len + BLOCK_BYTES - 1) / BLOCK_BYTES;
  bild_crc    = crc16(fb->buf, fb->len);
  blockindex  = 0;
  bildnummer++;
  status_reg  = 2;
  Serial.printf("[BILD] Nr. %u: %u Bytes, %u Bloecke, CRC 0x%04X\n",
                bildnummer, (unsigned)fb->len, blockanzahl, bild_crc);
}

// Registerwert liefern (virtuelles Registerabbild)
uint16_t lese_register(uint16_t adr) {
  switch (adr) {
    case 0:  return bildnummer;
    case 1:  return status_reg;
    case 2:  return fb ? (uint16_t)(fb->len >> 16) : 0;
    case 3:  return fb ? (uint16_t)(fb->len & 0xFFFF) : 0;
    case 4:  return BLOCK_BYTES;
    case 5:  return blockanzahl;
    case 6:  return blockindex;
    case 9:  return blitz;
    case 10: return bild_crc;
    case 11: return (uint16_t)((millis() / 1000UL) >> 16);   // Betriebszeit Hi
    case 12: return (uint16_t)(millis() / 1000UL);           // Betriebszeit Lo
    case 13: return (uint16_t)(int16_t)WiFi.RSSI();          // dBm (negativ)
    case 14: return (uint16_t)(ESP.getFreeHeap() / 1024);    // freier Heap kB
    case 99: {                       // CRC des aktuellen Blocks
      if (!fb) return 0;
      return crc16(fb->buf + (size_t)blockindex * BLOCK_BYTES,
                   blocklaenge(blockindex));
    }
    default:
      if (adr >= 100 && adr < 100 + BLOCK_REGS) {
        int i = (adr - 100) * 2;
        return ((uint16_t)blockbyte(blockindex, i) << 8) |
                blockbyte(blockindex, i + 1);
      }
      return 0;
  }
}

bool schreibe_register(uint16_t adr, uint16_t wert) {
  if (adr == 6) { blockindex = (blockanzahl && wert < blockanzahl) ? wert : 0; return true; }
  if (adr == 8) { if (wert == 1) aufnahme(); return true; }
  if (adr == 9) { blitz = wert ? 1 : 0; digitalWrite(BLITZ_PIN, blitz); return true; }
  return false;
}

// =============================================
//   MODBUS TCP (MBAP-Kopf 7 Byte + PDU)
// =============================================
void sende_antwort(const uint8_t* tid, uint8_t unit,
                   const uint8_t* pdu, int pdu_len) {
  uint8_t kopf[7] = { tid[0], tid[1], 0, 0,
                      (uint8_t)((pdu_len + 1) >> 8),
                      (uint8_t)((pdu_len + 1) & 0xFF), unit };
  client.write(kopf, 7);
  client.write(pdu, pdu_len);
}

void bearbeite_pdu(const uint8_t* tid, uint8_t unit,
                   const uint8_t* pdu, int pdu_len) {
  uint8_t antwort[260];
  uint8_t fc = pdu[0];
  if (pdu_len < 5) return;
  uint16_t start = ((uint16_t)pdu[1] << 8) | pdu[2];
  uint16_t wert  = ((uint16_t)pdu[3] << 8) | pdu[4];

  if (fc == 3 || fc == 4) {                     // Register lesen
    uint16_t anzahl = wert;
    if (anzahl == 0 || anzahl > 125 || start + anzahl > 220) {
      uint8_t aus[2] = { (uint8_t)(fc | 0x80), 2 };
      sende_antwort(tid, unit, aus, 2);
      return;
    }
    antwort[0] = fc;
    antwort[1] = anzahl * 2;
    for (int i = 0; i < anzahl; i++) {
      uint16_t v = lese_register(start + i);
      antwort[2 + 2*i] = v >> 8;
      antwort[3 + 2*i] = v & 0xFF;
    }
    sende_antwort(tid, unit, antwort, 2 + 2 * anzahl);
    return;
  }

  if (fc == 6) {                                // einzelnes Register schreiben
    if (!schreibe_register(start, wert)) {
      uint8_t aus[2] = { (uint8_t)(fc | 0x80), 2 };
      sende_antwort(tid, unit, aus, 2);
      return;
    }
    sende_antwort(tid, unit, pdu, 5);           // Echo als Bestaetigung
    return;
  }

  uint8_t aus[2] = { (uint8_t)(fc | 0x80), 1 }; // Funktionscode unbekannt
  sende_antwort(tid, unit, aus, 2);
}

void tcp_poll() {
  if (!client || !client.connected()) {
    WiFiClient neu = server.available();
    if (neu) {
      client = neu;
      puffer_len = 0;
      Serial.println("[TCP] Client verbunden: " + client.remoteIP().toString());
    }
    return;
  }
  while (client.available() && puffer_len < (int)sizeof(puffer))
    puffer[puffer_len++] = client.read();

  // vollstaendige MBAP-Telegramme abarbeiten
  while (puffer_len >= 7) {
    int laenge = ((int)puffer[4] << 8) | puffer[5];   // Unit + PDU
    if (laenge < 2 || laenge > 254) { puffer_len = 0; client.stop(); return; }
    if (puffer_len < 6 + laenge) break;               // noch unvollstaendig
    bearbeite_pdu(puffer, puffer[6], puffer + 7, laenge - 1);
    int rest = puffer_len - (6 + laenge);
    memmove(puffer, puffer + 6 + laenge, rest);
    puffer_len = rest;
  }
}

// =============================================
//   SETUP / LOOP
// =============================================
void setup() {
  Serial.begin(115200);
  Serial.println("\n[START] ESP32-CAM Modbus-Snapshot ...");
  pinMode(BLITZ_PIN, OUTPUT);
  digitalWrite(BLITZ_PIN, LOW);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk  = XCLK_GPIO_NUM;   config.pin_pclk  = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;  config.pin_href  = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM;   config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  if (psramFound()) {
    config.frame_size   = BILD_GROESSE;
    config.jpeg_quality = BILD_QUALITAET;
    config.fb_count     = 2;
    Serial.println("[INFO] PSRAM gefunden");
  } else {
    config.frame_size   = FRAMESIZE_CIF;
    config.jpeg_quality = 12;
    config.fb_count     = 1;
    Serial.println("[INFO] Kein PSRAM - reduzierte Aufloesung");
  }
  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("[FEHLER] Kamera-Init fehlgeschlagen, Neustart in 5 s");
    delay(5000);
    ESP.restart();
  }
  sensor_t* s = esp_camera_sensor_get();
  s->set_whitebal(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_gain_ctrl(s, 1);
  Serial.println("[OK] Kamera initialisiert");

  WiFi.setHostname("tomatencam");   // Name im Router (tomatencam.fritz.box)
  WiFi.begin(WIFI_SSID, WIFI_PASSWORT);
  Serial.print("[WLAN] Verbinde");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print("[OK] WLAN verbunden - in cam_dashboard.py eintragen:  ");
  Serial.println("ESP32CAM_IP = \"" + WiFi.localIP().toString() + "\"");

  // OTA: kuenftige Updates ueber WLAN statt ueber das wacklige Kabel.
  // Die Kamera erscheint in der Arduino IDE unter Werkzeuge -> Port
  // als Netzwerk-Port "tomatencam at <IP>".
  ArduinoOTA.setHostname("tomatencam");
  ArduinoOTA.begin();
  Serial.println("[OK] OTA bereit (Netzwerk-Port 'tomatencam')");

  server.begin();
  server.setNoDelay(true);
  Serial.printf("[BEREIT] Modbus TCP auf Port %u\n", TCP_PORT);
}

void loop() {
  ArduinoOTA.handle();     // auf OTA-Updates aus der IDE lauschen
  tcp_poll();

  // WLAN-Watchdog (nicht blockierend)
  static uint32_t letzter_check = 0;
  if (millis() - letzter_check > 5000) {
    letzter_check = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WLAN] Verbindung verloren - Reconnect ...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORT);
    }
  }
}
