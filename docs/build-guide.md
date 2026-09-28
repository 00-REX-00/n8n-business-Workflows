# Build Guide: Order-to-Fulfillment Pipeline

Two ways to use this guide:
- **Fast:** do Part A (setup) and Part B (paste the workflow). You're done.
- **For the video:** do Part A, then build it live with Part C, one stage at a time. Keep the pasted version in another tab as your reference.

---

## Part A – One-time setup (all free)

### A1. Start n8n + the PDF service
```bash
docker compose up -d
```
Open http://localhost:5678 and create your owner account.
(n8n has no built-in HTML-to-PDF node, so `docker-compose.yml` also starts **Gotenberg**, a free, open-source PDF service the workflow calls at `http://gotenberg:3000`.)

### A2. Google Sheet
1. Create a spreadsheet called **Store Ops**.
2. Tab 1 → rename to **Inventory** → File ▸ Import `sheets/inventory.csv` (*Replace current sheet*).
3. Tab 2 → rename to **Orders** → import `sheets/orders.csv` (headers only).
4. Copy the sheet ID from the URL: `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`.
5. *(Stretch: admin view)* On the Orders tab: Data ▸ Create a filter view ▸ `status` is not `fulfilled`. Name it **Needs attention**.

### A3. Telegram bot (failure alerts)
1. In Telegram, message **@BotFather** → `/newbot` → copy the **bot token**.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": …}`. That's your **chat ID**.

### A4. Stripe (test mode)
1. Create a free Stripe account and make sure **Test mode** is ON.
2. **Product catalogue → Add product** (one-off price). Create three products and add **metadata** `sku`:

   | Product | Price | Metadata `sku` |
   |---|---|---|
   | Ceramic Mug | 18.00 | `MUG-001` |
   | Logo T-Shirt | 25.00 | `TEE-001` |
   | Limited Edition Poster | 40.00 | `POSTER-001` (0 in stock → failure demo) |

3. For each product: **Create payment link**.
4. **Developers → API keys** → copy the **Secret key** (`sk_test_…`).
5. Install the **Stripe CLI** and run `stripe login`.

### A5. Credentials in n8n (Overview ▸ Credentials ▸ Create)
- **Stripe API** → secret key `sk_test_…`
- **Google Sheets OAuth2 API**
- **Gmail OAuth2**
- **Telegram API** → bot token

---

## Part B – Paste the finished workflow

1. Put your IDs in, either by building with them:
   ```bash
   SHEET_ID=your_sheet_id TELEGRAM_CHAT_ID=your_chat_id node scripts/build-workflows.js
   ```
   …or by opening the JSON files and replacing `YOUR_GOOGLE_SHEET_ID` and `YOUR_TELEGRAM_CHAT_ID`.
2. **Error handler first:** new workflow → open `workflows/order-error-handler.json`, select all, copy → click the n8n canvas → **Ctrl/Cmd + V**. Pick the Telegram credential, then save.
3. **Main workflow:** new workflow → paste `workflows/order-fulfillment-pipeline.json` the same way.
4. Open each node with a ⚠️ and pick its credential: *Fetch Session from Stripe* (Credential Type = Stripe API), 6 Google Sheets nodes, *Email Customer*, *Low Stock Warning*, *Alert Human*.
5. **Settings (⋯ ▸ Settings) → Error workflow** → *Order Pipeline - Error Handler*. Save.
6. **Activate** the workflow (toggle at the top).
7. Forward Stripe events to it (keep this terminal open while you demo):
   ```bash
   stripe listen --events checkout.session.completed \
     --forward-to http://localhost:5678/webhook/stripe-order
   ```
   *(n8n Cloud instead: Stripe ▸ Developers ▸ Webhooks ▸ Add endpoint → your **Production URL**, event `checkout.session.completed`. Gotenberg must then be hosted somewhere reachable.)*

### Test all the paths

| Test | How | Expected |
|---|---|---|
| ✅ Happy path | Pay the **Mug** link with card `4242 4242 4242 4242`, any future date, any CVC | Email with PDF invoice · Orders row `fulfilled` · Mug stock 10 → 9 |
| ⚠️ Low stock | Buy the **T-Shirt** (stock 3, reorder 2) | Fulfilled **and** a separate "Low stock" Telegram message |
| 🚨 Out of stock | Buy the **Poster** | **No** email · row `needs_attention` · Telegram alert |
| 🔁 Duplicate | `./scripts/replay-event.sh evt_…` (event id from the `stripe listen` output) | Execution ends at *Duplicate - Stop Here* · no new row |
| 💥 Broken step | `docker compose stop gotenberg`, then buy a Mug | 3 retries → row `failed` at *Generate invoice PDF* · Telegram alert. Then `docker compose start gotenberg` |

---

## Part C – Build it live, stage by stage

Each stage ends with a **✅ checkpoint** to show on camera. To copy a Code node's script, open the matching file in `src/code-nodes/`.
**Retry setting:** node ⚙️ *Settings* tab → *Retry On Fail* ON, *Max Tries* 3, *Wait Between Tries* 2000 ms.
**Error output:** same tab → *On Error* → *Continue (using error output)*. The node gets a second, red output.

### Stage 1 – The event trigger
| Node | Type | Settings |
|---|---|---|
| **Stripe Webhook** | Webhook | Method `POST`, Path `stripe-order`, Respond *Immediately* |
| **Extract Event** | Code | paste `01-extract-event.js` |
| **Is Checkout Paid Event?** | If | `{{ $json.event_type }}` *is equal to* `checkout.session.completed`. False → **No Operation** named *Ignore Other Events* |

✅ Click *Listen for test event*, run `stripe listen … --forward-to http://localhost:5678/webhook-test/stripe-order`, pay a link, and show the event arriving by itself.

### Stage 2 – Verify, dedupe, claim
| Node | Type | Settings |
|---|---|---|
| **Fetch Session from Stripe** | HTTP Request | GET `https://api.stripe.com/v1/checkout/sessions/{{ $json.session_id }}` · Auth: *Predefined → Stripe API* · Query `expand[]` = `line_items.data.price.product` · **Retry + error output** |
| **Normalize Order** | Code | paste `02-normalize-order.js` |
| **Find Existing Order** | Google Sheets ▸ Get row(s) | Sheet `Orders`, filter `order_id` = `{{ $json.order_id }}` · Settings: **Always Output Data** ON · **Retry + error output** |
| **Already Processed?** | If | `{{ $json.order_id }}` *is not empty*. True → No Operation *Duplicate - Stop Here* |
| **Processing Row** | Edit Fields (Set) | order fields from `{{ $('Normalize Order').first().json.… }}`, `status` = `processing` |
| **Claim Order** | Google Sheets ▸ Append or Update | Sheet `Orders`, *Map Automatically*, match on `order_id` · **Retry + error output** |

✅ Show the `processing` row appearing in the sheet.

### Stage 3 – Inventory
| Node | Type | Settings |
|---|---|---|
| **Order Valid?** | If | `{{ $('Normalize Order').first().json.valid }}` *is true* |
| **Flag: Invalid Order** | Set (false branch) | `status` needs_attention, `failed_step` Validate order, `reason` `{{ $('Normalize Order').first().json.issues }}`, `action` |
| **Look Up Stock** | Google Sheets ▸ Get row(s) | Sheet `Inventory`, filter `sku` = `{{ $('Normalize Order').first().json.sku }}` · **Always Output Data** · **Retry + error output** |
| **Check Stock** | Code | paste `03-check-stock.js` |
| **In Stock?** | If | `{{ $json.in_stock }}` *is true* |
| **Flag: Out of Stock** | Set (false branch) | `status` needs_attention, `failed_step` Inventory check, `reason` `{{ $json.reason }}`, `action` |
| **Reserve Stock** | Google Sheets ▸ Update Row | Sheet `Inventory`, match `sku`, set `stock` = `{{ $json.new_stock }}` · **Retry + error output** |
| **Low Stock?** → **Low Stock Warning** | If → Telegram | `{{ $('Check Stock').first().json.low_stock }}` is true · Telegram: On Error *Continue* |

✅ Show the stock number going down in the Inventory tab.

### Stage 4 – Invoice + email
| Node | Type | Settings |
|---|---|---|
| **Build Invoice HTML** | Code | paste `04-build-invoice-html.js` (outputs a file `index.html`) |
| **Render Invoice PDF** | HTTP Request | POST `http://gotenberg:3000/forms/chromium/convert/html` · Body *Form-Data* → type *n8n Binary File*, name `files`, input field `data` · Header `Gotenberg-Output-Filename` = `{{ $json.order_number }}` · Response format *File* · **Retry + error output** |
| **Email Customer** | Gmail ▸ Send | To `{{ $('Normalize Order').first().json.customer_email }}` · Attachments: `data` · **Retry (5000 ms) + error output** |
| **Mark Fulfilled** | Set | `status` fulfilled |

✅ Show the email and open the PDF invoice.

### Stage 5 – One ending for every path
| Node | Type | Settings |
|---|---|---|
| **Describe Failure** | Code | paste `05-describe-failure.js`. Connect **every red error output** here |
| **Build Log Row** | Code | paste `06-build-log-row.js`. Connect *Mark Fulfilled*, both *Flag* nodes and *Describe Failure* here |
| **Needs Human?** → **Alert Human** | If → Telegram | `{{ $json.status }}` *is not equal to* `fulfilled` · message template from the pasted workflow · Retry |
| **Update Order Log** | Google Sheets ▸ Append or Update | Sheet `Orders`, *Map Automatically*, match on `order_id` · Retry |

Finally: build the **Error Handler** workflow (Error Trigger → Telegram) and select it under *Settings → Error workflow*.

✅ Run the 5 tests from Part B.
