import requests
import time
from datetime import datetime, timezone

# --- Config ---
LASTFM_API_KEY = "98911dfeb5e40162072b3bc1af478cd1"
LASTFM_USER    = "thoM_Moht"
BIT_APP_ID     = "concert_finder_thoM"

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

def get_top_artists():
    print(f"Fetching top {ARTIST_LIMIT} artists for {LASTFM_USER} ({PERIOD})...")
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
    return [(a["name"], int(a["playcount"])) for a in artists]


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
    artists = get_top_artists()
    print(f"Got {len(artists)} artists. Searching for Bay Area shows...\n")

    shows = []
    now   = datetime.now(timezone.utc)

    for i, (artist, plays) in enumerate(artists, 1):
        print(f"  [{i:>3}/{len(artists)}] {artist} ({plays:,} plays)", end="\r")
        events = get_events(artist)
        for ev in events:
            if not is_bay_area(ev):
                continue
            date = parse_date(ev.get("datetime", ""))
            if date and date > now:
                venue = ev.get("venue", {})
                offers = ev.get("offers", [])
                shows.append({
                    "artist":   artist,
                    "plays":    plays,
                    "date":     date,
                    "venue":    venue.get("name", "Unknown venue"),
                    "city":     venue.get("city", ""),
                    "lineup":   ev.get("lineup", []),
                    "info_url": ev.get("url", ""),
                    "ticket":   offers[0].get("url", "") if offers else "",
                })
        time.sleep(0.15)   # be polite to the API

    print(" " * 70)  # clear the progress line

    if not shows:
        print("No upcoming Bay Area shows found for your top artists.")
        return

    shows.sort(key=lambda x: x["date"])

    # --- Print results ---
    print(f"\nFound {len(shows)} upcoming Bay Area show(s):\n")
    print("=" * 65)

    for s in shows:
        date_fmt = s["date"].strftime("%a  %b %d, %Y  %I:%M %p")
        others   = [x for x in s["lineup"] if x.lower() != s["artist"].lower()]
        print(f"\n{s['artist']}  ({s['plays']:,} plays)")
        print(f"  {date_fmt}")
        print(f"  {s['venue']}, {s['city']}")
        if others:
            print(f"  Also on bill: {', '.join(others)}")
        if s["info_url"]:
            print(f"  Info:    {s['info_url']}")
        if s["ticket"]:
            print(f"  Tickets: {s['ticket']}")

    # --- Save to file ---
    out_path = r"C:\Users\Thomas\AI\upcoming_shows.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Bay Area Shows — pulled {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Based on Last.fm top {ARTIST_LIMIT} artists ({PERIOD})\n")
        f.write("=" * 65 + "\n")
        for s in shows:
            date_fmt = s["date"].strftime("%a  %b %d, %Y  %I:%M %p")
            others   = [x for x in s["lineup"] if x.lower() != s["artist"].lower()]
            f.write(f"\n{s['artist']}  ({s['plays']:,} plays)\n")
            f.write(f"  {date_fmt}\n")
            f.write(f"  {s['venue']}, {s['city']}\n")
            if others:
                f.write(f"  Also on bill: {', '.join(others)}\n")
            if s["info_url"]:
                f.write(f"  Info:    {s['info_url']}\n")
            if s["ticket"]:
                f.write(f"  Tickets: {s['ticket']}\n")

    print(f"\n\nResults also saved to {out_path}")


if __name__ == "__main__":
    main()
