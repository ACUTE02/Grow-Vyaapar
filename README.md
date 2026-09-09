# LocalAI OS

Billing, inventory and customers for small Indian retail stores, with an
autonomous marketing agent and two machine-learning models on top.

**One codebase runs a kirana store, a chemist and a clothing shop.** They differ
only by rows in a config table: thresholds, feature flags, product fields,
reminder rules, job types, loyalty rates and copy tone. There is no
`if vertical == ...` anywhere outside `backend/app/verticals/` - a test fails the
build if a vertical name ever leaks into a service, agent, router or model.

**The marketing agent is autonomous.** It reads what billing and inventory
already produce, decides who to contact and what to promote, and writes only to
its own tables. Completing a sale is itself the trigger. It drafts every night -
and it never sends: delivery is always an explicit human action.

![System architecture](docs/architecture.png)

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

In a second terminal, the web app (Next.js):

```bash
cd web
npm install
npm run dev
```

API on <http://127.0.0.1:8000> (`/docs`), app on <http://localhost:3000>.
Sign in as **`owner@localai.demo`** with password **`localai123`**.
No LLM key is needed for any of it.

Or start both at once:

```bash
.venv\Scripts\python.exe dev.py
```

The Streamlit front end this project began with has been retired. Every page it
had, including the jobs board, expiry and purchasing, now lives in `web/`.

Full click path: **[docs/DEMO.md](docs/DEMO.md)**.

---

## What it does

### Shop keeping
POS with per-line GST, stock decrement in one transaction, sequential invoice
numbers and a PDF invoice. Customers with an append-only record log
(prescriptions, measurements). A catalog whose product fields are defined by the
vertical. Batches with first-expired-first-out picking and near-expiry alerts
where the trade needs them. A jobs board for alterations, lens fittings and cake
orders. Suppliers, purchase orders and receiving stock.

### Campaign posters
A shopkeeper picks an occasion and types an offer; the poster shown to the
customer actually says it. A generated background image (Pollinations) and the
offer text, occasion, store name and address are composited on top with Pillow,
so the words are always legible rather than left to a diffusion model to render.
Regenerate before publishing, Unpublish to make a change, download the result as
an image to send yourself - nothing here posts anywhere automatically.

### The agent
| Agent | Decides |
|---|---|
| `segmentation` | who is New, Regular, VIP or Inactive, by this store's thresholds |
| `reminders` | who to contact, why, and in what words |
| `insights` | the three things worth doing this week, quoting real figures |
| `campaigns` | what to promote, with a caption and a poster |
| `churn` | who is about to stop coming - **before** they lapse |
| `forecasting` | what runs out this cycle, and what is going stale |
| `attribution` | what the last campaign plausibly earned |

### The models
- **Churn** - logistic regression per store, self-labelled from history, seeded
  and reproducible, with the metrics and coefficients in `model_runs` and an
  honest [model card](docs/model-card-churn.md).
- **Stock forecast** - a random forest trained per store, but only served where
  it actually beats a predict-the-mean baseline on held-out data; where it
  doesn't (measured, not assumed), the reorder table falls back to a moving
  average and says so on screen instead of showing a badge the evidence
  doesn't support. Full numbers and limitations in the
  [model card](docs/model-card-stock-forecast.md).

### The guard rails
Consent per customer, a hard daily send cap, a rate limit, roles enforced in the
API rather than hidden in the UI, and an audit row for every mutating request
with before/after values on the ones that matter.

---

## The proof, in one table

| Claim | Where to check it |
|---|---|
| Vertical behaviour is data, not code | `pytest tests/test_vertical_isolation.py` |
| Configuration is read in exactly one place | `app/verticals/context.py`, used by everything |
| The same query gives different answers per store | `tests/test_catalog.py::test_dead_stock_uses_each_stores_own_window` |
| A sale never oversells | `tests/test_billing.py::test_oversell_returns_409_and_changes_nothing` |
| The agent reacts without being asked | `tests/test_segmentation.py::test_completing_a_sale_creates_a_review_request_with_no_manual_action` |
| No model output is ever load-bearing | `tests/test_intelligence.py`, `tests/test_llm_client.py` |
| The churn model does not cheat | `tests/test_churn.py::test_features_ignore_everything_after_the_cutoff` |
| A cashier cannot create a product by hand | `tests/test_auth.py::test_a_cashier_cannot_create_a_product_even_by_hand` |
| Lists do not issue a query per row | `tests/test_performance.py` |
| It runs on Postgres too | `TEST_DATABASE_URL=postgresql+psycopg://... pytest` |

```bash
cd backend && pytest -q          # 314 tests
```

---

## How the vertical layer works

```
app/verticals/definitions/<code>.json     eight files: thresholds, flags, schema, tone
        │  loader.py  (upsert into the verticals table)
        ▼
verticals + store_config rows             per-store overrides merged over defaults
        │  context.py  (the ONE place config is read)
        ▼
StoreContext                              handed to every service, router and agent
```

Six extension points, none of them Python: `default_config`, `feature_flags`,
`product_schema`, `unit_labels`, `prompt_profile`, and `reminder_rules`. Details
in [docs/architecture.md](docs/architecture.md).

Switching the store selector changes: thresholds, the dead-stock and near-expiry
windows, the add-product form's fields, the unit label on every quantity, which
reminder kinds fire, which pages appear in the sidebar, the loyalty rate, the job
types on offer, and the tone of every generated sentence.

---

## Without an LLM key

Every LLM call has a non-LLM fallback, so a network failure never breaks a
screen:

- **Reminders** fall back to the `message_templates` row for that rule
- **Insights** fall back to the same three slots written by Python from the same
  figures, or the last cached row
- **Campaigns** fall back to template copy and a template visual prompt

`llm/client.py` tries providers in `LLM_PROVIDER_ORDER` (default `gemini,groq`),
and is built for a free tier:

- **Batched** - one call drafts up to 20 messages keyed by customer id; a
  nightly run over three stores drafts ~163 messages in 12 calls
- **Throttled** - a token bucket sleeps rather than getting throttled
- **Cached** - identical prompts are answered from `llm_cache`, so the second
  nightly run makes no network calls at all
- **429-tolerant** - exponential backoff, then the next provider, then the
  template. It never surfaces as a 500.

Poster images come from Pollinations - no key, no SDK.

---

## Running the pieces

```bash
cd backend
uvicorn app.main:app --reload     # API
python scheduler.py               # nightly agent run, 02:00 IST
python scheduler.py --now         # one pass immediately
python -m scripts.seed            # deterministic demo data
python -m scripts.rehearse        # walk the demo path, non-zero exit on failure
python -m scripts.benchmark       # time the real queries
python -m scripts.backup          # pg_dump or SQLite online backup
python -m scripts.make_er_diagram # redraw docs/er-diagram.png from the models
python -m scripts.make_diagrams   # redraw the architecture and flow diagrams
```

---

## Documentation

| Document | What is in it |
|---|---|
| [docs/DEMO.md](docs/DEMO.md) | the click path, the accounts, a recording shot list |
| [docs/architecture.md](docs/architecture.md) | the six extension points, layer rules, agent boundaries |
| [docs/model-card-churn.md](docs/model-card-churn.md) | features, labels, metrics, coefficients, limitations |
| [docs/model-card-stock-forecast.md](docs/model-card-stock-forecast.md) | the reorder model, its baseline, and why it's switched off for one store |
| [docs/campaign-offer-poster-plan.md](docs/campaign-offer-poster-plan.md) | how offer text gets composited onto the generated poster |
| [docs/performance.md](docs/performance.md) | measured query times, the index before/after, N+1 guards |
| [docs/deployment.md](docs/deployment.md) | Postgres, Docker, Render, backups, what is verified |
| [docs/api-guide.md](docs/api-guide.md) | what each of the eleven routers is for |
| [docs/frontend-architecture.md](docs/frontend-architecture.md) | why Streamlit was replaced, and how the Next.js app is built |
| [docs/postgres-migration.md](docs/postgres-migration.md) | runbook for moving off SQLite, with rollback |
| `/docs` on a running API | the generated reference |

![Data model](docs/er-diagram.png)

---

## Layout

```
backend/app/verticals/   definitions, loader, StoreContext, attribute validation
backend/app/models/      config, core, agent, ml, commerce, admin
backend/app/services/    billing, stock, batches, jobs, coupons, loyalty,
                         suppliers, delivery, customers, products, invoice PDF
backend/app/agents/      segmentation, reminders, insights, campaigns,
                         churn, forecasting, attribution
backend/app/llm/         one call(), every prompt in one file
backend/app/delivery/    console (default), Twilio sandbox, WhatsApp Cloud
backend/app/security.py  bcrypt + JWT       app/middleware.py  roles and audit
backend/scripts/         seed, rehearse, benchmark, backup, diagrams
backend/scheduler.py     the nightly pass
backend/app/ratelimit.py in-process throttle for sign-in
web/src/app/             Next.js routes; every page lives under /s/[storeId]
web/src/lib/             api client, Zod schemas, query hooks, session, format
web/src/components/      shell, ui primitives, charts, feature components
dev.py                   starts the backend and the web app together
```

---

## Configuration

Copy `.env.example` to `backend/.env`. Every value has a working default; the
file is only needed to point at Postgres, switch on an LLM, or deploy.

```
DATABASE_URL=sqlite:///./localai.db    # or postgresql+psycopg://...
AUTH_ENABLED=true                      # enforced in the API, not just the UI
JWT_SECRET=change-me                   # generate one per environment
GEMINI_API_KEY=                        # optional
DELIVERY_ADAPTER=console               # console | twilio_wa | whatsapp_cloud
DELIVERY_DAILY_CAP=50                  # a bug cannot spam a real person
```

The seed is deterministic (`random.seed(42)`): running it twice produces
identical data, so a figure quoted in a report is the figure a reviewer sees.

---

## Known gaps, honestly

- **Settings**: store address and WhatsApp number are editable from the UI
  (`PATCH /config/stores/{store_id}`); name, city, GSTIN and language are
  still read-only - no write endpoint accepts changes to them yet.
- **Training the ML models is API-only.** Churn and stock-forecast are
  triggered from `/docs`, not from a button in the app - see
  [docs/feature-checklist.md](docs/feature-checklist.md) for the exact calls.
- **Devanagari offer text** renders as empty boxes on a poster until a Noto
  Sans Devanagari `.ttf` is dropped into `backend/assets/fonts/` - the code
  already looks there first, nothing else to change.

## Not built, on purpose

Mobile apps, offline sync, multi-tenant billing, auto-posting to Instagram or
Facebook (campaigns stop at "published"), a chat assistant, review sentiment
analysis, barcode hardware beyond scanner keyboard input, and anything needing a
paid API tier.
