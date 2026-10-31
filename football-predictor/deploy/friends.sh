#!/usr/bin/env bash
# Manage who can log in. Run as root on the server; changes apply at once.
#
#   bash friends.sh add NAME      asks for their password (also resets an existing one)
#   bash friends.sh remove NAME
#   bash friends.sh list
set -euo pipefail
PASSWORDS=/etc/nginx/predictor.htpasswd

case "${1:-}" in
  add)    htpasswd -B "$PASSWORDS" "${2:?usage: friends.sh add NAME}" ;;
  remove) htpasswd -D "$PASSWORDS" "${2:?usage: friends.sh remove NAME}" ;;
  list)   cut -d: -f1 "$PASSWORDS" ;;
  *)      echo "usage: friends.sh add NAME | remove NAME | list"; exit 1 ;;
esac
