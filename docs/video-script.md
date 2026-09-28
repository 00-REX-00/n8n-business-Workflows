# Video Script: "An n8n Order Pipeline That Fails Loudly"

**Length:** about 18–22 min · **Follow along:** `docs/build-guide.md` (Part C)
Each scene gives **what to show** and **what to say**. Put the talking points in your own words.

---

### Scene 1 – Hook (0:00–0:45)
**Show:** the finished workflow. Pay for a mug in Stripe; the email with the PDF invoice arrives, and a sheet row turns `fulfilled`. Then buy the poster, and your phone buzzes with a Telegram alert.
**Say:**
> "When someone pays, this workflow checks stock, makes an invoice, emails the customer and logs the sale. The important part: when something goes wrong, it doesn't fail quietly. It tells me what broke, for which order, and what to do about it."

### Scene 2 – Event-driven vs conversational (0:45–2:00)
**Show:** a simple slide: *Chat bot = a person is watching* vs *Webhook = nobody is watching*.
**Say:**
- "My last builds started when someone typed a message. If it broke, they'd just try again."
- "This one starts because a **payment** happened. Nobody is watching. If the invoice step silently dies, I find out when an angry customer emails me."
- "So today's lesson isn't really the nodes. It's **thinking about failure before building**."

### Scene 3 – Plan on paper first (2:00–4:00)
**Show:** the table in `docs/failure-plan.md` (or draw it).
**Say:**
- Walk the chain: payment → verify → dedupe → stock → invoice → email → log.
- For each step ask: **"What if this fails? Retry, or tell a human?"**
- Rule of thumb: **temporary problem → retry** (network, email hiccup). **Wrong-data or business problem → human** (out of stock, bad email). Retrying won't create stock.
- Three things we won't assume: the email is well formatted, the stock data is fresh, the webhook only fires once.

### Scene 4 – Setup tour (4:00–5:30)
**Show:** the Inventory and Orders tabs, the Stripe products with `sku` metadata, `docker compose up`, the Telegram bot.
**Say:** "Everything here is free. Stripe test mode means no real money moves."

### Scene 5 – Stage 1: the trigger (5:30–7:30)
**Build:** Webhook → Extract Event → Is Checkout Paid Event?
**Show:** `stripe listen` in a terminal. Pay a test link and the event lands in n8n with nobody clicking *Execute*.
**Say:**
- "The webhook answers Stripe instantly. If n8n were down, Stripe would keep retrying for 3 days. That's failure handling we get for free."
- "We only care about `checkout.session.completed`. Everything else is politely ignored."

### Scene 6 – Stage 2: don't trust, verify; don't do it twice (7:30–11:00)
**Build:** Fetch Session → Normalize Order → Find Existing Order → Already Processed? → Processing Row → Claim Order
**Say:**
- **Verify:** "Anyone could POST a fake 'payment succeeded' to my URL. So I ask Stripe directly with my secret key. That also gives me the real product and quantity."
- **Normalize:** "Clean the email, pull out the SKU, and list anything wrong in `issues`." Point at the regex and the `issues` list.
- **Idempotency:** "Stripe can send the same event twice. I use the checkout session id as the order id. Seen it already? Stop."
- **Claim:** "Before doing anything risky, I write the order as `processing`. If something crashes later, the order is still visible, not lost."
- Show the node **Settings tab**: Retry On Fail + *Continue (using error output)*. "This red output is where failures go instead of stopping the workflow."

### Scene 7 – Stage 3: inventory (11:00–13:30)
**Build:** Order Valid? → Look Up Stock → Check Stock → In Stock? → Reserve Stock (+ Low Stock branch)
**Say:**
- "Out of stock is **not** retried. The customer has paid, so a human must decide: restock or refund."
- Walk through `Check Stock`: unknown SKU, duplicate SKU, stock that isn't a number. "When in doubt, ask a human. Don't guess."
- "Low stock is a separate warning. The order still goes through, but I get a heads-up to reorder."
- Honest note: "Sheets isn't a real database, so two orders in the same second could clash. Supabase fixes that."

### Scene 8 – Stage 4: invoice + email (13:30–16:00)
**Build:** Build Invoice HTML → Render Invoice PDF → Email Customer → Mark Fulfilled
**Say:**
- "n8n doesn't ship an HTML-to-PDF node, so I run Gotenberg, a free open-source PDF service in Docker."
- "Email is the classic flaky step: 3 tries with a 5-second pause, and only then does a human get told."
- Open the PDF on screen.

### Scene 9 – Stage 5: every path ends in one place (16:00–18:00)
**Build:** Describe Failure → Build Log Row → Needs Human? → Alert Human / Update Order Log, plus the Error Handler workflow.
**Say:**
- "All red error outputs flow into **Describe Failure**. It works out which step broke and writes a plain-English 'what to do'."
- "Success, needs-attention, failed: everything becomes **one row** in the Orders sheet. Anything not fulfilled pings Telegram."
- "And if even the alert fails, the Error Workflow is the last safety net."

### Scene 10 – Prove it (18:00–21:00)
Run the tests from the build guide, Part B, on camera:
1. ✅ **Mug** → email + PDF + `fulfilled` + stock goes down
2. 🚨 **Poster** → no email, `needs_attention`, Telegram alert. Read the alert out loud: order, step, reason, action.
3. 🔁 **Replay** the mug event → *Duplicate - Stop Here*, no second row
4. 💥 **Stop Gotenberg**, buy a mug → watch 3 retries → `failed` at *Generate invoice PDF* + alert
5. Show the **Needs attention** filter view: the admin view.

### Scene 11 – Wrap-up (21:00–22:00)
**Say:**
> "The nodes were the easy part. The real skill is asking 'what if this breaks?' at every step and deciding: retry, or tell a human. That's the difference between an automation clients trust and one they quietly stop using."

---

## Recording checklist
- [ ] `docker compose up -d`, and Gotenberg running
- [ ] `stripe listen` running in a visible terminal
- [ ] Inventory reset: Mug 10, T-Shirt 3, Poster 0 · Orders tab empty
- [ ] Telegram open on your phone or desktop, with notifications on
- [ ] Gmail inbox open (use your own email at checkout)
- [ ] Browser zoom ~125% so node names are readable
- [ ] Workflow **active**, error workflow set in Settings
