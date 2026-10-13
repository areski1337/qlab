import io
import json
import urllib.error

import pytest

from qlab.calendar import fxstreet, store
from qlab.core.timeutil import iso_to_ts
from qlab.lab import Lab
from qlab.risk.controller import DEFAULT_LIMITS

EV = [{"id": "e1", "eventId": "x", "dateUtc": "2026-03-06T13:30:00Z", "name": "Nonfarm Payrolls", "countryCode": "US",
       "currencyCode": "USD", "volatility": "HIGH", "isTentative": False, "isAllDay": False, "actual": None,
       "consensus": 150, "previous": 143},
      {"id": "e2", "eventId": "y", "dateUtc": "2026-03-06T09:00:00Z", "name": "PMI", "countryCode": "DE",
       "currencyCode": "EUR", "volatility": "HIGH", "isTentative": False, "isAllDay": False}]


@pytest.fixture
def lab(tmp_path):
    lab = Lab.open(tmp_path / "d")
    yield lab
    lab.close()


def test_refresh_windows_and_ea_file(lab, tmp_path):
    a, b = iso_to_ts("2026-03-01T00:00:00Z"), iso_to_ts("2026-03-31T00:00:00Z")
    r = store.refresh(lab, a, b, fetch=lambda s, e: EV)
    assert r["events"] == 2
    lim = {**DEFAULT_LIMITS, "news_filter": {"enabled": True, "before_min": 15, "after_min": 30, "min_volatility": "HIGH"}}
    w = store.windows_for(lab, {"currency_base": "XAU", "currency_profit": "USD"}, lim)
    nfp = iso_to_ts("2026-03-06T13:30:00Z")
    assert w.blocked_at(nfp - 600) and not w.blocked_at(nfp - 1200) and w.blocked_at(nfp + 1700)
    assert not w.blocked_at(iso_to_ts("2026-03-06T09:00:00Z"))  # EUR : hors devises de XAUUSD
    assert w.covered(nfp) and not w.covered(iso_to_ts("2026-04-02T00:00:00Z"))
    assert store.windows_for(lab, {"currency_profit": "USD"}, DEFAULT_LIMITS) is None  # filtre désactivé
    p = store.write_ea_file(tmp_path / "news.csv", w, True)
    lines = p.read_text().splitlines()
    assert lines[0] == "QLAB_NEWS;1;1" and f"COV;{a};{b}" in lines and any(l.startswith("BLK;") for l in lines)


def test_failed_fetch_records_no_coverage(lab):
    def boom(s, e):
        raise fxstreet.FXStreetUnavailable("panne")
    with pytest.raises(fxstreet.FXStreetUnavailable):
        store.refresh(lab, 0, 86400, fetch=boom)
    assert lab.con.execute("SELECT COUNT(*) FROM calendar_coverage").fetchone()[0] == 0


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("QLAB_FXSTREET_CLIENT_ID", raising=False)
    monkeypatch.delenv("QLAB_FXSTREET_CLIENT_SECRET", raising=False)
    fxstreet._token.clear()
    with pytest.raises(fxstreet.FXStreetUnavailable, match="clés FXStreet absentes"):
        fxstreet.token()


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_client_with_mocked_api(monkeypatch):
    monkeypatch.setenv("QLAB_FXSTREET_CLIENT_ID", "pub-id")
    monkeypatch.setenv("QLAB_FXSTREET_CLIENT_SECRET", "very-secret-key")
    fxstreet._token.clear()
    calls = []

    def fake(req, timeout=0):
        calls.append(req)
        if req.full_url == fxstreet.TOKEN_URL:
            assert b"scope=calendar" in req.data and b"grant_type=client_credentials" in req.data
            return Resp(json.dumps({"access_token": "tok", "token_type": "Bearer", "expires_in": 86399}).encode())
        assert req.headers["Authorization"] == "Bearer tok"
        if "/eventDates/2026-02" in req.full_url:  # seule la tranche commençant en février est vide
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
        return Resp(json.dumps(EV).encode())
    monkeypatch.setattr(fxstreet.urllib.request, "urlopen", fake)
    evs = fxstreet.fetch_range(iso_to_ts("2026-01-15T00:00:00Z"), iso_to_ts("2026-03-20T00:00:00Z"))
    assert len(evs) == 4  # 3 tranches de 30 jours, dont une vide (404 = aucune occurrence)
    assert sum(1 for c in calls if c.full_url == fxstreet.TOKEN_URL) == 1  # jeton mis en cache
    n = fxstreet.normalize(evs[0])
    assert n["date_ts"] == iso_to_ts("2026-03-06T13:30:00Z") and n["currency"] == "USD"

    def fail(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
    fxstreet._token.clear()
    monkeypatch.setattr(fxstreet.urllib.request, "urlopen", fail)
    with pytest.raises(fxstreet.FXStreetUnavailable) as ei:
        fxstreet.fetch_range(0, 86400)
    assert "very-secret-key" not in str(ei.value)
