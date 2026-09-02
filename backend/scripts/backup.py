"""Daily database backup.

    python -m scripts.backup                 # dump, compress, prune old copies
    python -m scripts.backup --restore FILE  # print the restore command

Postgres goes through pg_dump; SQLite is copied with the online backup API so a
running app cannot leave a half-written file. Old dumps are pruned by count, so
a free disk does not fill up quietly.

Object storage is optional: set BACKUP_S3_BUCKET and the usual AWS variables and
each dump is uploaded after it is written. Without them the dump stays on the
attached disk, which is still a backup - just one with a worse failure story,
and the README says so.
"""
from __future__ import annotations

import argparse
import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backup")

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))
KEEP = int(os.environ.get("BACKUP_KEEP", "14"))


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_sqlite(url: str, target: Path) -> Path:
    source_path = url.split("sqlite:///")[-1]
    target = target.with_suffix(".db")
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    with destination:
        source.backup(destination)      # consistent even while the app is running
    source.close()
    destination.close()

    compressed = target.with_suffix(".db.gz")
    with open(target, "rb") as raw, gzip.open(compressed, "wb") as gz:
        shutil.copyfileobj(raw, gz)
    target.unlink()
    return compressed


def backup_postgres(url: str, target: Path) -> Path:
    parsed = urlparse(url.replace("postgresql+psycopg", "postgresql"))
    compressed = target.with_suffix(".sql.gz")
    environment = {**os.environ}
    if parsed.password:
        environment["PGPASSWORD"] = parsed.password

    command = [
        "pg_dump",
        "--no-owner",
        "--no-privileges",
        "--host", parsed.hostname or "localhost",
        "--port", str(parsed.port or 5432),
        "--username", parsed.username or "postgres",
        (parsed.path or "/postgres").lstrip("/"),
    ]
    logger.info("Running %s", " ".join(command))
    with gzip.open(compressed, "wb") as gz:
        process = subprocess.run(command, stdout=subprocess.PIPE, env=environment, check=True)
        gz.write(process.stdout)
    return compressed


def upload(path: Path) -> bool:
    bucket = os.environ.get("BACKUP_S3_BUCKET")
    if not bucket:
        return False
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        logger.warning("BACKUP_S3_BUCKET is set but boto3 is not installed; keeping it local")
        return False
    try:
        boto3.client("s3").upload_file(str(path), bucket, f"localai-os/{path.name}")
    except Exception:
        logger.exception("Upload failed; the local copy is still on disk")
        return False
    logger.info("Uploaded %s to s3://%s", path.name, bucket)
    return True


def prune(directory: Path, keep: int) -> int:
    dumps = sorted(directory.glob("localai-*.gz"), key=lambda item: item.stat().st_mtime)
    removed = 0
    while len(dumps) > keep:
        oldest = dumps.pop(0)
        oldest.unlink()
        removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the LocalAI OS database")
    parser.add_argument("--restore", help="print the restore command for a dump file")
    args = parser.parse_args()

    url = settings.database_url
    if args.restore:
        if url.startswith("sqlite"):
            print(f"gunzip -c {args.restore} > localai.db")
        else:
            print(f"gunzip -c {args.restore} | psql \"{url}\"")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"localai-{_stamp()}"

    try:
        path = backup_sqlite(url, target) if url.startswith("sqlite") else backup_postgres(url, target)
    except FileNotFoundError:
        logger.error("pg_dump is not on PATH. Install postgresql-client in the image.")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        logger.error("pg_dump failed with exit code %s", exc.returncode)
        sys.exit(1)

    size_kb = path.stat().st_size / 1024
    uploaded = upload(path)
    removed = prune(BACKUP_DIR, KEEP)

    logger.info(
        "Backup complete: %s (%.1f KB)%s, %s old dump(s) pruned, keeping %s",
        path.name,
        size_kb,
        " and uploaded" if uploaded else " on the attached disk",
        removed,
        KEEP,
    )


if __name__ == "__main__":
    main()
