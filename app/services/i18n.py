"""UI translations.

The locale preference has been stored in the settings table since F15, but
until now no template read it: the stored promise said "English or Russian"
and the pages always rendered English. This module makes the setting honest —
`t("...")` in a template looks up the literal in the active locale's catalog
and falls back to the literal itself, so an untranslated string degrades to
English instead of an error.

Catalogs live in app/translations/<locale>.json, keyed by the English
literal. Keys are literals (not opaque ids) on purpose: the English text is
the source of truth, grep-able, and a missing key needs no code change to
fix.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "en"

_TRANSLATIONS_DIR = Path(__file__).parent.parent / "translations"


@lru_cache(maxsize=8)
def _load_catalog(locale: str) -> dict[str, str]:
    if locale == DEFAULT_LOCALE:
        return {}
    path = _TRANSLATIONS_DIR / f"{locale}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("No usable translation catalog for %r (%s)", locale, e)
        return {}


def translate(text: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
    """Translate a literal into `locale`, interpolating {placeholders}.

    Unknown locale, missing key or a bad placeholder all degrade to the
    English text rather than raising — a page must never fail to render
    over a translation.
    """
    if locale and locale != DEFAULT_LOCALE:
        text = _load_catalog(locale).get(text, text)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            logger.warning("Bad interpolation in %r — rendering as-is", text)
            return text
    return text


def current_locale() -> str:
    """Active UI locale from the settings cache (startup-loaded).

    Sync on purpose: Jinja globals run inside a render. Before the cache is
    loaded — tests, first render — the English default applies.
    """
    from app.services.settings_service import settings_service

    locale = settings_service.get_cached("locale", DEFAULT_LOCALE)
    return locale if isinstance(locale, str) else DEFAULT_LOCALE
