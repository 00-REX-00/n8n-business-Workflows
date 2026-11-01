#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the app. Run as root on the server.
set -euo pipefail
BASE=/opt/predictor

runuser -u predictor -- git -C "$BASE" pull --ff-only
runuser -u predictor -- "$BASE/venv/bin/pip" install --quiet -r "$BASE/football-predictor/requirements.txt"
install -m 644 "$BASE/football-predictor/deploy/football-predictor.service" /etc/systemd/system/football-predictor.service
install -m 644 "$BASE/football-predictor/deploy/odds-snapshot.service" /etc/systemd/system/odds-snapshot.service
install -m 644 "$BASE/football-predictor/deploy/odds-snapshot.timer" /etc/systemd/system/odds-snapshot.timer
systemctl daemon-reload
systemctl enable --now odds-snapshot.timer
systemctl restart football-predictor
echo "Updated to: $(runuser -u predictor -- git -C "$BASE" log -1 --format='%h %s')"
