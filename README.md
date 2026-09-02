# LocalAI OS

Billing, inventory and customers for small Indian retail stores, with an autonomous marketing
agent on top.

**One codebase runs a kirana store, a chemist and a clothing shop.** They differ only by rows in a
config table: thresholds, feature flags, product fields, reminder rules and copy tone. There is not
one `if vertical == ...` anywhere outside `backend/app/verticals/` - a test fails the build if a
vertical name ever leaks into a service, agent, router or model.

**The marketing agent is autonomous.** It reads what billing and inventory already produce, decides
who to contact and what to promote, and writes only to its own five tables. Completing a sale is
itself the trigger - nobody asks it for anything.

![Data model](docs/er-diagram.png)

---

## Quickstart

Python 3.11 or newer.

```bash
git clone <this repo> && cd localai-os
python -m venv .venv
```

Windows PowerShell: `.venv\Scripts\Activate.ps1` · macOS/Linux: `source .venv/bin/activate`

```bash
pip install -r backend/requirements.txt
cp .env.example backend/.env
cd backend
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd frontend
streamlit run app.py
```

The API is on <http://127.0.0.1:8000> (docs at `/docs`), the app on <http://localhost:8501>.
No API key is needed for any of this - see "Without an LLM key" below.

---

## The four-minute path

Run it once, then switch the store selector to a different vertical and run it again. Nothing is
restarted and no code changes.

| # | Do this | What proves the point |
|---|---|---|
| 1 | **POS** → add items → *Complete sale* | Stock decrements by exactly the sold quantity; the invoice carries this store's unit label (`kg`, `strip`, `piece`) |
| 2 | Stay on POS | A `review_request` reminder is already queued in the Outbox. Nobody asked for it |
| 3 | **Outbox** → *Run reminder check* | The kinds produced differ by vertical: a chemist gets `reorder_due`, a clothing shop gets `revisit_due` and `pickup_ready` |
| 4 | **Dashboard** | Three suggestions, each quoting a figure computed in SQL from the seeded data |
| 5 | **Campaigns** → type an occasion → *Generate* | A caption, hashtags and a poster image built around the three SKUs that have sat longest |

Switching stores also changes: the sidebar configuration panel, the dead-stock window, the
add-product form fields, the navigation (Jobs and Expiry appear only when that flag is on) and the
tone of the copy.

---

## How the vertical layer works

```
app/verticals/definitions/<code>.json     eight files: thresholds, flags, product schema, tone
        │  loader.py  (upsert into the verticals table)
        ▼
verticals + store_config rows             per-store overrides merged over vertical defaults
        │  context.py  (the ONE place config is read)
        ▼
StoreContext                              handed to every service, router and agent
```

A service asks `context.cfg_int("dead_stock_days")`, never "which vertical is this". Adding a ninth
vertical is one JSON file plus reminder-rule rows - no Python.

`tests/test_vertical_isolation.py` parses every `.py` under `app/` outside `app/verticals/` and
fails if any of the eight codes appears in a string literal.

## How the agent works

| Agent | Reads | Writes |
|---|---|---|
| `agents/segmentation.py` | transactions, customers | `segments` |
| `agents/reminders.py` | transactions, jobs, segments, reminder_rules | `reminders` |
| `agents/insights.py` | transactions, stock, segments | `insights` |
| `agents/campaigns.py` | stock, segments | `campaigns` |
| `agents/churn.py` | - | `churn_scores` (phase 2, stub) |

The reminder engine loops over the enabled `reminder_rules` for the store's vertical and evaluates
the rule's **signal**. It knows six signals - a gap since a category purchase, a gap since any
visit, a job marked ready, a completed sale, the Inactive segment, a birthday or anniversary. It
has no idea what a prescription, a batch or an alteration is.

**Python computes every number. The model only writes sentences about numbers it was handed.**
`agents/insights.py` computes week-over-week change, segment counts and the stock lists in SQL, then
passes them into the prompt as literal facts.

## Without an LLM key

Every LLM call has a non-LLM fallback, so a network failure never breaks a screen:

- **Reminders** fall back to the `message_templates` row for that rule's `template_key`
- **Insights** fall back to the same three suggestion slots written by Python from the same figures,
  or to the last cached `insights` row (recomputed at most once every 24 hours)
- **Campaigns** fall back to template copy and a template visual prompt

`llm/client.py` tries providers in the order given by `LLM_PROVIDER_ORDER` (default `gemini,groq`),
with a 10-second timeout and two retries, and returns `None` rather than raising. Set
`GEMINI_API_KEY` or `GROQ_API_KEY` in `backend/.env` to switch the copy from template to
model-written; nothing else changes.

Built for a free tier, three ways:

- **Batched** - one call drafts up to 20 reminder messages, keyed by customer id. Any id the model
  omits keeps its template. A nightly run over three stores drafts ~163 messages in 12 calls.
- **Throttled** - a token bucket (`LLM_RATE_LIMIT_PER_MINUTE`, default 12) sleeps rather than
  letting the provider throttle us.
- **Cached** - identical prompts are answered from `llm_cache` for `LLM_CACHE_HOURS`, so the second
  nightly run makes no network calls at all.

A `429` or quota error backs off exponentially, then falls through to the next provider, then to the
template. It never surfaces as a 500.

Poster images come from Pollinations (`https://image.pollinations.ai/prompt/...`) - no key, no SDK.

---

## Nightly job

```bash
cd backend
python scheduler.py          # APScheduler, fires at 02:00 Asia/Kolkata
python scheduler.py --now    # run one pass immediately and exit
```

Per store: rebuild `daily_sales_summary`, resegment, run the reminder rules, refresh insights. It
calls the same functions the manual buttons call, so the cron and the UI cannot drift apart.

## Tests

```bash
cd backend
pytest -q
```

Covers vertical isolation, the context resolver, catalog attribute validation, billing arithmetic
and stock movement, segmentation, the reminder engine, and every LLM fallback path.

## Layout

```
backend/app/verticals/   definitions, loader, StoreContext, attribute validation
backend/app/models/      config.py, core.py, agent.py
backend/app/services/    billing, stock, invoice PDF, finance rollup, customers, products
backend/app/agents/      segmentation, reminders, insights, campaigns, churn (stub)
backend/app/llm/         one call(), every prompt in one file
backend/app/delivery/    console adapter (default), Twilio WhatsApp behind a flag
backend/scripts/seed.py  three stores, 18 months, fixed seed
backend/scheduler.py     nightly pass
frontend/                Streamlit app
```

## Configuration

Copy `.env.example` to `backend/.env`. Every value has a working default; the file is only needed
to point at Postgres or to switch on an LLM.

```
DATABASE_URL=sqlite:///./localai.db      # or postgresql+psycopg://user:pass@host/db
GROQ_API_KEY=                            # optional
GEMINI_API_KEY=                          # optional
DELIVERY_ADAPTER=console                 # console | twilio_wa
```

The seed is deterministic (`random.seed(42)`): running it twice produces byte-identical data, so a
figure quoted in a report is the same figure a reviewer sees.

## Not in this phase

Churn model, stock forecasting, batch and jobs workflows beyond the tables and their read-only
lists, real WhatsApp/SMS delivery beyond one sandbox message, campaign analytics, coupons, loyalty,
referrals, auth and roles, employee and supplier modules, chat assistant, review analyzer, mobile
app, React.
