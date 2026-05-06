"""
Bay Area small venue scraper.
Scrapes event calendars and cross-references against your TIDAL library.

Venues covered (static HTML):
  Yoshi's Oakland, Café du Nord, Brick & Mortar, Boom Boom Room, Rickshaw Stop

Venues needing browser rendering (TODO):
  The Chapel (SeeTickets JS), The Independent (FullCalendar JS)
"""

import csv
import os
import re
import sys
import time
from datetime import datetime
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

# Fix Windows console Unicode issues
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Config ---
USER_DATA_DIR = r"C:\Users\Thomas\AI\concert-finder\user_data_26161906"
OUTPUT_PATH   = r"C:\Users\Thomas\AI\venue_shows.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

NOW = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

# ── Library loader ────────────────────────────────────────────────────────────

def load_known_artists():
    artists = set()
    for fname, key in [("favorite_artists.csv", "artist_name"), ("streaming.csv", "artist_name")]:
        path = os.path.join(USER_DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get(key, "").strip()
                if name:
                    artists.add(name.lower())
    return artists


def is_known(artist_name, known_set):
    name = artist_name.lower().strip()
    if name in known_set:
        return True
    for k in known_set:
        if len(k) > 5 and (k in name or name in k):
            return True
    return False

# ── Fetch helper ──────────────────────────────────────────────────────────────

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=14)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    ! Could not fetch {url}: {e}")
        return None

# ── Date parser ───────────────────────────────────────────────────────────────

def parse_date(text):
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    current_year = datetime.now().year

    for fmt in (
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
        "%m/%d/%Y",  "%Y-%m-%d",  "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    # "May 6, 2026" without comma
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})[,\s]+(\d{4})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
        except ValueError:
            pass

    # "5.7" or "5/7" style — assume current or next year
    m = re.match(r"(\d{1,2})[./](\d{1,2})$", text)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        for yr in (current_year, current_year + 1):
            try:
                d = datetime(yr, mo, da)
                if d >= NOW:
                    return d
            except ValueError:
                pass

    return None

# ── Venue scrapers ────────────────────────────────────────────────────────────

def scrape_yoshis():
    print("  Yoshi's Oakland...")
    shows = []
    soup  = fetch("https://www.yoshis.com/events")
    if not soup:
        return shows

    seen = set()
    for li in soup.select("ul.eventListings li"):
        date_el = li.select_one("p.date")
        name_el = li.select_one("h2 a")
        link_el = li.select_one("a[href]")
        if not date_el or not name_el:
            continue

        date = parse_date(date_el.get_text(strip=True))
        if not date or date < NOW:
            continue

        artist = name_el.get_text(strip=True).title()
        key    = (artist, date.date())
        if key in seen:
            continue
        seen.add(key)

        href = (link_el["href"] if link_el else "")
        if href and not href.startswith("http"):
            href = "https://www.yoshis.com" + href

        shows.append({"venue": "Yoshi's", "city": "Oakland", "artist": artist,
                       "support": [], "date": date, "time": "", "ticket": href})
    return shows


def scrape_timewire(url, venue_name, city, max_pages=4):
    """Works for Café du Nord and Brick & Mortar (both use TimeWire/TicketWeb plugin)."""
    print(f"  {venue_name}...")
    shows = []
    seen  = set()

    for page in range(1, max_pages + 1):
        page_url = url if page == 1 else f"{url}/page/{page}"
        soup = fetch(page_url)
        if not soup:
            break

        sections = soup.select("div.tw-section")
        if not sections:
            break

        for sec in sections:
            name_el = sec.select_one(".tw-name a span") or sec.select_one(".tw-name a")
            date_el = sec.select_one(".tw-event-date")
            time_el = sec.select_one(".tw-event-time")
            supp_el = sec.select_one(".tw-attractions")
            tix_el  = sec.select_one("a.tw-buy-tix-btn")

            if not name_el or not date_el:
                continue

            date = parse_date(date_el.get_text(strip=True))
            if not date or date < NOW:
                continue

            artist  = name_el.get_text(strip=True)
            dedup_key = (artist.lower(), date.date())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            support = [s.get_text(strip=True) for s in supp_el.select("span")] if supp_el else []

            shows.append({
                "venue":   venue_name,
                "city":    city,
                "artist":  artist,
                "support": [s for s in support if s],
                "date":    date,
                "time":    time_el.get_text(strip=True) if time_el else "",
                "ticket":  tix_el["href"] if tix_el else "",
            })

        time.sleep(0.4)

    return shows


def scrape_boomboom():
    print("  Boom Boom Room...")
    shows = []
    soup  = fetch("https://boomboomroom.com/events/")
    if not soup:
        return shows

    # ETIX-powered WordPress site — events in article tags or divs with h4 headings
    for event in soup.select("article, .event, .tribe_events_cat"):
        name_el = event.select_one("h4, h3, h2, .tribe-events-list-event-title a, .entry-title a")
        date_el = event.select_one(
            ".tribe-event-date-start, abbr.tribe-events-abbr, time, "
            ".tribe-events-schedule abbr, .tribe-events-start-datetime"
        )
        link_el = event.select_one("a[href]")
        if not name_el:
            continue
        date_text = date_el.get("title", "") or (date_el.get_text(strip=True) if date_el else "")
        date = parse_date(date_text)
        if not date or date < NOW:
            continue
        href = link_el["href"] if link_el else ""
        shows.append({"venue": "Boom Boom Room", "city": "San Francisco",
                       "artist": name_el.get_text(strip=True), "support": [],
                       "date": date, "time": "", "ticket": href})
    return shows


def scrape_rickshaw(max_pages=5):
    print("  Rickshaw Stop...")
    shows = []

    for page in range(1, max_pages + 1):
        url  = ("https://rickshawstop.com/calendar" if page == 1
                else f"https://rickshawstop.com/calendar?page={page}")
        soup = fetch(url)
        if not soup:
            break

        # Squarespace calendar/list structure
        events = soup.select(".eventlist-event")
        if not events:
            break

        for event in events:
            name_el = event.select_one(".eventlist-title a, h1.eventlist-title")
            date_el = event.select_one("time.dt-start, .eventlist-meta-date")
            link_el = event.select_one("a.eventlist-title-link, .eventlist-title a")
            if not name_el:
                continue
            date_str = (date_el.get("datetime", "") if date_el else "") or \
                       (date_el.get_text(strip=True) if date_el else "")
            date = parse_date(date_str)
            if not date or date < NOW:
                continue
            href = link_el["href"] if link_el else ""
            if href and href.startswith("/"):
                href = "https://rickshawstop.com" + href
            shows.append({"venue": "Rickshaw Stop", "city": "San Francisco",
                           "artist": name_el.get_text(strip=True), "support": [],
                           "date": date, "time": "", "ticket": href})

        time.sleep(0.4)

    return shows


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading your artist library...")
    known = load_known_artists()
    print(f"  {len(known):,} artists loaded.\n")
    print("Scraping venues...\n")

    all_shows = []
    all_shows += scrape_yoshis()
    all_shows += scrape_timewire("https://cafedunord.com/calendar",              "Café du Nord",   "San Francisco")
    all_shows += scrape_timewire("https://www.brickandmortarmusic.com/shows",    "Brick & Mortar", "San Francisco")
    all_shows += scrape_boomboom()
    all_shows += scrape_rickshaw()

    all_shows.sort(key=lambda x: x["date"])

    your_shows = [s for s in all_shows if is_known(s["artist"], known)]
    new_shows  = [s for s in all_shows if not is_known(s["artist"], known)]

    print(f"\n{'='*65}")
    print(f"YOUR ARTISTS  —  {len(your_shows)} show(s)")
    print(f"{'='*65}")
    for s in your_shows:
        _print_show(s)

    print(f"\n{'='*65}")
    print(f"DISCOVER AT YOUR VENUES  —  {len(new_shows)} show(s)")
    print(f"{'='*65}")
    for s in new_shows:
        _print_show(s)

    print(f"\n\nNOTE: The Chapel and The Independent use JavaScript rendering")
    print(f"and cannot be scraped without a browser. Coming in the next update.")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(f"Bay Area Venue Shows — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("Venues: Yoshi's · Café du Nord · Brick & Mortar · Boom Boom Room · Rickshaw Stop\n")
        f.write(f"{'='*65}\n\n")
        f.write(f"YOUR ARTISTS ({len(your_shows)} shows)\n{'='*65}\n")
        for s in your_shows:
            f.write(_format_show(s) + "\n")
        f.write(f"\nDISCOVER AT YOUR VENUES ({len(new_shows)} shows)\n{'='*65}\n")
        for s in new_shows:
            f.write(_format_show(s) + "\n")

    print(f"\nResults saved to {OUTPUT_PATH}")


def _print_show(s):
    date_str    = s["date"].strftime("%a %b %d, %Y")
    support_str = f"  w/ {', '.join(s['support'])}" if s.get("support") else ""
    time_str    = f"  {s['time']}" if s.get("time") else ""
    print(f"\n  {s['artist']}{support_str}")
    print(f"  {date_str}{time_str}  |  {s['venue']}, {s['city']}")
    if s.get("ticket"):
        print(f"  {s['ticket']}")


def _format_show(s):
    date_str    = s["date"].strftime("%a %b %d, %Y")
    support_str = f" w/ {', '.join(s['support'])}" if s.get("support") else ""
    time_str    = f"  {s['time']}" if s.get("time") else ""
    lines = [
        f"\n{s['artist']}{support_str}",
        f"  {date_str}{time_str}  |  {s['venue']}, {s['city']}",
    ]
    if s.get("ticket"):
        lines.append(f"  {s['ticket']}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
