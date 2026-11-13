import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from services import package_service as ps
from services.cdisc_api import CDISCApiClient

logger = logging.getLogger(__name__)

bp = Blueprint("reports", __name__)

_DETAIL_FETCHERS = {"bc": "get_package_bc", "spec": "get_package_spec"}


def _require_date(value):
    if not ps.is_valid_date(value):
        abort(404)
    return value


@bp.route("/packages")
def packages():
    pkgs, errors = ps.list_packages(CDISCApiClient(), with_errors=True)
    return render_template("reports_packages.html", packages=pkgs, errors=errors)


@bp.route("/packages/<date>")
def package_detail(date):
    _require_date(date)
    contents = ps.package_contents(CDISCApiClient(), date)
    if not contents["bcs_available"] and not contents["specs_available"]:
        abort(404)
    return render_template("reports_package_detail.html", date=date, **contents)


@bp.route("/packages/<date>/<kind>/<item>")
def package_item(date, kind, item):
    _require_date(date)
    if kind not in _DETAIL_FETCHERS or not ps.is_valid_item_id(item):
        abort(404)
    data = getattr(CDISCApiClient(), _DETAIL_FETCHERS[kind])(date, item)
    if "error" in data:
        flash(f'Could not load {item} from package {date}: {data["error"]}', "danger")
        return redirect(url_for("reports.package_detail", date=date))
    return render_template("reports_package_item.html", date=date, kind=kind, item=item, rows=ps.detail_rows(data), title=data.get("shortName") or data.get("name") or data.get("title") or item)


@bp.route("/comparison")
def comparison():
    client = CDISCApiClient()
    pkgs, errors = ps.list_packages(client, with_errors=True)
    date_a = request.args.get("a", "").strip()
    date_b = request.args.get("b", "").strip()
    result = None
    warning = None
    if date_a or date_b:
        if not (ps.is_valid_date(date_a) and ps.is_valid_date(date_b)):
            abort(400)
        if date_a == date_b:
            warning = "Please select two different packages to compare."
        else:
            # Always compare older -> newer so Added/Removed read naturally.
            date_a, date_b = sorted((date_a, date_b))
            result = ps.compare_packages(client, date_a, date_b)
    return render_template("reports_comparison.html", packages=pkgs, errors=errors, a=date_a, b=date_b, result=result, warning=warning)


@bp.route("/comparison/diff")
def comparison_diff():
    kind = request.args.get("kind", "")
    item = request.args.get("id", "")
    date_a = request.args.get("a", "")
    date_b = request.args.get("b", "")
    if kind not in _DETAIL_FETCHERS or not ps.is_valid_item_id(item) or not (ps.is_valid_date(date_a) and ps.is_valid_date(date_b)):
        abort(400)
    client = CDISCApiClient()
    fetch = getattr(client, _DETAIL_FETCHERS[kind])
    a, b = fetch(date_a, item), fetch(date_b, item)
    error = a.get("error") or b.get("error")
    diffs = [] if error else ps.diff_items(a, b)
    return render_template("reports_diff_fragment.html", diffs=diffs, error=error, a=date_a, b=date_b)


@bp.route("/domains")
def domains():
    names, errors = ps.list_domains(CDISCApiClient(), with_errors=True)
    return render_template("reports_domains.html", domains=names, errors=errors)


@bp.route("/domains/<domain>")
def domain_detail(domain):
    client = CDISCApiClient()
    names, errors = ps.list_domains(client, with_errors=True)
    if domain not in names:
        if errors:  # can't tell whether the domain exists; surface the failure instead of a misleading 404
            flash(f'Could not load SDTM domains: {"; ".join(errors)}', "danger")
            return redirect(url_for("reports.domains"))
        abort(404)
    specs, spec_errors = ps.domain_specs(client, domain)
    return render_template("reports_domain_specs.html", domain=domain, specs=specs, errors=spec_errors, package_date=ps.latest_spec_package_date(client))
