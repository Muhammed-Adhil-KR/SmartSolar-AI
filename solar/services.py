"""
Geocoding service using Open-Meteo's free Geocoding API.
Kept separate from views so the API call is testable independently.
"""
import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


def search_locations(query, count=5):
    """
    Forward geocoding using Nominatim (OpenStreetMap). Unlike Open-Meteo's
    geocoding API, this can resolve villages/hamlets/rural areas, not just
    major cities — because OSM's database is community-mapped.
    Encourage users to type a full address (village, district, state) for
    best results with obscure places.
    """
    try:
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params={"q": query, "format": "json", "limit": count, "addressdetails": 1},
            headers={"User-Agent": "SolarDSS-MCA-Project/1.0"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data:
        try:
            results.append({
                "display_name": item.get("display_name", query),
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return results


def reverse_geocode(latitude, longitude):
    """
    Converts coordinates into a human-readable place name using Nominatim.
    Returns None on failure — caller must handle that.
    """
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={"lat": latitude, "lon": longitude, "format": "json", "zoom": 14, "addressdetails": 1},
            headers={"User-Agent": "SolarDSS-MCA-Project/1.0"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    address = data.get("address", {})
    place = (
        address.get("village") or address.get("town") or address.get("hamlet")
        or address.get("suburb") or address.get("city") or address.get("county")
    )
    state = address.get("state", "")
    country = address.get("country", "")
    parts = [p for p in [place, state, country] if p]
    return ", ".join(parts) if parts else data.get("display_name")


from .models import Battery, GridConfiguration


def sync_system_dependencies(user, system):
    """
    Called after a system_type change. Deletes Battery/GridConfiguration
    records that are no longer applicable to the new type, so stale data
    never lingers in the database for a section the user can no longer see.
    Uses direct queryset deletion (not cached instance attributes) to avoid
    Django's related-object caching giving a false "still exists" reading
    within the same request.
    """
    removed = []
    if not system.needs_battery:
        deleted, _ = Battery.objects.filter(user=user).delete()
        if deleted:
            removed.append('battery settings')
    if not system.needs_grid_config:
        deleted, _ = GridConfiguration.objects.filter(user=user).delete()
        if deleted:
            removed.append('grid settings')
    return removed