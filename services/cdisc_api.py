import hashlib
import logging
import os
from urllib.parse import quote

import requests
from flask import current_app

from services.api_cache import CACHE_STALE_TTL as _CACHE_STALE_TTL  # noqa: F401
from services.api_cache import CACHE_TTL as _CACHE_TTL  # noqa: F401
from services.api_cache import _cache, cached  # noqa: F401  (_cache re-exported for tests)

logger = logging.getLogger(__name__)

# Backward-compatible alias — the shared implementation lives in
# services/api_cache.py and is used by all three API clients.
_cached = cached

# The CDISC Library's general MDR API (Controlled Terminology packages,
# codelists) lives on a different host/path than the COSMoS-specific base
# used for BCs/specializations above.
LIBRARY_BASE_URL = "https://library.cdisc.org/api"

# CDISC SDTM Domain Abbreviation codelist (submissionValue = the 2-8 char
# domain code, e.g. "LB", "VS", "AE").
SDTM_DOMAIN_CODELIST = "C66734"


def _config_value(name, default=""):
    """Read a config value from the Flask app when a context is active,
    falling back to the environment (the MCP server and scripts run
    without a request context)."""
    try:
        return current_app.config.get(name) or os.environ.get(name, default)
    except RuntimeError:
        return os.environ.get(name, default)


class CDISCApiClient:
    def __init__(self):
        self.api_key = _config_value("CDISC_API_KEY")
        self.subscription_key = _config_value("CDISC_SUBSCRIPTION_KEY")
        self.base_url = _config_value("CDISC_API_BASE_URL", "https://api.library.cdisc.org/api/cosmos/v2")
        # Auth parity with soa-workbench: prefer the subscription key with
        # its Ocp header, fall back to the classic api-key header.
        if self.subscription_key:
            auth_header = {"Ocp-Apim-Subscription-Key": self.subscription_key}
            key_material = self.subscription_key
        else:
            auth_header = {"api-key": self.api_key}
            key_material = self.api_key
        self.headers = {**auth_header, "Accept": "application/json"}
        # Stable, non-secret digest of the active key for use in cache keys
        self._key_digest = hashlib.sha256(key_material.encode()).hexdigest()[:8]

    def _cache_key(self, endpoint):
        return (self.base_url, self._key_digest, endpoint)

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self.headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def _get_library(self, path):
        """GET against the general CDISC Library MDR API (LIBRARY_BASE_URL),
        as opposed to the COSMoS-specific base used by _get()."""
        url = f"{LIBRARY_BASE_URL}{path}"
        response = requests.get(url, headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_biomedical_concepts(self):
        """
        List all BCs from the CDISC Library.
        Returns list of {href, title, type} link objects (~1127 items).
        Response shape:
            {name, label, _links: {biomedicalConcepts: [{href, ...}]}}
        """

        def _fetch():
            try:
                data = self._get("/mdr/bc/biomedicalconcepts")
                return data.get("_links", {}).get("biomedicalConcepts", [])
            except (requests.RequestException, ValueError) as e:
                logger.error("CDISC Library BC list fetch failed (%s): %s", self.base_url, e)
                return [{"error": str(e)}]

        return _cached(self._cache_key("biomedical_concepts"), _fetch)

    def get_bc(self, concept_id):
        """Fetch a single BC by conceptId."""
        try:
            return self._get(f"/mdr/bc/biomedicalconcepts/{concept_id}")
        except (requests.RequestException, ValueError) as e:
            logger.error("CDISC Library BC fetch failed for %s: %s", concept_id, e)
            return {"error": str(e)}

    def get_specialization(self, href):
        """Fetch a single dataset specialization by its href path."""
        try:
            return self._get(href)
        except (requests.RequestException, ValueError) as e:
            logger.error("CDISC Library specialization fetch failed for %s: %s", href, e)
            return {"error": str(e)}

    def get_dataset_specializations(self):
        """
        List all dataset specializations from the CDISC Library.
        Returns list of {href, title, type} link objects (~1123 items).
        Response shape:
            {name, label, _links: {datasetSpecializations: {...}}}
        """

        def _fetch():
            try:
                data = self._get("/mdr/specializations/datasetspecializations")
                links = data.get("_links", {}).get("datasetSpecializations", [])
                # API returns either a flat list or a domain-keyed dict (sdtm/cdash/…)
                if isinstance(links, list):
                    return links
                return [item for v in links.values() if isinstance(v, list) for item in v]
            except (requests.RequestException, ValueError) as e:
                logger.error("CDISC Library specialization list fetch failed (%s): %s", self.base_url, e)
                return [{"error": str(e)}]

        return _cached(self._cache_key("dataset_specializations"), _fetch)

    # ── Release packages (BC / SDTM dataset specialization) ────────────

    def _cached_or_error(self, cache_name, fetch, on_error):
        """Run ``fetch`` through the shared stale-tolerant cache.

        ``fetch`` must RAISE on failure so ``cached()`` can fall back to a
        stale entry; only if there is no usable stale data does the error
        surface here, where it becomes an error marker that is returned to
        the caller but never stored in the cache.
        """
        try:
            return _cached(self._cache_key(cache_name), fetch)
        except (requests.RequestException, ValueError) as e:
            logger.error("CDISC Library fetch failed for %s: %s", cache_name, e)
            return on_error(str(e))

    def _list_links(self, cache_name, path, link_key):
        def _fetch():
            links = self._get(path).get("_links", {}).get(link_key, [])
            if isinstance(links, dict):  # domain-keyed (sdtm/cdash/...) shape
                return [item for v in links.values() if isinstance(v, list) for item in v]
            return links if isinstance(links, list) else []

        return self._cached_or_error(cache_name, _fetch, lambda msg: [{"error": msg}])

    def get_bc_packages(self):
        """List released BC packages: [{href, title, type}, ...]."""
        return self._list_links("bc_packages", "/mdr/bc/packages", "packages")

    def get_spec_packages(self):
        """List released SDTM dataset specialization packages."""
        return self._list_links("spec_packages", "/mdr/specializations/sdtm/packages", "packages")

    def get_package_bcs(self, date):
        """List the BCs contained in the BC package effective on ``date``."""
        return self._list_links(f"bc_package:{date}", f"/mdr/bc/packages/{date}/biomedicalconcepts", "biomedicalConcepts")

    def get_package_specs(self, date):
        """List the SDTM specializations in the package effective on ``date``."""
        return self._list_links(f"spec_package:{date}", f"/mdr/specializations/sdtm/packages/{date}/datasetspecializations", "datasetSpecializations")

    def get_sdtm_spec_domains(self):
        """List the SDTM domains that have dataset specializations: [{name}, ...]
        (or [{"error": msg}]). Order is as returned by the Library."""

        def _fetch():
            data = self._get("/mdr/specializations/sdtm/domains")
            return [{"name": d["name"]} for d in data.get("domains", []) if d.get("name")]

        return self._cached_or_error("sdtm_spec_domains", _fetch, lambda msg: [{"error": msg}])

    def get_domain_specs(self, domain):
        """List the SDTM dataset specializations for one domain as {href, title} links."""
        return self._list_links(f"domain_specs:{domain}", f"/mdr/specializations/sdtm/datasetspecializations?domain={quote(domain, safe='')}", "datasetSpecializations")

    def get_bc_categories(self):
        """List the BC categories: [{name}, ...] (or [{"error": msg}]).
        Order is as returned by the Library."""

        def _fetch():
            cats = self._get("/mdr/bc/categories").get("_links", {}).get("categories", [])
            return [{"name": c["name"]} for c in cats if c.get("name")]

        return self._cached_or_error("bc_categories", _fetch, lambda msg: [{"error": msg}])

    def get_category_bcs(self, category):
        """List the BCs in one category as {href, title} links."""
        return self._list_links(f"category_bcs:{category}", f"/mdr/bc/biomedicalconcepts?category={quote(category, safe='')}", "biomedicalConcepts")

    def _get_detail(self, cache_name, path):
        return self._cached_or_error(cache_name, lambda: self._get(path), lambda msg: {"error": msg})

    def get_package_bc(self, date, concept_id):
        """Fetch one BC as it appears in the package effective on ``date``."""
        return self._get_detail(f"bc_package:{date}:{concept_id}", f"/mdr/bc/packages/{date}/biomedicalconcepts/{concept_id}")

    def get_package_spec(self, date, spec_id):
        """Fetch one SDTM specialization as it appears in a package."""
        return self._get_detail(f"spec_package:{date}:{spec_id}", f"/mdr/specializations/sdtm/packages/{date}/datasetspecializations/{spec_id}")

    def get_ct_packages(self):
        """
        List all Controlled Terminology packages from the CDISC Library
        (every product family — sdtmct, adamct, cdashct, ... — and every
        dated version). Returns a list of {href, title, type} link objects.
        """

        def _fetch():
            try:
                data = self._get_library("/mdr/ct/packages")
                return data.get("_links", {}).get("packages", [])
            except (requests.RequestException, ValueError) as e:
                logger.error("CDISC Library CT package list fetch failed: %s", e)
                return [{"error": str(e)}]

        return _cached(self._cache_key("ct_packages"), _fetch)

    def get_sdtm_domain_codes(self):
        """
        Return the SDTM Domain Abbreviation codelist (C66734) terms from the
        most recent SDTM CT package.
        Returns a list of {"code": submissionValue, "label": preferredTerm}
        dicts sorted by code, e.g. [{"code": "AE", "label": "Adverse Event Domain"}, ...].
        """

        def _fetch():
            try:
                packages = self.get_ct_packages()
                sdtm_packages = sorted(
                    (p for p in packages if "href" in p and "error" not in p and p["href"].rstrip("/").split("/")[-1].startswith("sdtmct-")),
                    key=lambda p: p["href"],
                )
                if not sdtm_packages:
                    raise ValueError("No SDTM CT package found in the Library's package list")
                latest_href = sdtm_packages[-1]["href"]
                data = self._get_library(f"{latest_href}/codelists/{SDTM_DOMAIN_CODELIST}")
                codes = [{"code": t["submissionValue"], "label": t.get("preferredTerm", "")} for t in data.get("terms", []) if t.get("submissionValue")]
                codes.sort(key=lambda c: c["code"])
                return codes
            except (requests.RequestException, ValueError) as e:
                logger.error("CDISC Library SDTM domain codelist fetch failed: %s", e)
                return [{"error": str(e)}]

        return _cached(self._cache_key("sdtm_domain_codes"), _fetch)

    def check_duplicate(self, short_name):
        """
        Check if a BC with this short_name already exists in the library.
        """
        try:
            bcs = self.get_biomedical_concepts()
            return any(bc.get("title", "").lower() == short_name.lower() for bc in bcs)
        except (requests.RequestException, ValueError) as e:
            logger.error("CDISC Library duplicate check failed for %r: %s", short_name, e)
            return False

    def publish_bc(self, bc_data):
        """POST a new BC to the CDISC Library (requires write permission)."""
        url = f"{self.base_url}/mdr/bc/biomedicalconcepts"
        response = requests.post(url, headers=self.headers, json=bc_data, timeout=10)
        response.raise_for_status()
        return response.json()
