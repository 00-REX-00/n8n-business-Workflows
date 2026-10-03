# Upwork Profile Kit: n8n Automation

Paste-ready copy for every profile field, plus the reasons behind it. Character limits are Upwork's.

---

## 1. Title (70 char max)

**Pick one:**

```
n8n Automation Expert | Stripe, CRM & AI Workflows That Don't Break
```
```
n8n Developer | Business Automation, Webhooks, APIs & AI Agents
```
```
n8n & Zapier Automation | Order, Lead & Invoice Workflows | AI Agents
```

Why: clients search for the tool by name ("n8n"). Put it first, then the outcomes they're paying for. Avoid vague titles like "Virtual Assistant | Data Entry | Automation | Web Design". A title that lists many unrelated skills tells the client you're not a specialist.

---

## 2. Hourly rate

- **Start at $25–35/hr.** Fixed-price small jobs: **$80–250.**
- Goal: 3–5 completed jobs with 5-star reviews, then raise to $45–60/hr.
- Don't go below $20. Very low rates bring difficult clients and signal low quality.

---

## 3. Overview

Upwork shows only the **first ~200 characters** in search results and proposals. Those lines decide whether the client clicks.

```
I build n8n automations that run your business while you sleep, and tell you the moment something goes wrong instead of failing silently.

Most automations work in the demo and break in real life: a webhook fires twice and the customer gets charged twice, an API times out and an order disappears, an email fails and nobody notices for a week. I design for those cases from the start.

WHAT I BUILD
• Order & payment workflows: Stripe/PayPal → stock check → invoice PDF → customer email → order log
• Lead capture & CRM sync: forms, Facebook/LinkedIn leads, HubSpot, Pipedrive, GoHighLevel, Airtable, Google Sheets
• AI workflows: OpenAI/Claude for email replies, lead qualification, document extraction, chatbots, AI agents
• Reporting & alerts: daily summaries and instant Telegram/Slack/email alerts
• Fixing and migrating: broken n8n flows, Zapier/Make → n8n migrations (cut your monthly bill)

RECENT EXAMPLE
An event-driven order pipeline: a Stripe payment triggers payment verification, duplicate protection, stock check and reservation, PDF invoice, customer email and order logging. Every step either retries automatically or sends a Telegram alert naming the order, the failed step, the reason and the next action. Replaying the same Stripe event never creates a second order. (See my portfolio.)

HOW I WORK
1. A short call or message thread to map your current process
2. A written plan: each step, what can fail, and what happens when it does
3. Build, test with real data, and hand over with a walkthrough video
4. 14 days of free fixes after delivery

You get the workflow JSON, documentation, and a video explaining how it works, so you're never locked in to me.

TOOLS
n8n (cloud & self-hosted/Docker), JavaScript, REST APIs & webhooks, Stripe, Google Workspace, Airtable, Notion, HubSpot, Slack, Telegram, OpenAI, Claude, Supabase.

Send me a description of the process you want automated. I'll reply with how I'd build it and a fixed price.
```

> **Edit before pasting:** remove any tool from the TOOLS line or the "WHAT I BUILD" list that you haven't actually used or can't learn in a day. Clients test this in interviews.

---

## 4. Skills (add up to 15, in this order)

1. n8n
2. Automation
3. Workflow Automation
4. API Integration
5. Zapier
6. Make.com
7. JavaScript
8. Webhooks
9. Stripe
10. Google Sheets
11. AI Agent Development
12. OpenAI API
13. CRM Automation
14. Airtable
15. Docker

Remove any unrelated skills (graphic design, data entry, writing, etc.). They pull you into the wrong search results.

---

## 5. Portfolio item #1 (build it from this repo)

**Title:**
```
Stripe Order-to-Fulfillment Automation (n8n) with Failure Alerts
```

**Description:**
```
Problem: an online store needed paid orders fulfilled automatically, without double-processing, selling stock it didn't have, or failing silently.

Solution: an event-driven n8n workflow triggered by a real Stripe webhook:
• Verifies the payment against Stripe's API (doesn't trust the webhook body)
• Ignores duplicate events: replaying the same event never creates a second order
• Checks and reserves stock; out-of-stock orders go to "needs attention", never "fulfilled"
• Generates a PDF invoice and emails the customer
• Logs every order in Google Sheets
• Every failure-prone step either retries or sends a Telegram alert with the order, failed step, reason and next action

Stack: n8n (self-hosted, Docker), Stripe, Gotenberg (PDF), Gmail, Google Sheets, Telegram, JavaScript.
```

**Role:** Automation developer
**Skills:** n8n, Stripe, Workflow Automation, API Integration, JavaScript

**Images to upload (4–6):**
1. **Cover:** screenshot of the full workflow on the n8n canvas (zoom so node names are readable)
2. The ASCII flow diagram from the README, redrawn as a clean image (or a canvas screenshot)
3. A Telegram alert message on your phone (out-of-stock example)
4. The generated PDF invoice
5. The Google Sheets order log showing `fulfilled` and `needs_attention` rows
6. The failure-plan table from `docs/failure-plan.md`

**Video:** record a 2–3 minute Loom using `docs/video-script.md`. A video in the portfolio is the strongest proof a client can see before hiring.

### Portfolio items #2 and #3 (build these next, 1–2 days each)
You need 3 portfolio items minimum. Build these because they match the most common job posts:
- **AI lead qualifier:** form/webhook → OpenAI scores and enriches the lead → hot leads to CRM + Slack alert, cold leads to a nurture sheet
- **AI email assistant:** Gmail trigger → classify (sales / support / spam) → draft reply → save as draft or send to Slack for approval

---

## 6. Project Catalog (fixed-price offers clients buy directly)

**Project 1**
```
I will build a custom n8n automation workflow for your business
```
- Starter, $120: 1 workflow, up to 5 steps, 2 apps, 3-day delivery
- Standard, $280: up to 12 steps, error alerts, documentation, 5 days
- Advanced, $550: multi-workflow system, AI step, error handling, video walkthrough, 7 days

**Project 2**
```
I will fix or debug your broken n8n workflow
```
- $60 for 1 workflow, 2-day delivery

**Project 3**
```
I will migrate your Zapier or Make automations to n8n
```
- $150 for up to 3 zaps/scenarios

---

## 7. Other fields

- **Photo:** clear face, plain background, smiling, good light. No logos or avatars.
- **Video intro (60–90s):** who you are, what you automate, one example, "message me". Profiles with a video get noticeably more invites.
- **Availability:** "More than 30 hrs/week" and turn on **"Available now"**.
- **English level:** set it honestly; clients filter on it.
- **Profile completeness:** must be 100% (Upwork ranks incomplete profiles lower).
- **Skill certifications / Skill Tests:** if Upwork offers anything for automation or JavaScript, take it.

---

## 8. Why 2+ years with no hires: the usual causes

Check yourself against each one:

| Problem | Fix |
|---|---|
| Generalist profile (many unrelated skills) | One niche: n8n automation. Everything on the profile supports it. |
| No portfolio or weak portfolio | 3 real, documented projects with screenshots and a video (section 5) |
| Generic or long proposals | Tailored proposals that start with the client's problem (section 9) |
| Applying to jobs with 50+ proposals | Apply only to jobs posted in the **last 1–2 hours** with **<15 proposals** |
| Applying to jobs requiring "Expert" with $1k+ budgets | Target small fixed-price jobs ($50–500) and clients with a verified payment method |
| Low Job Success / no activity | First jobs are about reviews, not money |
| Account location/payment not verified | Verify identity and payment method so you appear in search |

---

## 9. Proposal template (adapt every time, never send it as-is)

```
Hi [name if shown],

[One sentence restating THEIR problem in your words, showing you read the post.]

I recently built [closest portfolio example] that [result]. [Link to portfolio item.]

For your project I'd:
1. [Concrete step specific to their apps]
2. [Concrete step]
3. [Error handling: what happens when X fails]

Quick question: [one smart question about their setup, e.g. "Is n8n self-hosted or cloud?"]

I can have a first working version in [X days].

[Your name]
```

Rules:
- Under 150 words. The first 2 lines are all they see in the list.
- Never start with "Hi, I'm X and I have Y years of experience."
- Always ask one question. Replies to it start a conversation, and conversations lead to hires.
- Use Freelancer Plus boosts only on jobs that fit you well and were posted recently.
