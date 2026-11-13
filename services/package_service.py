"""Release-package reports: list packages, show contents, compare two packages.

Pure data-shaping over ``CDISCApiClient`` results; no Flask imports so the
logic is testable without a request context.
"""

import json
import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_RE = re.compile(r"^(?!\.+$)[A-Za-z0-9_.\-]+$")  # rejects dot-only ids ("." / "..")
_PKG_DATE_RE = re.compile(r"/packages/(\d{4}-\d{2}-\d{2})(?:/|$)")


def is_valid_date(value):
    return bool(value and _DATE_RE.match(value))


def is_valid_item_id(value):
    return bool(value and _ID_RE.match(value))


def package_date(href):
    """Extract the effective date from a package href, or None."""
    m = _PKG_DATE_RE.search(href or "")
    return m.group(1) if m else None


def item_id(href):
    return (href or "").rstrip("/").split("/")[-1]


def _split(links):
    """Separate good link dicts from error markers."""
    good = [lnk for lnk in links if "href" in lnk and "error" not in lnk]
    errors = [lnk["error"] for lnk in links if "error" in lnk]
    return good, errors


def list_packages(client, with_errors=False):
    """Union of BC and SDTM-specialization packages, newest first.

    Returns [{date, has_bc, has_spec}]; with ``with_errors`` returns
    (packages, [error messages]).
    """
    packages = {}
    errors = []
    for links, flag in ((client.get_bc_packages(), "has_bc"), (client.get_spec_packages(), "has_spec")):
        good, errs = _split(links)
        errors.extend(errs)
        for lnk in good:
            date = package_date(lnk["href"])
            if date:
                packages.setdefault(date, {"date": date, "has_bc": False, "has_spec": False})[flag] = True
    result = sorted(packages.values(), key=lambda p: p["date"], reverse=True)
    return (result, errors) if with_errors else result


def _items(links):
    good, errors = _split(links)
    items = sorted(({"id": item_id(lnk["href"]), "title": lnk.get("title", "")} for lnk in good), key=lambda i: i["title"].lower())
    return items, errors


def list_domains(client, with_errors=False):
    """SDTM domain names that have specializations, ascending (case-insensitive).

    With ``with_errors`` returns (names, [error messages]).
    """
    entries = client.get_sdtm_spec_domains()
    names = sorted({e["name"] for e in entries if e.get("name") and "error" not in e}, key=str.lower)
    errors = [e["error"] for e in entries if "error" in e]
    return (names, errors) if with_errors else names


def domain_specs(client, domain):
    """(items, errors) for the specializations of ``domain``; items are
    [{id, title}] sorted by title."""
    return _items(client.get_domain_specs(domain))


def latest_spec_package_date(client):
    """Effective date of the newest package that contains SDTM specializations, or None."""
    return next((p["date"] for p in list_packages(client) if p["has_spec"]), None)


_KIND_LABELS = {"bcs": "biomedical concept", "specs": "SDTM specialization"}


def _availability(client, date):
    """(has_bc, has_spec) for ``date`` from the package lists.

    If a package list itself failed to load we can't tell, so assume both
    exist and let the per-kind fetches report their own errors.
    """
    packages, errors = list_packages(client, with_errors=True)
    if errors:
        return True, True
    match = next((p for p in packages if p["date"] == date), None)
    return (match["has_bc"], match["has_spec"]) if match else (False, False)


def package_contents(client, date):
    """Contents of one package, fetching only the kinds it actually has.

    Returns {bcs, specs, errors, bcs_available, specs_available,
    bcs_failed, specs_failed}. A kind that doesn't exist for the date is
    "unavailable" (not an error); a kind whose fetch failed is "failed".
    """
    has_bc, has_spec = _availability(client, date)
    out = {"errors": []}
    for key, available, fetch in (("bcs", has_bc, client.get_package_bcs), ("specs", has_spec, client.get_package_specs)):
        items, errors = _items(fetch(date)) if available else ([], [])
        out[key] = items
        out[f"{key}_available"] = available
        out[f"{key}_failed"] = bool(errors)
        out["errors"].extend(errors)
    return out


def _compare_items(a_items, b_items):
    a_ids = {i["id"] for i in a_items}
    b_ids = {i["id"] for i in b_items}
    return {
        "removed": [i for i in a_items if i["id"] not in b_ids],
        "added": [i for i in b_items if i["id"] not in a_ids],
        "common": [i for i in b_items if i["id"] in a_ids],
        "skipped": None,
    }


def _skipped(message):
    return {"removed": [], "added": [], "common": [], "skipped": message}


def _compare_kind(key, a, b, date_a, date_b):
    """Compare one kind across two packages, or explain why we can't.

    Never diffs against a list that is missing or failed to load, since
    that would report every item as Added/Removed.
    """
    label = _KIND_LABELS[key]
    for date, side in ((date_a, a), (date_b, b)):
        if not side[f"{key}_available"]:
            return _skipped(f"Could not compare: there is no {label} package for {date}.")
        if side[f"{key}_failed"]:
            return _skipped(f"Could not compare: the {label} list for {date} failed to load (see the error above).")
    return _compare_items(a[key], b[key])


def compare_packages(client, date_a, date_b):
    """Compare package ``date_a`` (older/base) with ``date_b``.

    Returns {"bcs": {...}, "specs": {...}, "errors": [...]} where each of
    bcs/specs has added / removed / common item lists and a ``skipped``
    message (None when the comparison ran). Field-level changes for common
    items are computed lazily via ``diff_items``.
    """
    a = package_contents(client, date_a)
    b = package_contents(client, date_b)
    return {
        "bcs": _compare_kind("bcs", a, b, date_a, date_b),
        "specs": _compare_kind("specs", a, b, date_a, date_b),
        "errors": a["errors"] + b["errors"],
    }


def flatten(data, prefix=""):
    """Flatten a detail dict to [(dotted.field, display string)] rows.

    ``_links`` is dropped (hrefs embed the package date, so they always
    differ). Lists are rendered as JSON.
    """
    rows = []
    for key, value in data.items():
        if key == "_links":
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            rows.extend(flatten(value, f"{path}."))
        elif isinstance(value, list):
            rows.append((path, json.dumps(value, ensure_ascii=False)))
        else:
            rows.append((path, "" if value is None else str(value)))
    return rows


_LABEL_KEYS = ("shortName", "name", "title", "label")


def _display(value):
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def _detail_pairs(data, prefix=""):
    """[(dotted.key, text)] for a list entry's attributes: nested dicts are
    flattened to dotted keys and scalar lists comma-joined, so no raw JSON."""
    pairs = []
    for key, value in data.items():
        if key == "_links":
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            pairs.extend(_detail_pairs(value, f"{path}."))
        else:
            pairs.append((path, _display(value)))
    return pairs


def _list_item(entry):
    """One list entry as {label, details}. Dict entries (e.g. a data element
    concept) use their name as the label, suffixed with the conceptId, and
    list their remaining fields as details."""
    if not isinstance(entry, dict):
        return {"label": _display(entry), "details": []}
    label_key = next((k for k in _LABEL_KEYS if entry.get(k)), None)
    label = str(entry[label_key]) if label_key else str(entry.get("conceptId", ""))
    if label_key and entry.get("conceptId"):
        label = f'{label} ({entry["conceptId"]})'
    skip = {"_links", "conceptId", label_key}
    return {"label": label, "details": _detail_pairs({k: v for k, v in entry.items() if k not in skip})}


def detail_rows(data, prefix=""):
    """Rows for the item detail table: [{field, value, items}].

    ``items`` is None for scalar rows and a list of {label, details} for
    list-valued fields, so the template can render them as real lists.
    """
    rows = []
    for key, value in data.items():
        if key == "_links":
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            rows.extend(detail_rows(value, f"{path}."))
        elif isinstance(value, list):
            rows.append({"field": path, "value": "", "items": [_list_item(e) for e in value]})
        else:
            rows.append({"field": path, "value": "" if value is None else str(value), "items": None})
    return rows


_MISSING = object()
_SEP = " \u203a "


def _scalar(value):
    if value is _MISSING or value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _row(field, a, b):
    change = "Added" if a is _MISSING else "Removed" if b is _MISSING else "Changed"
    return {"field": field, "change": change, "a": _scalar(a), "b": _scalar(b)}


_KEY_FIELDS = ("conceptId", "name")


def _identity_key(items):
    """The field that uniquely identifies each dict in ``items`` (conceptId
    for concepts, name for specialization variables), or None."""
    if not items or not all(isinstance(e, dict) for e in items):
        return None
    for key in _KEY_FIELDS:
        values = [e.get(key) for e in items]
        if all(values) and len(set(values)) == len(values):
            return key
    return None


def _element_label(element, key):
    if key == "conceptId":
        name = next((str(element[k]) for k in _LABEL_KEYS if element.get(k)), "")
        return f'{name} ({element["conceptId"]})' if name else str(element["conceptId"])
    return str(element[key])


def _list_key(a, b):
    """Shared identity key when both lists (ignoring an empty side) have one."""
    keys = {_identity_key(side) for side in (a, b) if side}
    return keys.pop() if len(keys) == 1 and None not in keys else None


def _diff_list(path, a, b, rows):
    key = _list_key(a, b)
    if key:
        a_map = {e[key]: e for e in a}
        b_map = {e[key]: e for e in b}
        for ident in list(a_map) + [c for c in b_map if c not in a_map]:
            ea, eb = a_map.get(ident), b_map.get(ident)
            label = _element_label(ea or eb, key)
            if eb is None:
                rows.append({"field": f"{path}{_SEP}{label}", "change": "Removed", "a": label, "b": ""})
            elif ea is None:
                rows.append({"field": f"{path}{_SEP}{label}", "change": "Added", "a": "", "b": label})
            elif ea != eb:
                _diff_dicts(ea, eb, f"{path}{_SEP}{label}{_SEP}", rows)
    elif not any(isinstance(e, (dict, list)) for e in a + b):
        if not a or not b:  # whole list added/removed: one readable row
            rows.append({"field": path, "change": "Added" if b else "Removed", "a": ", ".join(map(_scalar, a)), "b": ", ".join(map(_scalar, b))})
            return
        for value in a:
            if value not in b:
                rows.append({"field": path, "change": "Removed", "a": _scalar(value), "b": ""})
        for value in b:
            if value not in a:
                rows.append({"field": path, "change": "Added", "a": "", "b": _scalar(value)})
    else:
        rows.append(_row(path, a, b))


def _diff_dicts(a, b, prefix, rows):
    for key in [k for k in a if k != "_links"] + [k for k in b if k not in a and k != "_links"]:
        va, vb = a.get(key, _MISSING), b.get(key, _MISSING)
        if va == vb:
            continue
        path = f"{prefix}{key}"
        if isinstance(va, dict) and isinstance(vb, dict):
            _diff_dicts(va, vb, f"{path}.", rows)
        elif isinstance(va, list) and isinstance(vb, list):
            _diff_list(path, va, vb, rows)
        elif isinstance(va, dict) and vb is _MISSING:
            _diff_dicts(va, {}, f"{path}.", rows)
        elif isinstance(vb, dict) and va is _MISSING:
            _diff_dicts({}, vb, f"{path}.", rows)
        elif isinstance(va, list) and vb is _MISSING:
            _diff_list(path, va, [], rows)
        elif isinstance(vb, list) and va is _MISSING:
            _diff_list(path, [], vb, rows)
        else:
            rows.append(_row(path, va, vb))


def diff_items(a, b):
    """Field-level differences between two detail dicts.

    Returns [{field, change, a, b}] where ``change`` is Added / Removed /
    Changed. Lists of scalars report each added/removed value; lists of
    concepts (e.g. dataElementConcepts) are matched by conceptId so each
    added, removed or changed element gets its own row(s). ``_links`` is
    ignored (its hrefs embed the package date).
    """
    rows = []
    _diff_dicts(a, b, "", rows)
    return rows
