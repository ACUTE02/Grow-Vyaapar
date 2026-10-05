# 🛒 Grow Vyaapar

**Billing, inventory and customers for small Indian retail stores — with an autonomous marketing agent and two machine-learning models on top, and an honest label on every number the models produce.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-Alembic-D71F00)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/SQLite%20%7C%20PostgreSQL-supported-336791?logo=postgresql&logoColor=white)](docs/postgres-migration.md)
[![Gemini](https://img.shields.io/badge/Google-Gemini%20API-4285F4?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-406%20passing-brightgreen)](#-testing)
[![License](https://img.shields.io/badge/License-MIT-yellow)](#-license)

> The marketing agent decides who to contact and what to promote — and **never sends anything on its own**. The stock forecast is only shown where it measurably beats a naive baseline, and says so on screen where it doesn't.

---

## 📖 Overview

**Grow Vyaapar** is a full-stack point-of-sale and customer-growth platform for small Indian retail businesses. A shopkeeper bills a customer, keeps stock, tracks regulars, and gets a short list of things worth doing this week — all from one app, in the language of their own trade.

- **One codebase, eight kinds of shop.** Grocery, pharmacy, apparel, optical, bakery, cosmetics, electronics and hardware differ only by rows in a config table: thresholds, feature flags, product fields, reminder rules, job types, loyalty rates and copy tone. There is no `if vertical == ...` outside `backend/app/verticals/` — a test fails the build if a vertical name ever leaks into a service, agent, router or model.
- **An autonomous agent that never sends.** It reads what billing and inventory already produce, decides who to contact and what to promote, and writes only to its own tables. Completing a sale is itself the trigger. Delivery is always an explicit human action.
- **Models that report their own limits.** Two ML models are trained per store, validated on held-out data, and served only where the evidence supports it.

## ✨ Features

### 🧾 Shop keeping
- **POS with per-line GST**, stock decrement in a single transaction, sequential invoice numbers and a PDF invoice
- **Idempotent checkout** — a required `Idempotency-Key` means a retried payment returns the original bill instead of billing twice
- **Stock adjustments** with a reason code and a full audit trail
- **Customers** with an append-only record log (prescriptions, measurements)
- **Vertical-defined catalog**, batches with first-expired-first-out picking, and near-expiry alerts where the trade needs them
- **Jobs board** for alterations, lens fittings and cake orders
- **Suppliers, purchase orders** and receiving stock

### 🎨 Campaign posters
A shopkeeper picks an occasion and types an offer; the poster the customer sees actually says it. A generated background and the offer text, occasion, store name and address are composited with Pillow, so the words are always legible rather than left to a diffusion model to render. Regenerate before publishing, unpublish to edit, download the result — nothing posts anywhere automatically.

### 🤖 Seven agents

| Agent | Decides |
|---|---|
| `segmentation` | who is New, Regular, VIP or Inactive, by this store's thresholds |
| `reminders` | who to contact, why, and in what words |
| `insights` | the three things worth doing this week, quoting real figures |
| `campaigns` | what to promote, with a caption and a poster |
| `churn` | who is about to stop coming — **before** they lapse |
| `forecasting` | what runs out this cycle, and what is going stale |
| `attribution` | what the last campaign plausibly earned |

### 📈 Two honest ML models
- **Stock forecast** — four candidates trained per store, the winner chosen by validation error, but served **only where it beats a predict-the-mean baseline on held-out data**. Where it doesn't, the reorder table falls back to a moving average and says so on screen instead of showing a badge the evidence doesn't support. One of the three seeded stores is in exactly that position.
- **Churn** — logistic regression per store, self-labelled from history, seeded and reproducible, with metrics and coefficients stored in `model_runs`. Its ROC-AUC sits under the project's own 0.75 target; that is reported rather than tuned away.

### 🔐 Safety by default
- JWT auth with bcrypt, role checks and an audit log — enforced in the API, not just the UI
- Cross-tenant guards on every store-scoped route, plus sign-in rate limiting
- `DELIVERY_DAILY_CAP` so a bug cannot spam a real person; the default delivery adapter is `console`
- The LLM key stays server-side and is never logged or sent to the browser

## 🏗️ Architecture

```
                 Shopkeeper (Next.js web app)
                              │
                              ▼
                ┌──────────────────────────┐
                │   FastAPI  (11 routers)   │   auth · roles · audit · rate limit
                └─────┬──────────────┬─────┘
                      │              │
        ┌─────────────▼───┐    ┌─────▼─────────────────────┐
        │    Services     │    │          Agents            │
        │ billing · stock │    │ segmentation · reminders   │
        │ batches · jobs  │    │ insights · campaigns       │
        │ loyalty · PDF   │    │ churn · forecasting        │
        └────────┬────────┘    │ attribution                │
                 │             └──────┬──────────────┬──────┘
                 │                    │              │
                 │             ┌──────▼─────┐  ┌─────▼──────┐
                 │             │ ML models  │  │ LLM client │  fallback to
                 │             │ (sklearn)  │  │ Gemini/Groq│  template copy
                 │             └────────────┘  └────────────┘
                 ▼
        ┌─────────────────┐        ┌───────────────────────────┐
        │ SQLite / Postgres│        │  Delivery adapter          │
        │  (SQLAlchemy)    │        │  console · Twilio · Cloud  │
        └─────────────────┘        │  ── human presses Send ──  │
                                   └───────────────────────────┘
```

The nightly pass (`backend/scheduler.py`) re-runs the agents; the generated output waits in the Outbox until a person approves it.

## 📁 Project Structure

```
Grow-Vyaapar/
├── backend/
│   ├── app/
│   │   ├── verticals/     # definitions (8 JSON files), loader, StoreContext, validation
│   │   ├── models/        # config, core, agent, ml, commerce, admin
│   │   ├── services/      # billing, stock, batches, jobs, coupons, loyalty,
│   │   │                  # suppliers, delivery, customers, products, invoice PDF
│   │   ├── agents/        # segmentation, reminders, insights, campaigns,
│   │   │                  # churn, forecasting, attribution
│   │   ├── routers/       # eleven API routers
│   │   ├── llm/           # one call(), every prompt in one file
│   │   ├── delivery/      # console (default), Twilio WhatsApp, WhatsApp Cloud
│   │   ├── ml/            # stock-forecast model
│   │   ├── security.py    # bcrypt + JWT
│   │   └── middleware.py  # roles and audit
│   ├── alembic/           # migrations
│   ├── scripts/           # seed, rehearse, benchmark, backup, diagrams
│   ├── scheduler.py       # the nightly pass
│   └── tests/
├── web/
│   └── src/
│       ├── app/           # Next.js routes — every page lives under /s/[storeId]
│       ├── lib/           # api client, Zod schemas, query hooks, session, format
│       └── components/    # shell, ui primitives, charts, feature components
├── dev.py                 # starts the backend and the web app together
├── render.yaml            # Render blueprint
└── Procfile
```

## 🛠️ Tech Stack

`Python 3.11` · `FastAPI` · `SQLAlchemy` · `Alembic` · `Pydantic` · `APScheduler` · `scikit-learn` · `Pillow` · `WeasyPrint` · `Next.js 16` · `React 19` · `TypeScript` · `Tailwind CSS 4` · `TanStack Query` · `Zod` · `Recharts` · `Google Gemini API` · `Twilio / WhatsApp Cloud API` · `SQLite` · `PostgreSQL` · `Docker`

## 🚀 Local Deployment

Requires Python 3.11 or newer and Node.js.

```bash
git clone https://github.com/ACUTE02/Grow-Vyaapar.git
cd Grow-Vyaapar
python -m venv .venv
```

Activate the environment — Windows PowerShell: `.venv\Scripts\Activate.ps1` · macOS/Linux: `source .venv/bin/activate`

```bash
pip install -r backend/requirements.txt
cp .env.example backend/.env
cd backend
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

In a second terminal, start the web app:

```bash
cd web
npm install
npm run dev
```

The API runs on <http://127.0.0.1:8000> (reference at `/docs`) and the app on <http://localhost:3000>. Sign in as **`owner@localai.demo`**; the demo password is printed by the seed script. **No LLM key is needed for any of it.**

Or start both at once:

```bash
python dev.py
```

### ⚙️ Configuration

Copy `.env.example` to `backend/.env`. Every value has a working default; the file is only needed to point at Postgres, switch on an LLM, or deploy.

```
DATABASE_URL=sqlite:///./localai.db    # or postgresql+psycopg://...
AUTH_ENABLED=true                      # enforced in the API, not just the UI
JWT_SECRET=change-me                   # generate one per environment
GEMINI_API_KEY=                        # optional; server-side only
DELIVERY_ADAPTER=console               # console | twilio_wa | whatsapp_cloud
DELIVERY_DAILY_CAP=50                  # a bug cannot spam a real person
ML_MODEL_DIR=                          # empty means backend/models
```

> ⚠️ **Before any demo, check `DELIVERY_ADAPTER=console`.** With `twilio_wa` and real credentials present, pressing Send in the Outbox messages a real phone. The test suite blanks every credential, but the running app does not.

The seed is deterministic (`random.seed(42)`): running it twice produces identical data, so a figure quoted in a report is the figure a reviewer sees.

### 🐳 Docker / Render

A Dockerfile lives in `backend/`, and `render.yaml` describes a web service, a scheduler worker and a managed Postgres database. Secrets are never in the file — the blueprint only names the variables.

## 🧪 Testing

```bash
cd backend && python -m pytest -q          # 406 tests
cd web && npx tsc --noEmit && npx eslint . && npm run build
```

The suite also runs against PostgreSQL — each test in its own schema — by setting `TEST_DATABASE_URL`. It covers cross-tenant isolation, idempotent checkout, the no-vertical-names-outside-`verticals/` rule, and delivery being impossible to trigger from a test.

## ⚠️ Known Gaps, Honestly

- **Nothing is deployed.** `render.yaml`, `Procfile` and a Dockerfile exist; monitoring, error tracking and scheduled backups are not running anywhere.
- **SQLite allows one writer at a time.** Two cashiers billing simultaneously is the first realistic failure. The PostgreSQL runbook is written and the suite already passes there.
- **Three of eight verticals are seeded.** Grocery, pharmacy and apparel have full trading history; the other five are configured and usable but empty.
- **Training the ML models is API-only.** Churn and stock-forecast are triggered from `/docs`, not from a button in the app.
- **Devanagari offer text** renders as empty boxes on a poster until a Noto Sans Devanagari `.ttf` is placed in `backend/assets/fonts/`.
- **A throttled LLM call produces template copy**, not delayed model copy. A 429 falls back immediately rather than retrying, because on a free tier a refused request still spends the allowance.

### 🚫 Not built, on purpose
Mobile apps, offline sync, multi-tenant billing, auto-posting to Instagram or Facebook, review sentiment analysis, barcode hardware beyond scanner keyboard input, and anything needing a paid API tier.

## 🤝 Contributing

Contributions are welcome!

1. Fork this repository.
2. Create a new feature branch.
3. Commit your changes.
4. Push to GitHub.
5. Open a Pull Request.

## ⭐ Support

If you found this project useful:

- ⭐ Star this repository
- 🍴 Fork this repository
- 📣 Share it with others

## 📄 License

This project is licensed under the MIT License.

---

<div align="center">

**🛒 Grow Vyaapar**

*Billing, inventory and an agent that helps a small shop grow — without ever sending a message on its own.*

⭐ If this project helped you, don't forget to star the repository!

</div>
