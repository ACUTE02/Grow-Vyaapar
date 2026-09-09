# LocalAI OS

Billing, inventory and customers for small Indian retail stores, with an
autonomous marketing agent and two machine-learning models on top.

**One codebase runs eight kinds of shop.** They differ only by rows in a config
table: thresholds, feature flags, product fields, reminder rules, job types,
loyalty rates and copy tone. There is no `if vertical == ...` anywhere outside
`backend/app/verticals/` — a test fails the build if a vertical name ever leaks
into a service, agent, router or model.

**The marketing agent is autonomous, and it never sends.** It reads what billing
and inventory already produce, decides who to contact and what to promote, and
writes only to its own tables. Completing a sale is itself the trigger. Delivery
is always an explicit human action.

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

In a second terminal, the web app:

```bash
cd web
npm install
npm run dev
```

API on <http://127.0.0.1:8000> (`/docs`), app on <http://localhost:3000>.
Sign in as **`owner@localai.demo`**; the demo password is printed by the seed
script. No LLM key is needed for any of it.

Or start both at once:

```bash
.venv\Scripts\python.exe dev.py
```

Full click path: **[docs/demo-guide.md](docs/demo-guide.md)**.

---

## What it does

### Shop keeping
POS with per-line GST, stock decrement in one transaction, sequential invoice
numbers and a PDF invoice. **A required `Idempotency-Key` on checkout**, so a
retried payment returns the original bill instead of billing twice. Stock
adjustments with a reason code and a full audit trail. Customers with an
append-only record log (prescriptions, measurements). A catalog whose product
fields are defined by the vertical. Batches with first-expired-first-out picking
and near-expiry alerts where the trade needs them. A jobs board for alterations,
lens fittings and cake orders. Suppliers, purchase orders and receiving stock.

### Campaign posters
A shopkeeper picks an occasion and types an offer; the poster shown to the
customer actually says it. A generated background image and the offer text,
occasion, store name and address are composited on top with Pillow, so the words
are always legible rather than left to a diffusion model to render. Regenerate
before publishing, unpublish to make a change, download the result — nothing here
posts anywhere automatically.

### The agents
| Agent | Decides |
|---|---|
| `segmentation` | who is New, Regular, VIP or Inactive, by this store's thresholds |
| `reminders` | who to contact, why, and in what words |
| `insights` | the three things worth doing this week, quoting real figures |
| `campaigns` | what to promote, with a caption and a poster |
| `churn` | who is about to stop coming — **before** they lapse |
| `forecasting` | what runs out this cycle, and what is going stale |
| `attribution` | what the last campaign plausibly earned |

### The models
- **Stock forecast** — four candidates trained per store, the winner chosen by
  validation error, but served **only where it beats a predict-the-mean baseline
  on held-out data**. Where it doesn't (measured, not assumed), the reorder table
  falls back to a moving average and says so on screen instead of showing a badge
  the evidence doesn't support. One of the three seeded stores is in exactly that
  position. Full numbers in the
  [model card](docs/model-card-stock-forecast.md).
- **Churn** — logistic regression per store, self-labelled from history, seeded
  and reproducible, with the metrics and coefficients in `model_runs` and an
  honest [model card](docs/model-card-churn.md). Its ROC-AUC sits under the
  project's own 0.75 target; that is reported rather than tuned away.

---

## Documentation

| Where | What |
|---|---|
| **[docs/LocalAI_OS_Final_Project_Report.pdf](docs/LocalAI_OS_Final_Project_Report.pdf)** | **The full project report — 36 pages, architecture through to viva prep** |
| [docs/demo-guide.md](docs/demo-guide.md) | a 10-minute click path, and what not to do |
| [docs/viva-study-guide.md](docs/viva-study-guide.md) | short answers to the questions an examiner asks |
| [docs/testing-report.md](docs/testing-report.md) | every measured figure, and the defects this pass found |
| [docs/architecture.md](docs/architecture.md) | layers, data flow, agent boundaries |
| [docs/model-card-stock-forecast.md](docs/model-card-stock-forecast.md) | the reorder model, its baseline, and why it's switched off for one store |
| [docs/model-card-churn.md](docs/model-card-churn.md) | features, labels, metrics, coefficients, limitations |
| [docs/whatsapp-demo.md](docs/whatsapp-demo.md) | how to send one real WhatsApp reminder for a live demo |
| [docs/hardening-report.md](docs/hardening-report.md) | the earlier security/accessibility/performance audit |
| [docs/performance.md](docs/performance.md) | measured query times, the index before/after, N+1 guards |
| [docs/deployment.md](docs/deployment.md) | Postgres, Docker, Render, backups, what is verified |
| [docs/api-guide.md](docs/api-guide.md) | what each of the eleven routers is for |
| [docs/frontend-architecture.md](docs/frontend-architecture.md) | how the Next.js app is built |
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
backend/app/delivery/    console (default), Twilio WhatsApp, WhatsApp Cloud
backend/app/security.py  bcrypt + JWT       app/middleware.py  roles and audit
backend/scripts/         seed, rehearse, benchmark, backup, diagrams
backend/scheduler.py     the nightly pass
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
GEMINI_API_KEY=                        # optional; server-side only, never sent to the browser
DELIVERY_ADAPTER=console               # console | twilio_wa | whatsapp_cloud
DELIVERY_DAILY_CAP=50                  # a bug cannot spam a real person
ML_MODEL_DIR=                          # empty means backend/models
```

> **Before any demo, check `DELIVERY_ADAPTER=console`.** With `twilio_wa` and
> real credentials present, pressing Send in the Outbox messages a real phone.
> The test suite is immune — it blanks every credential — but the running app is
> not.

The seed is deterministic (`random.seed(42)`): running it twice produces
identical data, so a figure quoted in a report is the figure a reviewer sees.

---

## Testing

```bash
cd backend && python -m pytest -q          # 403 tests
cd web && npx tsc --noEmit && npx eslint . && npm run build
```

The suite also runs against PostgreSQL — each test in its own schema — by setting
`TEST_DATABASE_URL`. See [docs/testing-report.md](docs/testing-report.md) for the
full results and for how test isolation is enforced.

---

## Known gaps, honestly

- **Nothing is deployed.** `render.yaml`, `Procfile` and a Dockerfile exist;
  monitoring, error tracking and scheduled backups are not running anywhere.
- **SQLite allows one writer at a time.** Two cashiers billing simultaneously is
  the first realistic failure. The PostgreSQL runbook is written and the suite
  already passes there.
- **Three of eight verticals are seeded.** Grocery, pharmacy and apparel have
  full trading history; the other five are configured and usable but empty.
- **Training the ML models is API-only.** Churn and stock-forecast are triggered
  from `/docs`, not from a button in the app.
- **Devanagari offer text** renders as empty boxes on a poster until a Noto Sans
  Devanagari `.ttf` is dropped into `backend/assets/fonts/` — the code already
  looks there first, nothing else to change.
- **The LLM retry backoff is shorter than the free tier's throttle window.**
  Three attempts finish in about 3 s while a 429 asks for roughly 15, so
  throttling always produces template copy rather than delayed model copy. That
  is deliberate — waiting 15 s inside a user's request is worse — but a
  background path could afford to honour the hint.

## Not built, on purpose

Mobile apps, offline sync, multi-tenant billing, auto-posting to Instagram or
Facebook (campaigns stop at "published"), review sentiment analysis, barcode
hardware beyond scanner keyboard input, and anything needing a paid API tier.
