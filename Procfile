# Railway, Heroku and anything else that reads a Procfile.
release: cd backend && alembic upgrade head
web: cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && python scheduler.py
