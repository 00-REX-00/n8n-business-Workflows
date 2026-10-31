#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the app. Run as root on the server.
set -euo pipefail
BASE=/opt/predictor

runuser -u predictor -- git -C "$BASE" pull --ff-only
runuser -u predictor -- "$BASE/venv/bin/pip" install --quiet -r "$BASE/football-predictor/requirements.txt"
install -m 644 "$BASE/football-predictor/deploy/football-predictor.service" /etc/systemd/system/football-predictor.service
systemctl daemon-reload
systemctl restart football-predictor
echo "Updated to: $(runuser -u predictor -- git -C "$BASE" log -1 --format='%h %s')"
