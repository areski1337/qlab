"""Client de l'API officielle FXStreet Economic Calendar (OAuth2 v2, client credentials).

Les clés (publique/privée) sont fournies par FXStreet à ses clients. Elles sont lues
UNIQUEMENT depuis les variables d'environnement QLAB_FXSTREET_CLIENT_ID et
QLAB_FXSTREET_CLIENT_SECRET : jamais écrites en base, en fichier ou dans les journaux.
Spécification : https://calendar-api.fxstreet.com/swagger/v1/openapi.json
Conditions FXStreet : reproduction interdite hors usage personnel et privé — les
événements restent locaux et ne sont pas inclus dans les exports.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://authorization.fxstreet.com/v2/token"
API = "https://calendar-api.fxstreet.com/en/api/v1"
SOURCE = "fxstreet"
MAX_DAYS = 30  # taille des requêtes par plage de dates


class FXStreetUnavailable(RuntimeError):
    pass


def credentials() -> tuple[str, str] | None:
    cid, sec = os.environ.get("QLAB_FXSTREET_CLIENT_ID"), os.environ.get("QLAB_FXSTREET_CLIENT_SECRET")
    return (cid, sec) if cid and sec else None


_token: dict = {}


def token() -> str:
    if _token.get("exp", 0) > time.time() + 60:
        return _token["v"]
    cred = credentials()
    if cred is None:
        raise FXStreetUnavailable("clés FXStreet absentes : définir QLAB_FXSTREET_CLIENT_ID et QLAB_FXSTREET_CLIENT_SECRET")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cred[0], "client_secret": cred[1],
                                   "scope": "calendar"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
    except Exception as e:  # pas de détail de requête : il contiendrait les clés
        raise FXStreetUnavailable(f"échec d'authentification FXStreet ({type(e).__name__})") from None
    _token.update(v=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)))
    return _token["v"]


def _iso(t: int) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_range(start_ts: int, end_ts: int) -> list[dict]:
    """Événements de [start, end) en UTC. Lève FXStreetUnavailable en cas d'échec (jamais de liste vide inventée)."""
    out = []
    a = start_ts
    while a < end_ts:
        b = min(end_ts, a + MAX_DAYS * 86400)
        url = f"{API}/eventDates/{urllib.parse.quote(_iso(a))}/{urllib.parse.quote(_iso(b))}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out += json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:  # « Event occurrencies not found » : plage vide mais couverte
                pass
            else:
                raise FXStreetUnavailable(f"API FXStreet : HTTP {e.code} sur {_iso(a)} → {_iso(b)}") from None
        except Exception as e:
            raise FXStreetUnavailable(f"API FXStreet injoignable ({type(e).__name__})") from None
        a = b
    return out


def normalize(ev: dict) -> dict:
    t = int(dt.datetime.fromisoformat(ev["dateUtc"].replace("Z", "+00:00")).timestamp())
    return {"id": f"{SOURCE}:{ev['id']}", "event_id": ev.get("eventId"), "date_ts": t,
            "currency": ev.get("currencyCode"), "country": ev.get("countryCode"), "name": ev.get("name"),
            "volatility": ev.get("volatility"), "is_tentative": bool(ev.get("isTentative")),
            "is_all_day": bool(ev.get("isAllDay")), "actual": ev.get("actual"), "consensus": ev.get("consensus"),
            "previous": ev.get("previous"), "last_updated": ev.get("lastUpdated")}
