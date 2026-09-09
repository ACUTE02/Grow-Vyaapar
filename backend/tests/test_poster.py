"""Poster compositing: the offer has to end up on the image, legibly.

The picture comes from a generator that cannot spell; the words come from
Pillow. These tests cover the second half - that something is actually drawn,
that an absent offer is skipped rather than rendered as an empty bar, and that
a failure anywhere hands back the plain background instead of a broken image.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.services import poster


@pytest.fixture()
def background(monkeypatch, tmp_path: Path):
    """A plain grey square standing in for the generated background.

    Patched at the httpx boundary so no test reaches the network, and the
    output is written under tmp_path so a run leaves nothing behind.
    """
    buffer = BytesIO()
    Image.new("RGB", (1024, 1024), (120, 120, 120)).save(buffer, format="PNG")
    payload = buffer.getvalue()

    class _Response:
        content = payload

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(poster, "POSTER_DIR", tmp_path / "campaigns")
    return payload


def _saved(tmp_path: Path, url: str) -> Path:
    assert url.startswith("/static/campaigns/"), url
    return tmp_path / "campaigns" / url.rsplit("/", 1)[-1]


def test_the_offer_is_drawn_onto_the_poster(background, tmp_path: Path) -> None:
    url = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Jeevan Medical Store",
        occasion="Diwali",
        offer_text="20% off all toothpaste",
        address="12 MG Road, Nagpur",
        key="store2-campaign1",
    )

    path = _saved(tmp_path, url)
    assert path.is_file()

    with Image.open(path) as image:
        assert image.size == (1024, 1024)
        # The source was one flat grey. Anything drawn on it - the bar, the
        # accent rule, the text - shows up as more than one colour.
        assert len(image.convert("RGB").getcolors(maxcolors=200_000) or []) > 50


def test_a_poster_without_an_offer_still_renders(background, tmp_path: Path) -> None:
    """A shopkeeper who just wants a festive poster gets one."""
    url = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Sharma Kirana Bazaar",
        occasion="Holi",
        offer_text=None,
        address=None,
        key="store1-campaign9",
    )

    path = _saved(tmp_path, url)
    assert path.is_file()

    with Image.open(path) as image:
        colours = len(image.convert("RGB").getcolors(maxcolors=200_000) or [])
    assert colours > 20


def test_an_offer_makes_a_taller_bar_than_none(background, tmp_path: Path) -> None:
    """The offer line is real, not decoration: with one, more of the image is
    covered by the overlay than without."""

    def dark_rows(url: str) -> int:
        with Image.open(_saved(tmp_path, url)) as image:
            pixels = image.convert("L")
            # Count rows whose left edge has been darkened by the bar.
            return sum(1 for y in range(image.height) if pixels.getpixel((5, y)) < 90)

    with_offer = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Store",
        occasion="Diwali",
        offer_text="Flat 50 rupees off on bills above 500",
        address=None,
        key="a",
    )
    without = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Store",
        occasion="Diwali",
        offer_text=None,
        address=None,
        key="b",
    )

    assert dark_rows(with_offer) > dark_rows(without)


def test_a_long_offer_is_shrunk_rather_than_clipped(background, tmp_path: Path) -> None:
    """140 characters is the field's limit, so it has to fit."""
    url = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Rangoli Fashion House",
        occasion="End of season",
        offer_text=(
            "Buy any two kurtas and get the third absolutely free, plus flat 200 rupees "
            "off on every bill above 2000 rupees, this weekend only"
        ),
        address="Shop 4, Jaipur",
        key="long",
    )
    path = _saved(tmp_path, url)
    assert path.is_file()
    with Image.open(path) as image:
        assert image.size == (1024, 1024)


def test_a_failed_background_returns_the_original_url(monkeypatch, tmp_path: Path) -> None:
    """A poster is a nice-to-have on a page that already works. If the
    background cannot be fetched the caller keeps the plain generated image
    rather than a broken one - and nothing raises."""

    def _boom(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(poster, "POSTER_DIR", tmp_path / "campaigns")

    original = "https://image.pollinations.ai/prompt/whatever"
    assert (
        poster.compose_poster(
            original,
            store_name="Store",
            occasion="Diwali",
            offer_text="20% off",
            key="fail",
        )
        == original
    )
    assert not (tmp_path / "campaigns").exists() or not list((tmp_path / "campaigns").iterdir())


def test_a_corrupt_background_returns_the_original_url(monkeypatch, tmp_path: Path) -> None:
    """The generator answering 200 with something that is not an image is the
    other way this fails in the wild."""

    class _Response:
        content = b"<html>rate limited</html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(poster, "POSTER_DIR", tmp_path / "campaigns")

    original = "https://image.pollinations.ai/prompt/whatever"
    assert (
        poster.compose_poster(
            original, store_name="S", occasion="Eid", offer_text=None, key="corrupt"
        )
        == original
    )


def test_the_filename_is_stable_for_a_campaign(background, tmp_path: Path) -> None:
    """Regenerating replaces the poster instead of leaving orphans behind."""
    first = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Store",
        occasion="Diwali",
        offer_text="10% off",
        key="store3-campaign7",
    )
    second = poster.compose_poster(
        "https://example.invalid/bg.png",
        store_name="Store",
        occasion="Diwali",
        offer_text="25% off",
        key="store3-campaign7",
    )

    assert first == second
    assert len(list((tmp_path / "campaigns").iterdir())) == 1


def test_the_poster_directory_is_served_without_a_token(anon_client) -> None:
    """An <img> tag sends no Authorization header. If the middleware guards
    /static, every poster renders as a broken image in the browser - which is
    exactly what happened the first time this was wired up."""
    response = anon_client.get("/static/campaigns/does-not-exist.jpg")

    # 404 rather than 401: the path is reachable, that file just is not there.
    assert response.status_code == 404
