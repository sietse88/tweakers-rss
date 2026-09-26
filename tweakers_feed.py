#!/usr/bin/env python3
"""Bouwt één gefilterde RSS-feed uit de Tweakers-feeds nieuws en reviews.

Haalt beide officiële feeds op, bewaart elk artikel in archive.json (ook de
weggefilterde, zodat een gewijzigde filterregel ook op oudere artikelen werkt),
past de regels uit filter_regels.py toe en schrijft docs/feed.xml. Artikelen
ouder dan FEED_DAYS dagen verdwijnen uit het archief.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from filter_regels import ALTIJD_DOOR, REGELS, WOORDEN

USER_AGENT = "tweakers-rss/1.0 (github.com/sietse88/tweakers-rss)"
SOURCES = [
    "https://tweakers.net/feeds/nieuws.xml",
    "https://tweakers.net/feeds/reviews.xml",
]
OUTPUT = Path("docs/feed.xml")
ARCHIVE_FILE = Path("archive.json")
SITE_BASE_URL = "https://sietse88.github.io/tweakers-rss"
FEED_URL = f"{SITE_BASE_URL}/feed.xml"
# Het logo uit de officiële Tweakers-feed (vierkant, 192 px). NetNewsWire toont
# dit naast de feed; zonder <image> wordt het een grijze wereldbol.
FEED_ICON_URL = "https://tweakers.net/icon-192.png"

# Archief: de feed bevat alle artikelen van de afgelopen FEED_DAYS dagen, niet
# alleen de 1 à 2 dagen die Tweakers zelf aanbiedt. Zo haalt de RSS-reader na
# een pauze van een paar weken alsnog alles op wat er in de tussentijd verscheen.
FEED_DAYS = 30


# --- Ophalen -----------------------------------------------------------------

def fetch_feed(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    items = []
    for it in root.findall("channel/item"):
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if not guid or not title or not pub:
            continue
        items.append({
            "guid": guid,
            "title": title,
            "link": (it.findtext("link") or guid).strip(),
            "description": (it.findtext("description") or "").strip(),
            "author": (it.findtext("author") or "").strip(),
            "category": (it.findtext("category") or "").strip(),
            "comments": (it.findtext("comments") or "").strip(),
            "pubDate": pub,
        })
    if not items:
        raise ValueError("geen artikelen gevonden")
    return items


# --- Filter ------------------------------------------------------------------

def _word_pattern(word: str) -> re.Pattern:
    # Hele woorden, met een optionele meervoud-s. Korte woorden (AI, Mac, iOS)
    # hoofdlettergevoelig, zodat "MAC-adres" of "ai" in een zin niet meetelt.
    flags = 0 if len(word) <= 3 else re.IGNORECASE
    body = re.escape(word).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![\w]){body}s?(?![\w])", flags)


WOORD_PATRONEN = {
    groep: [_word_pattern(w) for w in woorden] for groep, woorden in WOORDEN.items()
}


def split_category(category: str) -> tuple[str, str]:
    """"Nieuws / Computers / Laptops" -> ("Computers", "Laptops")."""
    parts = [p.strip() for p in category.split("/")]
    hoofd = parts[1] if len(parts) > 1 else ""
    onderwerp = parts[2] if len(parts) > 2 else ""
    return hoofd, onderwerp


def rule_for(category: str):
    hoofd, onderwerp = split_category(category)
    if onderwerp and f"{hoofd} / {onderwerp}" in REGELS:
        return REGELS[f"{hoofd} / {onderwerp}"]
    return REGELS.get(hoofd, "alles")


def matches(title: str, groepen) -> bool:
    return any(p.search(title) for groep in groepen for p in WOORD_PATRONEN[groep])


def passes(item: dict) -> bool:
    if matches(item["title"], ALTIJD_DOOR):
        return True
    rule = rule_for(item["category"])
    if rule == "alles":
        return True
    if rule == "niets":
        return False
    return matches(item["title"], rule)


# --- Archief -----------------------------------------------------------------

def parse_date(rfc_date: str) -> datetime:
    try:
        return parsedate_to_datetime(rfc_date)
    except (TypeError, ValueError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def load_archive() -> dict:
    if ARCHIVE_FILE.exists():
        return json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
    return {}


def save_archive(archive: dict) -> None:
    ARCHIVE_FILE.write_text(
        json.dumps(archive, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def merge(archive: dict, fetched: list[dict]) -> int:
    """Voegt nieuwe artikelen toe en werkt bestaande bij. De publicatiedatum
    van een artikel dat al in het archief staat blijft ongewijzigd."""
    new = 0
    for item in fetched:
        old = archive.get(item["guid"])
        if old is None:
            new += 1
        else:
            item["pubDate"] = old["pubDate"]
        archive[item["guid"]] = item
    return new


def prune(archive: dict, cutoff: datetime, current: set) -> int:
    old = [g for g, it in archive.items()
           if parse_date(it["pubDate"]) < cutoff and g not in current]
    for g in old:
        del archive[g]
    return len(old)


# --- Feed schrijven -----------------------------------------------------------

def build_rss(items: list[dict], now: datetime) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>Tweakers (gefilterd)</title>\n"
        "  <link>https://tweakers.net/</link>\n"
        f'  <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>\n'
        "  <description>Tweakers nieuws en reviews, gefilterd op onderwerp, "
        f"met de artikelen van de afgelopen {FEED_DAYS} dagen.</description>\n"
        "  <language>nl-NL</language>\n"
        f"  <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        "  <ttl>60</ttl>\n"
        "  <image>\n"
        f"    <url>{FEED_ICON_URL}</url>\n"
        "    <title>Tweakers (gefilterd)</title>\n"
        "    <link>https://tweakers.net/</link>\n"
        "    <width>192</width>\n"
        "    <height>192</height>\n"
        "  </image>\n"
    ]
    for it in items:
        parts.append(
            "  <item>\n"
            f"    <title>{escape(it['title'])}</title>\n"
            f"    <link>{escape(it['link'])}</link>\n"
            f'    <guid isPermaLink="false">{escape(it["guid"])}</guid>\n'
            f"    <pubDate>{format_datetime(parse_date(it['pubDate']))}</pubDate>\n"
            f"    <description>{escape(it['description'])}</description>\n"
            + (f"    <dc:creator>{escape(it['author'])}</dc:creator>\n" if it["author"] else "")
            + (f"    <category>{escape(it['category'])}</category>\n" if it["category"] else "")
            + (f"    <comments>{escape(it['comments'])}</comments>\n" if it["comments"] else "")
            + "  </item>\n"
        )
    parts.append("</channel>\n</rss>\n")
    return "".join(parts)


def main() -> int:
    now = datetime.now(timezone.utc)
    archive = load_archive()

    fetched = []
    for url in SOURCES:
        try:
            items = fetch_feed(url)
            print(f"{url}: {len(items)} artikelen")
            fetched.extend(items)
        except Exception as e:  # noqa: BLE001 — één mislukte bron mag de rest niet tegenhouden
            print(f"WAARSCHUWING: {url} ophalen mislukt: {e}", file=sys.stderr)
    if not fetched:
        print("FOUT: geen enkele bron opgehaald; archief en feed blijven ongewijzigd.",
              file=sys.stderr)
        return 1

    new = merge(archive, fetched)
    removed = prune(archive, now - timedelta(days=FEED_DAYS), {i["guid"] for i in fetched})

    items = sorted(archive.values(), key=lambda it: parse_date(it["pubDate"]), reverse=True)
    kept = [it for it in items if passes(it)]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_rss(kept, now), encoding="utf-8")
    save_archive(archive)

    print(f"Archief: {len(archive)} artikelen ({new} nieuw, {removed} verlopen). "
          f"In de feed: {len(kept)}, weggefilterd: {len(items) - len(kept)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
