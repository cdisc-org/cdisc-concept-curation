"""Tests for the release-package methods on CDISCApiClient."""

from unittest.mock import patch

import requests

from services import api_cache
from services.cdisc_api import CDISCApiClient


def _client():
    return CDISCApiClient()


def test_get_bc_packages_returns_links():
    with patch.object(CDISCApiClient, "_get", return_value={"_links": {"packages": [{"href": "/mdr/bc/packages/2023-02-13/biomedicalconcepts"}]}}) as g:
        out = _client().get_bc_packages()
    g.assert_called_once_with("/mdr/bc/packages")
    assert out == [{"href": "/mdr/bc/packages/2023-02-13/biomedicalconcepts"}]


def test_get_spec_packages_uses_sdtm_path():
    with patch.object(CDISCApiClient, "_get", return_value={"_links": {"packages": []}}) as g:
        _client().get_spec_packages()
    g.assert_called_once_with("/mdr/specializations/sdtm/packages")


def test_get_package_bcs_and_specs_paths():
    with patch.object(CDISCApiClient, "_get", side_effect=[{"_links": {"biomedicalConcepts": [{"href": "a"}]}}, {"_links": {"datasetSpecializations": [{"href": "b"}]}}]) as g:
        c = _client()
        assert c.get_package_bcs("2023-02-13") == [{"href": "a"}]
        assert c.get_package_specs("2023-02-13") == [{"href": "b"}]
    assert [x.args[0] for x in g.call_args_list] == [
        "/mdr/bc/packages/2023-02-13/biomedicalconcepts",
        "/mdr/specializations/sdtm/packages/2023-02-13/datasetspecializations",
    ]


def test_get_package_item_detail_paths():
    with patch.object(CDISCApiClient, "_get", return_value={"x": 1}) as g:
        c = _client()
        c.get_package_bc("2023-02-13", "C1")
        c.get_package_spec("2023-02-13", "S1")
    assert [x.args[0] for x in g.call_args_list] == [
        "/mdr/bc/packages/2023-02-13/biomedicalconcepts/C1",
        "/mdr/specializations/sdtm/packages/2023-02-13/datasetspecializations/S1",
    ]


def test_errors_become_error_entries():
    with patch.object(CDISCApiClient, "_get", side_effect=requests.RequestException("down")):
        c = _client()
        assert c.get_bc_packages() == [{"error": "down"}]
        assert c.get_package_bcs("2023-02-13") == [{"error": "down"}]
        assert c.get_package_bc("2023-02-13", "C1") == {"error": "down"}
        assert c.get_package_spec("2023-02-13", "S1") == {"error": "down"}


def _age(client, cache_name, seconds):
    """Make the cached entry stale (older than the fresh TTL, newer than the stale TTL)."""
    key = client._cache_key(cache_name)
    ts, data = api_cache._cache[key]
    api_cache._cache[key] = (ts - seconds, data)


def test_list_failure_after_success_serves_stale_data():
    good = {"_links": {"packages": [{"href": "/mdr/bc/packages/2023-02-13/biomedicalconcepts"}]}}
    c = _client()
    with patch.object(CDISCApiClient, "_get", return_value=good):
        first = c.get_bc_packages()
    _age(c, "bc_packages", api_cache.CACHE_TTL + 10)
    with patch.object(CDISCApiClient, "_get", side_effect=requests.RequestException("down")):
        assert c.get_bc_packages() == first  # stale data, not an error marker


def test_detail_failure_after_success_serves_stale_data():
    c = _client()
    with patch.object(CDISCApiClient, "_get", return_value={"conceptId": "C1"}):
        c.get_package_bc("2023-02-13", "C1")
    _age(c, "bc_package:2023-02-13:C1", api_cache.CACHE_TTL + 10)
    with patch.object(CDISCApiClient, "_get", side_effect=requests.RequestException("down")):
        assert c.get_package_bc("2023-02-13", "C1") == {"conceptId": "C1"}


def test_list_error_is_not_cached():
    c = _client()
    with patch.object(CDISCApiClient, "_get", side_effect=requests.RequestException("down")):
        assert c.get_package_bcs("2023-02-13") == [{"error": "down"}]
    with patch.object(CDISCApiClient, "_get", return_value={"_links": {"biomedicalConcepts": [{"href": "a"}]}}):
        assert c.get_package_bcs("2023-02-13") == [{"href": "a"}]  # recovered immediately


def test_detail_error_is_not_cached():
    c = _client()
    with patch.object(CDISCApiClient, "_get", side_effect=requests.RequestException("down")):
        assert c.get_package_bc("2023-02-13", "C1") == {"error": "down"}
    with patch.object(CDISCApiClient, "_get", return_value={"conceptId": "C1"}):
        assert c.get_package_bc("2023-02-13", "C1") == {"conceptId": "C1"}


def test_domain_keyed_spec_links_are_flattened():
    data = {"_links": {"datasetSpecializations": {"sdtm": [{"href": "a"}], "cdash": [{"href": "b"}]}}}
    with patch.object(CDISCApiClient, "_get", return_value=data):
        assert _client().get_package_specs("2023-02-13") == [{"href": "a"}, {"href": "b"}]
