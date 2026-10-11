#!/bin/sh
# Install the OCCHIO boot services on the UNO Q (run on the board, from the repo root: sudo sh deploy/install_autostart.sh).
# Afterwards: MCU app and vision node start at every boot; the node restarts by itself if it crashes.
set -e
cd "$(dirname "$0")"
if [ ! -f /etc/default/occhio ]; then
  cat > /etc/default/occhio <<'EOF'
# OCCHIO boot settings (edit, then: sudo systemctl restart occhio)
OCCHIO_CONFIG=configs/board_imx219.yaml
OCCHIO_WRAPPER=libcamerify
OCCHIO_MCU_APP=/home/arduino/ArduinoApps/crosswalk_mcu
EOF
fi
install -m 644 occhio-mcu.service occhio.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable occhio-mcu.service occhio.service
systemctl restart occhio-mcu.service
systemctl restart occhio.service
systemctl --no-pager status occhio-mcu.service occhio.service | head -30
echo "Logs: journalctl -u occhio -f      Health: curl -s localhost:8000/api/health"
