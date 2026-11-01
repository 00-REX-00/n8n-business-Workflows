#!/usr/bin/env bash
# Install the Football Predictor on a fresh Ubuntu or Debian VPS, for you and invited friends.
#
#   bash setup.sh predictor.example.com you@example.com yourname
#
# Run as root. Point the domain's DNS (an A record) at this server first, or the
# HTTPS step fails (rerun the script once DNS works). EMAIL "-" skips Let's
# Encrypt's expiry emails. It asks for the first login's password unless
# PREDICTOR_PASSWORD is set. Safe to run again, and alongside other apps: it
# only adds firewall rules and never restarts other services.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l   # no prompts, no automatic service restarts

DOMAIN=${1:?usage: setup.sh DOMAIN EMAIL FIRST_LOGIN}
EMAIL=${2:?usage: setup.sh DOMAIN EMAIL FIRST_LOGIN}
FIRST_LOGIN=${3:?usage: setup.sh DOMAIN EMAIL FIRST_LOGIN}
REPO=https://github.com/00-REX-00/n8n-business-Workflows.git
BRANCH=claude/optimistic-hopper-kfj4ww
BASE=/opt/predictor
APP=$BASE/football-predictor
PASSWORDS=/etc/nginx/predictor.htpasswd
as_app() { runuser -u predictor -- "$@"; }

echo "== Packages"
apt-get update
apt-get install -y git python3 python3-venv python3-pip nginx apache2-utils certbot python3-certbot-nginx ufw

echo "== App user and code"
id predictor >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin predictor
mkdir -p "$BASE"
chown predictor:predictor "$BASE"
if [ -d "$BASE/.git" ]; then
  as_app git -C "$BASE" pull --ff-only
else
  as_app git clone --branch "$BRANCH" --single-branch "$REPO" "$BASE"
fi
as_app python3 -m venv "$BASE/venv"
as_app "$BASE/venv/bin/pip" install --quiet --upgrade pip
as_app "$BASE/venv/bin/pip" install --quiet -r "$APP/requirements.txt"

echo "== Logins"
if [ ! -f "$PASSWORDS" ]; then
  if [ -n "${PREDICTOR_PASSWORD:-}" ]; then
    printf '%s\n' "$PREDICTOR_PASSWORD" | htpasswd -B -i -c "$PASSWORDS" "$FIRST_LOGIN"
  else
    echo "Choose a password for $FIRST_LOGIN:"
    htpasswd -B -c "$PASSWORDS" "$FIRST_LOGIN"
  fi
fi
chown root:www-data "$PASSWORDS"
chmod 640 "$PASSWORDS"

echo "== App service"
install -m 644 "$APP/deploy/football-predictor.service" /etc/systemd/system/football-predictor.service
install -m 644 "$APP/deploy/odds-snapshot.service" /etc/systemd/system/odds-snapshot.service
install -m 644 "$APP/deploy/odds-snapshot.timer" /etc/systemd/system/odds-snapshot.timer
systemctl daemon-reload
systemctl enable football-predictor
systemctl restart football-predictor
systemctl enable --now odds-snapshot.timer   # SportyBet odds log, every 2 hours

echo "== Web server"
sed "s/__DOMAIN__/$DOMAIN/g" "$APP/deploy/nginx.conf" > /etc/nginx/sites-available/football-predictor
ln -sf /etc/nginx/sites-available/football-predictor /etc/nginx/sites-enabled/football-predictor
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "== Firewall (SSH, HTTP, HTTPS only)"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "== HTTPS"
if [ "$EMAIL" = "-" ]; then contact=(--register-unsafely-without-email); else contact=(-m "$EMAIL"); fi
if certbot --nginx -d "$DOMAIN" "${contact[@]}" --agree-tos --redirect --non-interactive; then
  echo "HTTPS is on."
else
  echo "HTTPS failed: check that $DOMAIN points at this server, then run: certbot --nginx -d $DOMAIN"
fi

echo "== First data download and backtest (takes several minutes)"
cd "$APP"
as_app "$BASE/venv/bin/python" -m predictor upcoming --days 2 \
  --leagues E0 SP1 I1 D1 F1 E1 N1 P1 B1 T1 SC0 D2 I2 SP2 F2 G1 >/dev/null || true
as_app "$BASE/venv/bin/python" -m predictor backtest --seasons 2024 2025 >/dev/null || true

echo
echo "Done. Open https://$DOMAIN and log in as $FIRST_LOGIN."
echo "Add a friend:  bash $APP/deploy/friends.sh add NAME"
echo "Update later:  bash $APP/deploy/update.sh"
