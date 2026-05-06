import csv
import os
import requests
import time
from collections import defaultdict
from datetime import datetime, timezone

# --- Config ---
LASTFM_API_KEY = "98911dfeb5e40162072b3bc1af478cd1"
LASTFM_USER    = "thoM_Moht"
BIT_APP_ID     = "concert_finder_thoM"
USER_DATA_DIR  = r"C:\Users\Thomas\AI\concert-finder\user_data_26161906"

# How many of your top artists to use as seeds for recommendations
SEED_ARTIST_COUNT = 40
# How many similar artists Last.fm returns per seed
SIMILAR_LIMIT = 20
# Minimum number of seed artists that must recommend an artist to include it
MIN_MATCHES = 2

# Search locations — add trip cities here as {"city": "...", "region": "...", "country": "..."}
LOCATIONS = [
    {"label": "Bay Area",   "cities": {"oakland","san francisco","berkeley","emeryville","alameda","richmond","el cerrito","san jose","santa clara","palo alto","mountain view","sunnyvale","fremont","hayward","concord","walnut creek","san mateo","redwood city","daly city","south san francisco","mill valley","sausalito","marin","san rafael","novato"}, "region": "ca", "country": "united states"},
]

# Venues to always include regardless of artist familiarity
MUST_WATCH_VENUES = {"yoshi's", "yoshis", "yoshi's oakland"}


# ---------------------------------------------------------------

def get_known_artists():
    """All artists in streaming history (lowercase set for filtering)."""
    known = set()
    stream_path = os.path.join(USER_DATA_DIR, "streaming.csv")
    if os.path.exists(stream_path):
        with open(stream_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("artist_name", "").strip()
                if name:
                    known.add(name.lower())
    fav_path = os.path.join(USER_DATA_DIR, "favorite_artists.csv")
    if os.path.exists(fav_path):
        with open(fav_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("artist_name", "").strip()
                if name:
                    known.add(name.lower())
    return known


def get_top_seed_artists():
    """Top artists by stream count from TIDAL export."""
    counts = defaultdict(int)
    stream_path = os.path.join(USER_DATA_DIR, "streaming.csv")
    with open(stream_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("artist_name", "").strip()
            if name:
                counts[name] += 1
    return [name for name, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:SEED_ARTIST_COUNT]]


def get_similar(artist_name):
    try:
        resp = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method":   "artist.getSimilar",
                "artist":   artist_name,
                "api_key":  LASTFM_API_KEY,
                "format":   "json",
                "limit":    SIMILAR_LIMIT,
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        artists = data.get("similarartists", {}).get("artist", [])
        return [(a["name"], float(a["match"])) for a in artists]
    except Exception:
        return []


def get_events(artist_name):
    try:
        resp = requests.get(
            f"https://rest.bandsintown.com/artists/{requests.utils.quote(artist_name)}/events",
            params={"app_id": BIT_APP_ID},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def matches_location(event, loc):
    venue   = event.get("venue", {})
    city    = venue.get("city", "").lower().strip()
    region  = venue.get("region", "").lower().strip()
    country = venue.get("country", "").lower().strip()
    if country not in ("united states", "us", "usa") and country != loc["country"]:
        return False
    if region != loc["region"]:
        return False
    return any(c in city for c in loc["cities"])


def is_must_watch_venue(event):
    name = event.get("venue", {}).get("name", "").lower().strip()
    return any(v in name for v in MUST_WATCH_VENUES)


def parse_date(dt_str):
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    print("Loading your streaming history...")
    known   = get_known_artists()
    seeds   = get_top_seed_artists()
    print(f"Using {len(seeds)} seed artists. Finding similar artists via Last.fm...\n")

    # Map: artist_name -> {"score": float, "because": [seed1, seed2, ...]}
    candidates = defaultdict(lambda: {"score": 0.0, "because": []})

    for i, seed in enumerate(seeds, 1):
        print(f"  [{i:>2}/{len(seeds)}] {seed}", end="\r")
        for name, match in get_similar(seed):
            if name.lower() not in known:
                candidates[name]["score"]   += match
                candidates[name]["because"].append(seed)
        time.sleep(0.12)

    print(" " * 70)

    # Filter to artists recommended by at least MIN_MATCHES seeds
    filtered = {
        name: data for name, data in candidates.items()
        if len(data["because"]) >= MIN_MATCHES
    }
    ranked = sorted(filtered.items(), key=lambda x: x[1]["score"], reverse=True)

    print(f"Found {len(ranked)} recommended artists. Checking for upcoming shows...\n")

    shows = []
    now   = datetime.now(timezone.utc)

    # Also check known/seed artists for Yoshi's shows
    all_check = [(a, {"score": 0, "because": ["your library"]}, True) for a in seeds]
    all_check += [(a, d, False) for a, d in ranked]

    seen = set()
    for i, (artist, data, is_known) in enumerate(all_check, 1):
        print(f"  [{i:>3}/{len(all_check)}] {artist}", end="\r")
        events = get_events(artist)
        for ev in events:
            date = parse_date(ev.get("datetime", ""))
            if not date or date <= now:
                continue
            venue_name = ev.get("venue", {}).get("name", "Unknown venue")
            key = (artist, date.isoformat(), venue_name)
            if key in seen:
                continue

            at_yoshi  = is_must_watch_venue(ev)
            in_area   = any(matches_location(ev, loc) for loc in LOCATIONS)

            if not at_yoshi and (is_known or not in_area):
                continue

            seen.add(key)
            venue  = ev.get("venue", {})
            offers = ev.get("offers", [])
            label  = "Yoshi's Oakland" if at_yoshi else next(
                (loc["label"] for loc in LOCATIONS if matches_location(ev, loc)), "Unknown"
            )
            shows.append({
                "artist":   artist,
                "score":    data["score"],
                "because":  data["because"][:3],
                "location": label,
                "known":    is_known,
                "date":     date,
                "venue":    venue_name,
                "city":     venue.get("city", ""),
                "lineup":   ev.get("lineup", []),
                "info_url": ev.get("url", ""),
                "ticket":   offers[0].get("url", "") if offers else "",
            })
        time.sleep(0.15)

    print(" " * 70)

    if not shows:
        print("No upcoming shows found for recommended artists.")
        print(f"\nTop 20 recommended artists (no shows found):")
        for name, data in ranked[:20]:
            because = ", ".join(data["because"][:3])
            print(f"  {name}  — because you like {because}")
        return

    shows.sort(key=lambda x: x["date"])

    def format_show(s):
        date_fmt = s["date"].strftime("%a  %b %d, %Y  %I:%M %p")
        others   = [x for x in s["lineup"] if x.lower() != s["artist"].lower()]
        because  = ", ".join(s["because"])
        tag      = "[familiar]" if s["known"] else "[new to you]"
        lines    = [
            f"\n{s['artist']}  [{s['location']}]  {tag}",
            f"  Because you like: {because}",
            f"  {date_fmt}",
            f"  {s['venue']}, {s['city']}",
        ]
        if others:
            lines.append(f"  Also on bill: {', '.join(others)}")
        if s["info_url"]:
            lines.append(f"  Info:    {s['info_url']}")
        if s["ticket"]:
            lines.append(f"  Tickets: {s['ticket']}")
        return "\n".join(lines)

    print(f"\nFound {len(shows)} recommended shows:\n")
    print("=" * 65)
    for s in shows:
        print(format_show(s))

    out_path = r"C:\Users\Thomas\AI\recommended_shows.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Recommended Shows — pulled {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Based on {len(seeds)} top artists + Last.fm similarity\n")
        f.write("=" * 65 + "\n")
        for s in shows:
            f.write(format_show(s) + "\n")

    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
