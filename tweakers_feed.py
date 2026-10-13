#!/usr/bin/env python3
"""Bouwt één RSS-feed uit de Tweakers-feeds nieuws en reviews.

Haalt beide officiële feeds op, bewaart elk artikel in archive.json en schrijft
docs/feed.xml en de dagbestanden in dagen/. Artikelen ouder dan FEED_DAYS dagen
verdwijnen uit het archief.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

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

# Dagbestanden: per dag één Markdown-bestand in DAG_DIR, genoemd naar de dag
# zelf ("Dinsdag 13 oktober.md"), met dezelfde tekst als kop. Een dag loopt van
# 17:00 de dag ervoor tot 17:00 die dag (Nederlandse tijd). Een artikel hoort
# bij de dag waarin de robot het voor het eerst zag ("first"), niet bij zijn
# publicatiedatum: een artikel van 16:55 dat pas om 17:10 binnenkomt, zou in een
# dag die al is opgehaald niemand meer bereiken. Zo staat elk artikel in precies
# één dagbestand.
#
# LAATSTE_FILE noemt de laatste LAATSTE_DAGEN afgeronde dagen, nieuwste eerst,
# één naam per regel. Inkt leest dat lijstje en haalt de dagen die het nog niet
# had naar de map Nieuws in iCloud Drive; twee weken, zodat ook na een lange
# tijd zonder verbinding niets ontbreekt. Dagbestanden blijven DAG_BEWAREN dagen
# staan: langer dan het lijstje, zodat Inkt dat het lijstje net vóór een run las,
# het oudste bestand nog vindt.
DAG_DIR = Path("dagen")
LAATSTE_FILE = DAG_DIR / "laatste.txt"
DAG_TZ = ZoneInfo("Europe/Amsterdam")
DAG_EINDE_UUR = 17
LAATSTE_DAGEN = 14
DAG_BEWAREN = 16
DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december"]


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


def merge(archive: dict, fetched: list[dict], now: datetime) -> int:
    """Voegt nieuwe artikelen toe en werkt bestaande bij. De publicatiedatum
    en het moment van eerste keer gezien blijven bij een bekend artikel staan.
    Artikelen van vóór 13 oktober 2026 hebben geen "first"; voor hen geldt de
    publicatiedatum."""
    new = 0
    for item in fetched:
        old = archive.get(item["guid"])
        if old is None:
            new += 1
            item["first"] = format_datetime(now)
        else:
            item["pubDate"] = old["pubDate"]
            item["first"] = old.get("first", old["pubDate"])
        archive[item["guid"]] = item
    return new


def prune(archive: dict, cutoff: datetime, current: set) -> int:
    old = [g for g, it in archive.items()
           if parse_date(it["pubDate"]) < cutoff and g not in current]
    for g in old:
        del archive[g]
    return len(old)


# --- Dagbestanden -------------------------------------------------------------

def dag_van(moment: datetime) -> date:
    """De dag waar moment bij hoort: na 17:00 is het al de volgende dag."""
    local = moment.astimezone(DAG_TZ)
    dag = local.date()
    return dag + timedelta(days=1) if local.hour >= DAG_EINDE_UUR else dag


def dag_grens(dag: date) -> datetime:
    """17:00 Nederlandse tijd op die dag, ook over de zomer/wintertijd-grens."""
    return datetime(dag.year, dag.month, dag.day, DAG_EINDE_UUR, tzinfo=DAG_TZ)


def dag_naam(dag: date) -> str:
    return f"{DAGEN[dag.weekday()].capitalize()} {dag.day} {MAANDEN[dag.month - 1]}"


def eerst_gezien(item: dict) -> datetime:
    return parse_date(item.get("first", item["pubDate"]))


def _md_regel(tekst: str) -> str:
    """Voorkom dat een alinea per ongeluk als kop, lijst of citaat wordt gelezen."""
    if re.match(r"^(#|>|[-+*]\s|\d+[.)]\s)", tekst):
        return "\\" + tekst
    return tekst


def build_dag_markdown(archive: dict, dag: date) -> str:
    start, end = dag_grens(dag - timedelta(days=1)), dag_grens(dag)
    artikelen = [it for it in archive.values() if start <= eerst_gezien(it) < end]
    # Oudste eerst; bij gelijke tijd (zelfde run) op publicatiedatum en adres,
    # zodat de volgorde vastligt.
    artikelen.sort(key=lambda it: (eerst_gezien(it), parse_date(it["pubDate"]), it["guid"]))

    regels = [f"# {dag_naam(dag)}"]
    if not artikelen:
        regels += ["", "Geen artikelen."]
    for it in artikelen:
        regels += ["", f"## {' '.join(it['title'].split())}"]
        if it["description"]:
            regels += ["", _md_regel(" ".join(it["description"].split()))]
        regels += ["", f"[Lees het hele artikel]({it['link']})"]
    return "\n".join(regels) + "\n"


def write_dagen(archive: dict, now: datetime) -> list[Path]:
    """Schrijf de laatste afgeronde dagen en het lijstje met hun namen.

    De lopende dag wordt niet geschreven: die is pas om 17:00 compleet.
    """
    DAG_DIR.mkdir(exist_ok=True)
    lopend = dag_van(now)
    afgerond = [lopend - timedelta(days=n) for n in range(1, LAATSTE_DAGEN + 1)]
    paden = []
    for dag in afgerond:
        pad = DAG_DIR / f"{dag_naam(dag)}.md"
        pad.write_text(build_dag_markdown(archive, dag), encoding="utf-8")
        paden.append(pad)
    LAATSTE_FILE.write_text("".join(f"{dag_naam(d)}\n" for d in afgerond), encoding="utf-8")

    bewaren = {f"{dag_naam(lopend - timedelta(days=n))}.md" for n in range(1, DAG_BEWAREN + 1)}
    for oud in DAG_DIR.glob("*.md"):
        if oud.name not in bewaren:
            oud.unlink()
    return paden


# --- Feed schrijven -----------------------------------------------------------

def build_rss(items: list[dict], now: datetime) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>Tweakers</title>\n"
        "  <link>https://tweakers.net/</link>\n"
        f'  <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>\n'
        "  <description>Tweakers nieuws en reviews, "
        f"met de artikelen van de afgelopen {FEED_DAYS} dagen.</description>\n"
        "  <language>nl-NL</language>\n"
        f"  <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        "  <ttl>60</ttl>\n"
        "  <image>\n"
        f"    <url>{FEED_ICON_URL}</url>\n"
        "    <title>Tweakers</title>\n"
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

    new = merge(archive, fetched, now)
    removed = prune(archive, now - timedelta(days=FEED_DAYS), {i["guid"] for i in fetched})

    items = sorted(archive.values(), key=lambda it: parse_date(it["pubDate"]), reverse=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_rss(items, now), encoding="utf-8")
    save_archive(archive)
    for pad in write_dagen(archive, now):
        print(f"Dagbestand bijgewerkt: {pad}")

    print(f"Archief: {len(archive)} artikelen ({new} nieuw, {removed} verlopen).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
