# Failure-Handling Plan (per step)

The rule: **a step either retries automatically (if the failure is usually temporary) or alerts a human with order, step, reason and next action.** Nothing just stops.

| # | Step | If it fails… | Decision |
|---|---|---|---|
| 0 | Stripe → n8n webhook | n8n down or unreachable | **Retry (Stripe's side)** |
| 1 | Verify payment with Stripe | API timeout / fake event | **Retry 3×, then alert** |
| 2 | Duplicate check | Sheets unavailable | **Retry 3×, then alert** |
| 3 | Claim order ("processing" row) | Sheets unavailable | **Retry 3×, then alert** |
| 4 | Validate order data | Bad email, unpaid, no SKU | **Alert immediately** |
| 5 | Inventory check | Out of stock / unknown SKU | **Alert immediately** |
| 6 | Reserve stock | Sheets unavailable | **Retry 3×, then alert** |
| 7 | Generate invoice PDF | Gotenberg down | **Retry 3×, then alert** |
| 8 | Email customer | Gmail hiccup / auth expired | **Retry 3× with 5 s pause, then alert** |
| 9 | Log final status + alert | Sheets / Telegram down | **Retry 3×, then Error Workflow** |
| — | Low-stock warning | Telegram down | **Retry, then ignore** (it's only a warning) |

## Why each decision

**0. Webhook delivery.** If n8n is offline, Stripe keeps retrying the event for up to 3 days. We don't need to build anything. We reply 200 as soon as the event arrives, so Stripe never waits on our slower steps.

**1. Verify payment with Stripe.** We don't trust the webhook body. We fetch the checkout session from Stripe's API with our secret key. A network blip is temporary, so we retry. If Stripe says the session doesn't exist, someone may be sending fake "paid" events, and a human must look. Verifying also gives us the real line items, quantity and payment status.

**2. Duplicate check (idempotency).** Stripe can send the same event more than once, and so can someone replaying it. We look up the Stripe session id in the Orders sheet. If it's already there, we stop, so we never get a second order, a second stock deduction or a second email. The session id is the key, so even a *different* event for the same checkout is caught.

**3. Claim the order.** Before doing any real work, we write the order as `processing`. If something later crashes in a way we didn't predict, the order is still visible in the sheet, not lost. It also closes the duplicate window early.

**4. Validate order data.** A badly formatted email, an unpaid status, or a product with no SKU won't fix itself on retry. Retrying would only delay the alert, so a human is alerted straight away and the order is marked `needs_attention`.

**5. Inventory check.** Payment received but no stock is the brief's main example of "needs a human". The money is taken, so someone must choose between restocking and refunding. The order is **never** marked fulfilled, and no invoice or confirmation email goes out. Odd data (SKU missing from the sheet, a duplicate SKU row, stock that isn't a number) gets the same treatment. We don't guess.

**6. Reserve stock.** Writing to Sheets usually fails for temporary reasons (rate limit, timeout), so we retry. If it keeps failing, the alert says clearly that *money was taken but stock wasn't reduced*.

**7. Invoice PDF.** Gotenberg being briefly busy or restarting is temporary, so we retry. If it keeps failing, the human knows the invoice is the only missing piece.

**8. Customer email.** Email sends are the classic flaky step, so we use more retries with a longer pause (stretch goal). If it still fails (usually an expired Gmail login), the alert says everything else succeeded and only the email needs resending.

**9. Final log and alert.** These are the steps that report failures, so they get retries too. If they fail anyway, n8n runs the separate **Error Workflow**, which sends a Telegram message with the failed node, the error and a direct link to the execution.

## What the human sees

Every alert contains: order number, Stripe session id, customer, item, amount, **which step failed, why, and what to do next**, plus the n8n execution id. It's enough to act without opening the logs.

## Known limits (worth saying on camera)

- Google Sheets isn't a real database. Two orders for the same item in the same second could both read the same stock number. For real volume, move inventory to Supabase and decrement it in one atomic query.
- Only single-product orders are automated. Multi-item orders are flagged for a human instead of being guessed at.
