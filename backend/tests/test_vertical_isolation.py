"""Hard rule 1: no vertical names outside app/verticals/.

Walk every .py file under app/ except app/verticals/, parse it, and fail if any
shipped vertical code appears as a string literal. Vertical differences must come
from config objects, never from branching on a name.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.verticals.loader import known_codes

APP_DIR = Path(__file__).resolve().parents[1] / "app"
EXEMPT_DIR = APP_DIR / "verticals"

CODES = set(known_codes())


def _scanned_files() -> list[Path]:
    return sorted(
        path
        for path in APP_DIR.rglob("*.py")
        if EXEMPT_DIR not in path.parents and path != EXEMPT_DIR
    )


def test_definitions_are_loadable() -> None:
    assert len(CODES) == 8, f"expected eight verticals, found {sorted(CODES)}"


def test_no_vertical_code_literals_outside_verticals_package() -> None:
    offences: list[str] = []
    for path in _scanned_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for code in CODES:
                    if code in node.value.lower():
                        offences.append(
                            f"{path.relative_to(APP_DIR.parent)}:{node.lineno} "
                            f"contains vertical code '{code}' in a string literal"
                        )
    assert not offences, "Vertical names leaked outside app/verticals/:\n" + "\n".join(offences)


def test_scan_actually_covers_the_codebase() -> None:
    """Guards against the isolation test silently passing on an empty file list."""
    scanned = _scanned_files()
    assert len(scanned) > 5, f"only scanned {len(scanned)} files, the walk is broken"


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: p.name)
def test_files_parse(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
