"""
shaking.py - how hard the ground could shake at the user's address.

Two steps, both using free public services (no API key needed):

  1. Address -> latitude/longitude ("geocoding").
     First the U.S. Census Bureau geocoder (works for full street addresses),
     then OpenStreetMap's Nominatim (also understands "Redmond, WA").

  2. Latitude/longitude -> expected shaking, from the USGS Seismic Design
     Maps web service for the ASCE 7-22 building code:
        https://earthquake.usgs.gov/ws/designmaps/asce7-22.json
     We use the value "pgam": the peak ground acceleration (in g) for the
     Maximum Considered Earthquake, adjusted for the local soil. It's the
     shaking engineers design buildings to survive: a rare, very strong
     earthquake, such as a Cascadia Subduction Zone event or a big Seattle
     Fault quake. For Redmond it is about 0.67 g.

If the internet or a service is down, we fall back to values for nearby
cities that were looked up from the same USGS service in October 2026.
"""

import json
import urllib.parse
import urllib.request

USGS_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_S = 8

# pgam (g) from the USGS ASCE 7-22 service, site class "Default", risk II.
FALLBACK_CITIES = {
    "redmond":     {"lat": 47.674, "lon": -122.121, "pga": 0.67},
    "seattle":     {"lat": 47.606, "lon": -122.332, "pga": 0.73},
    "bellevue":    {"lat": 47.610, "lon": -122.202, "pga": 0.70},
    "kirkland":    {"lat": 47.682, "lon": -122.209, "pga": 0.56},
    "bothell":     {"lat": 47.760, "lon": -122.205, "pga": 0.67},
    "woodinville": {"lat": 47.754, "lon": -122.164, "pga": 0.67},
    "sammamish":   {"lat": 47.616, "lon": -122.036, "pga": 0.67},
    "snohomish":   {"lat": 47.913, "lon": -122.098, "pga": 0.65},
    "everett":     {"lat": 47.979, "lon": -122.202, "pga": 0.66},
}
DEFAULT_CITY = "redmond"


def _get_json(url: str, params: dict) -> dict:
    """Small helper: GET a URL with query parameters and parse the JSON."""
    full_url = url + "?" + urllib.parse.urlencode(params)
    # Nominatim's rules ask every app to identify itself.
    request = urllib.request.Request(full_url, headers={"User-Agent": "QuakeReady student app"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode(address: str):
    """Turn an address into (lat, lon, matched_name), or None if not found."""
    try:
        data = _get_json(CENSUS_URL, {"address": address,
                                      "benchmark": "Public_AR_Current",
                                      "format": "json"})
        matches = data["result"]["addressMatches"]
        if matches:
            c = matches[0]["coordinates"]
            return c["y"], c["x"], matches[0]["matchedAddress"]
    except Exception:
        pass  # fall through to the next geocoder

    try:
        results = _get_json(NOMINATIM_URL, {"q": address, "format": "json",
                                            "limit": 1, "countrycodes": "us"})
        if results:
            r = results[0]
            return float(r["lat"]), float(r["lon"]), r["display_name"]
    except Exception:
        pass
    return None


def usgs_pga(lat: float, lon: float) -> float:
    """Ask USGS for the design peak ground acceleration (g) at a point."""
    data = _get_json(USGS_URL, {"latitude": round(lat, 4), "longitude": round(lon, 4),
                                "riskCategory": "II", "siteClass": "Default",
                                "title": "QuakeReady"})
    return float(data["response"]["data"]["pgam"])


# Remember successful lookups so the same address is instant next time
# (and we don't spam USGS). Failures aren't remembered, so they get retried.
_cache: dict[str, dict] = {}


def lookup(address: str) -> dict:
    """Main entry point. Always returns a result (never raises).

    {"pga": 0.67, "place": "...", "lat": .., "lon": .., "source": "usgs" | "fallback"}
    """
    address = (address or "").strip()
    if address in _cache:
        return _cache[address]
    if address:
        try:
            found = geocode(address)
            if found:
                lat, lon, place = found
                result = {"pga": usgs_pga(lat, lon), "place": place,
                          "lat": lat, "lon": lon, "source": "usgs"}
                _cache[address] = result
                return result
        except Exception:
            pass  # network problem: use the offline table below

    # Offline fallback: find a known city name inside what the user typed.
    city = next((c for c in FALLBACK_CITIES if c in address.lower()), DEFAULT_CITY)
    info = FALLBACK_CITIES[city]
    return {"pga": info["pga"], "place": city.title() + ", WA",
            "lat": info["lat"], "lon": info["lon"], "source": "fallback"}
