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

# Bay Area cities (lowercase for matching)
BAY_AREA = {
    "oakland", "san francisco", "berkeley", "emeryville", "alameda",
    "richmond", "el cerrito", "san jose", "santa clara", "palo alto",
    "mountain view", "sunnyvale", "fremont", "hayward", "concord",
    "walnut creek", "san mateo", "redwood city", "daly city",
    "south san francisco", "mill valley", "sausalito", "marin",
    "san rafael", "novato",
}

# How many top artists to pull from Last.fm
ARTIST_LIMIT = 100
# Period: overall | 12month | 6month | 3month | 1month | 7day
PERIOD = "overall"

# ---------------------------------------------------------------

def get_lastfm_artists():
    print(f"Fetching top {ARTIST_LIMIT} artists from Last.fm ({LASTFM_USER}, {PERIOD})...")
    resp = requests.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method":   "user.gettopartists",
            "user":     LASTFM_USER,
            "api_key":  LASTFM_API_KEY,
            "format":   "json",
            "limit":    ARTIST_LIMIT,
            "period":   PERIOD,
        },
        timeout=10,
    )
    resp.raise_for_status()
    artists = resp.json()["topartists"]["artist"]
    return {a["name"]: {"plays": int(a["playcount"]), "source": "lastfm"} for a in artists}


def get_tidal_artists():
    """Read TIDAL export: favorite artists + streaming history play counts."""
    artists = {}

    fav_path = os.path.join(USER_DATA_DIR, "favorite_artists.csv")
    if os.path.exists(fav_path):
        with open(fav_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row["artist_name"].strip()
                if name:
                    artists[name] = {"plays": 0, "source": "tidal_fav"}

    stream_path = os.path.join(USER_DATA_DIR, "streaming.csv")
    if os.path.exists(stream_path):
        print("Reading TIDAL streaming history (this may take a moment)...")
        stream_counts = defaultdict(int)
        with open(stream_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("artist_name", "").strip()
                if name:
                    stream_counts[name] += 1
        for name, count in stream_counts.items():
            if name in artists:
                artists[name]["plays"] = count
                artists[name]["source"] = "tidal"
            else:
                artists[name] = {"plays": count, "source": "tidal"}

    return artists


def merge_artists(lastfm, tidal):
    """Merge Last.fm and TIDAL artist dicts, preferring Last.fm play counts."""
    merged = dict(lastfm)
    lastfm_lower = {k.lower(): k for k in lastfm}

    for name, data in tidal.items():
        match = lastfm_lower.get(name.lower())
        if match:
            merged[match]["source"] = "both"
        else:
            merged[name] = data

    return merged


def get_events(artist_name):
    try:
        resp = requests.get(
            f"https://rest.bandsintown.com/artists/{requests.utils.quote(artist_name)}/events",
            params={"app_id": BIT_APP_ID},
            timeout=6,
        )
        if resp.status_code == 200:
            return resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        pass
    return []


def is_bay_area(event):
    venue   = event.get("venue", {})
    city    = venue.get("city", "").lower().strip()
    region  = venue.get("region", "").lower().strip()
    country = venue.get("country", "").lower().strip()

    if country not in ("united states", "us", "usa"):
        return False
    if region not in ("ca", "california"):
        return False
    return any(bc in city for bc in BAY_AREA)


def parse_date(dt_str):
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    lastfm = get_lastfm_artists()
    tidal  = get_tidal_artists()
    all_artists = merge_artists(lastfm, tidal)

    print(f"\nTotal artists to check: {len(all_artists)} "
          f"({len(lastfm)} Last.fm + {len(tidal)} TIDAL, merged)\n")
    print("Searching for Bay Area shows...\n")

    shows = []
    now   = datetime.now(timezone.utc)
    artist_list = list(all_artists.items())

    for i, (artist, data) in enumerate(artist_list, 1):
        print(f"  [{i:>3}/{len(artist_list)}] {artist}", end="\r")
        events = get_events(artist)
        for ev in events:
            if not is_bay_area(ev):
                continue
            date = parse_date(ev.get("datetime", ""))
            if date and date > now:
                venue  = ev.get("venue", {})
                offers = ev.get("offers", [])
                shows.append({
                    "artist":   artist,
                    "plays":    data["plays"],
                    "source":   data["source"],
                    "date":     date,
                    "venue":    venue.get("name", "Unknown venue"),
                    "city":     venue.get("city", ""),
                    "lineup":   ev.get("lineup", []),
                    "info_url": ev.get("url", ""),
                    "ticket":   offers[0].get("url", "") if offers else "",
                })
        time.sleep(0.15)

    print(" " * 70)

    if not shows:
        print("No upcoming Bay Area shows found for your artists.")
        return

    shows.sort(key=lambda x: x["date"])

    source_label = {"lastfm": "Last.fm", "tidal": "TIDAL", "tidal_fav": "TIDAL fav", "both": "Last.fm+TIDAL"}

    def format_show(s):
        date_fmt = s["date"].strftime("%a  %b %d, %Y  %I:%M %p")
        others   = [x for x in s["lineup"] if x.lower() != s["artist"].lower()]
        src      = source_label.get(s["source"], s["source"])
        lines    = [
            f"\n{s['artist']}  ({s['plays']:,} plays via {src})",
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

    print(f"\nFound {len(shows)} upcoming Bay Area show(s):\n")
    print("=" * 65)
    for s in shows:
        print(format_show(s))

    out_path = r"C:\Users\Thomas\AI\upcoming_shows.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Bay Area Shows — pulled {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Based on Last.fm top {ARTIST_LIMIT} ({PERIOD}) + TIDAL export\n")
        f.write("=" * 65 + "\n")
        for s in shows:
            f.write(format_show(s) + "\n")

    print(f"\n\nResults also saved to {out_path}")


if __name__ == "__main__":
    main()
