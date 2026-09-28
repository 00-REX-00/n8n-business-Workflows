#!/usr/bin/env bash
# Re-send a real Stripe event to n8n to prove duplicates are ignored.
# Usage: ./scripts/replay-event.sh evt_123 [webhook_url]
# Needs the Stripe CLI, logged in with `stripe login` (test mode).
set -euo pipefail

EVENT_ID=${1:?usage: replay-event.sh <evt_id> [webhook_url]}
URL=${2:-http://localhost:5678/webhook/stripe-order}

stripe events retrieve "$EVENT_ID" \
  | curl -sS -X POST -H 'Content-Type: application/json' --data-binary @- "$URL"
echo
echo "Replayed $EVENT_ID -> $URL. The new execution should end at 'Duplicate - Stop Here'."
