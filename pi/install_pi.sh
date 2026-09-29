#!/bin/bash
# ---------------------------------------------------------------------------
# install_pi.sh - richtet den Tomaten-Bewaesserungswaechter auf einem
# frisch gebrannten Raspberry Pi OS ein: Pakete, I2C, Autostart.
#
# Aufruf (im Ordner mit pflanzen_dashboard.py):
#     chmod +x install_pi.sh
#     sudo ./install_pi.sh
#
# Danach laeuft der Waechter bei jedem Einschalten automatisch mit.
# ---------------------------------------------------------------------------
set -e

DIENST=pflanzen_waechter
ORDNER="$(cd "$(dirname "$0")" && pwd)"
BENUTZER="${SUDO_USER:-$(id -un)}"

echo "=== Tomaten-Bewaesserungswaechter einrichten ==="
echo "    Ordner:   $ORDNER"
echo "    Benutzer: $BENUTZER"
echo

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo aufrufen:  sudo ./install_pi.sh" >&2
  exit 1
fi
if [ ! -f "$ORDNER/pflanzen_dashboard.py" ]; then
  echo "pflanzen_dashboard.py liegt nicht in $ORDNER" >&2
  exit 1
fi
if ! grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
  echo "HINWEIS: das sieht nicht nach einem Raspberry Pi aus."
  read -r -p "Trotzdem weitermachen? [j/N] " antwort
  [ "$antwort" = "j" ] || exit 1
fi

# --- 1. Pakete ------------------------------------------------------------
# Bewusst per apt und nicht per pip: Raspberry Pi OS (Bookworm) laesst
# "pip install" ins System nicht mehr zu (externally-managed-environment).
echo "--- 1/5  Pakete installieren"
apt-get update -qq
apt-get install -y python3-numpy python3-pil fonts-dejavu-core i2c-tools

# --- 2. I2C einschalten ---------------------------------------------------
echo "--- 2/5  I2C einschalten"
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_i2c 0
else
  echo "    raspi-config fehlt - dtparam=i2c_arm=on selbst eintragen!"
fi

CONFIG=/boot/firmware/config.txt              # Bookworm
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt   # aeltere Fassungen
if [ -f "$CONFIG" ] && ! grep -q "i2c_arm_baudrate" "$CONFIG"; then
  echo "dtparam=i2c_arm_baudrate=400000" >> "$CONFIG"
  echo "    I2C-Takt auf 400 kHz gesetzt (in $CONFIG, Zeile wieder"
  echo "    entfernbar) - wirkt nach dem naechsten Neustart."
fi

# Der Dienstbenutzer muss auf /dev/i2c-1 schreiben duerfen.
usermod -aG i2c,gpio "$BENUTZER" 2>/dev/null || usermod -aG i2c "$BENUTZER"

# --- 3. Display suchen ----------------------------------------------------
echo "--- 3/5  Display suchen"
if [ -e /dev/i2c-1 ]; then
  if i2cdetect -y 1 2>/dev/null | grep -qE " 3c | 3d "; then
    echo "    OLED gefunden."
  else
    echo "    Noch kein OLED auf dem Bus (Adresse 3c/3d fehlt)."
    echo "    Verdrahtung pruefen; nach dem ersten Einschalten von I2C"
    echo "    ist ausserdem ein Neustart noetig."
  fi
else
  echo "    /dev/i2c-1 gibt es noch nicht -> nach dem Neustart pruefen mit:"
  echo "        i2cdetect -y 1"
fi

# --- 4. Autostart ---------------------------------------------------------
echo "--- 4/5  Autostart einrichten"
sed -e "s|__BENUTZER__|$BENUTZER|g" -e "s|__ORDNER__|$ORDNER|g" \
    "$ORDNER/$DIENST.service" > "/etc/systemd/system/$DIENST.service"
systemctl daemon-reload
systemctl enable "$DIENST"
systemctl restart "$DIENST"

# --- 5. Rueckmeldung ------------------------------------------------------
echo "--- 5/5  Fertig"
sleep 2
systemctl --no-pager --lines=8 status "$DIENST" || true
IP="$(hostname -I | awk '{print $1}')"
echo
echo "Dashboard:      http://$IP:8083"
echo "                http://$(hostname).fritz.box:8083"
echo "Meldungen:      journalctl -u $DIENST -f"
echo "Anhalten:       sudo systemctl stop $DIENST"
echo "Nach Aenderung: sudo systemctl restart $DIENST"
echo
echo "Wenn I2C gerade erst eingeschaltet wurde:  sudo reboot"
