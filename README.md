# n8n Business Workflows

## Order-to-Fulfillment Pipeline (event-driven, fails loudly)

A Stripe test-mode payment triggers the workflow. It verifies the payment, skips duplicates, checks and reserves stock, generates a PDF invoice, emails the customer and logs the order. **Every step either retries or alerts a human** with the order, the failed step, the reason and what to do.

```
Stripe Webhook ─► Extract Event ─► Fetch Session from Stripe ─► Normalize Order ─► Find Existing Order ─► Already Processed? ──yes──► stop
                                                                                                             │ no
      ┌──────────────────────────────────────────────────────────────────────────────────────────────────────┘
      ▼
 Claim Order ("processing") ─► Order Valid? ─► Look Up Stock ─► Check Stock ─► In Stock? ─► Reserve Stock ─► Invoice HTML ─► PDF ─► Email ─► Mark Fulfilled ─┐
                                   │ no                                           │ no            └─► Low Stock? ─► Telegram warning                          │
                                   ▼                                              ▼                                                                           ▼
                           Flag: Invalid Order                          Flag: Out of Stock            (red error outputs) ─► Describe Failure ─►  Build Log Row
                                                                                                                                            ├─► Update Order Log (Sheets)
                                                                                                                                            └─► Needs Human? ─► Telegram alert
```

| Path | What it's for |
|---|---|
| `workflows/order-fulfillment-pipeline.json` | **Main workflow**. Copy it and paste onto the n8n canvas (Ctrl/Cmd+V) |
| `workflows/order-error-handler.json` | Safety-net error workflow |
| `docs/build-guide.md` | Setup, paste instructions, tests, and a stage-by-stage build |
| `docs/video-script.md` | Scene-by-scene script for explaining the build |
| `docs/failure-plan.md` | Written retry-or-alert decision for every step (brief deliverable) |
| `src/code-nodes/*.js` | The JavaScript inside each Code node, readable |
| `sheets/*.csv` | Inventory (sample stock) and Orders (headers) tabs |
| `docker-compose.yml` | n8n + Gotenberg (free HTML→PDF) |
| `scripts/build-workflows.js` | Regenerates the workflow JSON (optionally with your Sheet ID / Telegram chat ID) |
| `scripts/replay-event.sh` | Re-sends a Stripe event to prove duplicates are ignored |

**Stack (all free):** n8n self-hosted · Stripe test mode · Gotenberg · Gmail · Google Sheets · Telegram.

Quick start: see [docs/build-guide.md](docs/build-guide.md), Parts A and B.

### Brief checklist
- [x] Triggered by a real Stripe webhook event, not a manual click
- [x] Every failure-prone step has a retry or alert plan ([failure-plan.md](docs/failure-plan.md))
- [x] Out-of-stock orders are marked `needs_attention`, never `fulfilled`
- [x] Alerts include order, step, reason and next action
- [x] Replaying the same event doesn't create a second order
- [x] Stretch: retry-with-delay on email · separate low-stock warning · "Needs attention" filter view
