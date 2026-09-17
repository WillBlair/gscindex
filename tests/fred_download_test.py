"""Public FRED downloads preserve the same observations used by API clients."""
from unittest.mock import Mock
import pytest
from data.providers import fred_client as fred


def test_public_download_parses_missing_values_and_dates(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred, "get_cached", lambda *a, **kw: None)
    save = Mock()
    monkeypatch.setattr(fred, "set_cached", save)
    response = Mock(text="observation_date,TEST\n2026-09-13,10\n2026-09-14,.\ninvalid,99\n2026-09-15,12\n")
    get = Mock(return_value=response)
    monkeypatch.setattr(fred.requests, "get", get)
    series = fred.fetch_fred_series("TEST")
    assert series.tolist() == [10, 12]
    assert series.index.strftime("%Y-%m-%d").tolist() == ["2026-09-13", "2026-09-15"]
    assert get.call_args.args[0].endswith("/graph/fredgraph.csv")
    assert "api_key" not in get.call_args.kwargs["params"]
    assert save.call_args.args[1]["values"] == [10, 12]


@pytest.mark.parametrize("body", ["<html>Service unavailable</html>", "observation_date,TEST\n2026-09-13,.\n"])
def test_bad_download_is_not_cached_as_data(monkeypatch, body):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred, "get_cached", lambda *a, **kw: None)
    save = Mock()
    monkeypatch.setattr(fred, "set_cached", save)
    monkeypatch.setattr(fred.requests, "get", Mock(return_value=Mock(text=body)))
    with pytest.raises(ValueError):
        fred.fetch_fred_series("TEST")
    save.assert_not_called()


def test_configured_key_keeps_authenticated_api(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(fred, "get_cached", lambda *a, **kw: None)
    monkeypatch.setattr(fred, "set_cached", Mock())
    response = Mock()
    response.json.return_value = {"observations": [{"date": "2026-09-15", "value": "12"}]}
    get = Mock(return_value=response)
    monkeypatch.setattr(fred.requests, "get", get)
    assert fred.fetch_fred_series("TEST").tolist() == [12]
    assert get.call_args.args[0] == fred._BASE_URL
    assert get.call_args.kwargs["params"]["api_key"] == "test-key"
