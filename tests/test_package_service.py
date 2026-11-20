"""Tests for services/package_service.py — release package reports."""

from unittest.mock import MagicMock

from services import package_service as ps

BC_PKGS = [
    {"href": "/mdr/bc/packages/2023-02-13/biomedicalconcepts", "title": "BC Package 2023-02-13"},
    {"href": "/mdr/bc/packages/2024-05-01/biomedicalconcepts", "title": "BC Package 2024-05-01"},
]
SPEC_PKGS = [
    {"href": "/mdr/specializations/sdtm/packages/2023-02-13/datasetspecializations", "title": "Spec Package 2023-02-13"},
    {"href": "/mdr/specializations/sdtm/packages/2025-01-01/datasetspecializations", "title": "Spec Package 2025-01-01"},
]


def _client():
    c = MagicMock()
    c.get_bc_packages.return_value = BC_PKGS
    c.get_spec_packages.return_value = SPEC_PKGS
    return c


class TestHelpers:
    def test_package_date_extracts_date_from_href(self):
        assert ps.package_date("/mdr/bc/packages/2023-02-13/biomedicalconcepts") == "2023-02-13"

    def test_package_date_none_when_missing(self):
        assert ps.package_date("/mdr/bc/biomedicalconcepts") is None

    def test_item_id_is_last_path_segment(self):
        assert ps.item_id("/mdr/bc/packages/2023-02-13/biomedicalconcepts/C105585") == "C105585"

    def test_valid_date_and_id(self):
        assert ps.is_valid_date("2023-02-13")
        assert not ps.is_valid_date("../etc")
        assert ps.is_valid_item_id("C105585")
        assert ps.is_valid_item_id("AG_MEALTOLERANCE")
        assert ps.is_valid_item_id("A.B-1")
        assert not ps.is_valid_item_id("a/b")

    def test_dot_only_ids_are_rejected(self):
        for bad in (".", "..", "..."):
            assert not ps.is_valid_item_id(bad)


class TestListPackages:
    def test_union_sorted_descending_with_flags(self):
        pkgs = ps.list_packages(_client())
        assert [p["date"] for p in pkgs] == ["2025-01-01", "2024-05-01", "2023-02-13"]
        by_date = {p["date"]: p for p in pkgs}
        assert by_date["2023-02-13"]["has_bc"] and by_date["2023-02-13"]["has_spec"]
        assert by_date["2024-05-01"]["has_bc"] and not by_date["2024-05-01"]["has_spec"]
        assert by_date["2025-01-01"]["has_spec"] and not by_date["2025-01-01"]["has_bc"]

    def test_error_results_are_skipped(self):
        c = _client()
        c.get_bc_packages.return_value = [{"error": "boom"}]
        pkgs = ps.list_packages(c)
        assert [p["date"] for p in pkgs] == ["2025-01-01", "2023-02-13"]

    def test_reports_errors(self):
        c = _client()
        c.get_bc_packages.return_value = [{"error": "boom"}]
        assert ps.list_packages(c, with_errors=True)[1] == ["boom"]


class TestContents:
    def test_package_contents_sorted_by_title(self):
        c = _client()
        c.get_package_bcs.return_value = [
            {"href": "/mdr/bc/packages/D/biomedicalconcepts/C2", "title": "Zeta"},
            {"href": "/mdr/bc/packages/D/biomedicalconcepts/C1", "title": "alpha"},
        ]
        c.get_package_specs.return_value = [{"href": "/x/SPEC1", "title": "Spec One"}]
        out = ps.package_contents(c, "2023-02-13")
        assert out["bcs"] == [{"id": "C1", "title": "alpha"}, {"id": "C2", "title": "Zeta"}]
        assert out["specs"] == [{"id": "SPEC1", "title": "Spec One"}]
        assert out["errors"] == []

    def test_package_contents_collects_errors(self):
        c = _client()
        c.get_package_bcs.return_value = [{"error": "bc down"}]
        c.get_package_specs.return_value = []
        out = ps.package_contents(c, "2023-02-13")
        assert out["bcs"] == [] and out["errors"] == ["bc down"]


class TestAvailability:
    def test_contents_fetch_only_kinds_the_package_has(self):
        c = _client()  # 2024-05-01 is BC-only, 2025-01-01 is spec-only
        c.get_package_bcs.return_value = [{"href": "/p/C1", "title": "One"}]
        out = ps.package_contents(c, "2024-05-01")
        c.get_package_specs.assert_not_called()
        assert (out["bcs_available"], out["specs_available"]) == (True, False)
        assert out["errors"] == [] and out["bcs"] == [{"id": "C1", "title": "One"}] and out["specs"] == []

    def test_spec_only_package_does_not_fetch_bcs(self):
        c = _client()
        c.get_package_specs.return_value = []
        out = ps.package_contents(c, "2025-01-01")
        c.get_package_bcs.assert_not_called()
        assert (out["bcs_available"], out["specs_available"]) == (False, True)

    def test_unknown_date_has_nothing_available(self):
        out = ps.package_contents(_client(), "1999-01-01")
        assert (out["bcs_available"], out["specs_available"]) == (False, False)

    def test_package_list_failure_assumes_both_available(self):
        c = _client()
        c.get_bc_packages.return_value = [{"error": "boom"}]
        c.get_spec_packages.return_value = [{"error": "boom"}]
        c.get_package_bcs.return_value = []
        c.get_package_specs.return_value = []
        out = ps.package_contents(c, "2024-05-01")
        assert (out["bcs_available"], out["specs_available"]) == (True, True)

    def test_failed_fetch_is_flagged(self):
        c = _client()
        c.get_package_bcs.return_value = [{"error": "bc down"}]
        c.get_package_specs.return_value = [{"href": "/x/S1", "title": "S"}]
        out = ps.package_contents(c, "2023-02-13")
        assert out["bcs_failed"] and not out["specs_failed"]


def _cmp_client(bc_dates, spec_dates):
    c = MagicMock()
    c.get_bc_packages.return_value = [{"href": f"/mdr/bc/packages/{d}/biomedicalconcepts"} for d in bc_dates]
    c.get_spec_packages.return_value = [{"href": f"/mdr/specializations/sdtm/packages/{d}/datasetspecializations"} for d in spec_dates]
    c.get_package_bcs.side_effect = lambda d: {
        "2023-01-01": [{"href": "/p/C1", "title": "One"}, {"href": "/p/C2", "title": "Two"}],
        "2024-01-01": [{"href": "/p/C2", "title": "Two"}, {"href": "/p/C3", "title": "Three"}],
    }[d]
    c.get_package_specs.return_value = []
    return c


class TestCompare:
    def test_added_removed_common(self):
        out = ps.compare_packages(_cmp_client(["2023-01-01", "2024-01-01"], ["2023-01-01", "2024-01-01"]), "2023-01-01", "2024-01-01")
        assert out["bcs"]["removed"] == [{"id": "C1", "title": "One"}]
        assert out["bcs"]["added"] == [{"id": "C3", "title": "Three"}]
        assert out["bcs"]["common"] == [{"id": "C2", "title": "Two"}]
        assert out["bcs"]["skipped"] is None
        assert out["specs"] == {"added": [], "removed": [], "common": [], "skipped": None}

    def test_kind_missing_on_one_side_is_skipped_not_diffed_as_empty(self):
        c = _cmp_client(["2023-01-01", "2024-01-01"], ["2024-01-01"])
        c.get_package_specs.return_value = [{"href": "/p/S1", "title": "Spec"}]
        out = ps.compare_packages(c, "2023-01-01", "2024-01-01")
        assert out["specs"]["added"] == [] and out["specs"]["removed"] == []
        assert "2023-01-01" in out["specs"]["skipped"]
        assert out["bcs"]["skipped"] is None

    def test_failed_fetch_skips_that_kind_and_reports_error(self):
        c = _cmp_client(["2023-01-01", "2024-01-01"], ["2023-01-01", "2024-01-01"])
        c.get_package_bcs.side_effect = lambda d: [{"error": "timeout"}] if d == "2024-01-01" else [{"href": "/p/C1", "title": "One"}]
        out = ps.compare_packages(c, "2023-01-01", "2024-01-01")
        assert out["bcs"]["removed"] == [] and out["bcs"]["added"] == [] and out["bcs"]["skipped"]
        assert "timeout" in out["errors"]


class TestFlattenAndDiff:
    def test_flatten_nested(self):
        rows = ps.flatten({"a": 1, "b": {"c": "x"}, "_links": {"self": 1}, "l": [1, 2]})
        assert dict(rows) == {"a": "1", "b.c": "x", "l": "[1, 2]"}

    def test_diff_reports_changed_added_removed_fields(self):
        a = {"same": 1, "chg": "old", "gone": "x"}
        b = {"same": 1, "chg": "new", "new": "y"}
        diff = {d["field"]: d for d in ps.diff_items(a, b)}
        assert set(diff) == {"chg", "gone", "new"}
        assert diff["chg"]["a"] == "old" and diff["chg"]["b"] == "new"
        assert diff["gone"]["b"] == "" and diff["new"]["a"] == ""

    def test_diff_identical_is_empty(self):
        assert ps.diff_items({"a": 1}, {"a": 1}) == []


class TestDetailRows:
    def test_scalar_and_nested_dict_rows_have_no_items(self):
        rows = {r["field"]: r for r in ps.detail_rows({"shortName": "SN", "meta": {"k": "v"}, "_links": {}})}
        assert rows["shortName"] == {"field": "shortName", "value": "SN", "items": None}
        assert rows["meta.k"]["value"] == "v" and rows["meta.k"]["items"] is None

    def test_scalar_list_becomes_list_items(self):
        (row,) = ps.detail_rows({"synonyms": ["LIPASET", "Total Lipase"]})
        assert row["items"] == [{"label": "LIPASET", "details": []}, {"label": "Total Lipase", "details": []}]

    def test_data_element_concepts_become_list_with_details(self):
        dec = {"conceptId": "C25372", "href": "https://x/C25372", "shortName": "Category", "dataType": "string", "exampleSet": ["Chemistry", "Hematology"], "ncitCode": "C25372"}
        (row,) = ps.detail_rows({"dataElementConcepts": [dec]})
        (item,) = row["items"]
        assert item["label"] == "Category (C25372)"
        details = dict(item["details"])
        assert details["dataType"] == "string"
        assert details["exampleSet"] == "Chemistry, Hematology"
        assert "shortName" not in details and "conceptId" not in details

    def test_empty_list_is_empty_items(self):
        (row,) = ps.detail_rows({"synonyms": []})
        assert row["items"] == []


class TestDiffGranularity:
    def test_change_type_labels(self):
        diff = {d["field"]: d for d in ps.diff_items({"chg": "old", "gone": "x"}, {"chg": "new", "new": "y"})}
        assert diff["chg"]["change"] == "Changed"
        assert diff["gone"]["change"] == "Removed"
        assert diff["new"]["change"] == "Added"

    def test_nested_dict_changes_use_dotted_path(self):
        (d,) = ps.diff_items({"m": {"k": "1"}}, {"m": {"k": "2"}})
        assert d["field"] == "m.k" and (d["a"], d["b"]) == ("1", "2")

    def test_scalar_list_reports_added_and_removed_values(self):
        rows = ps.diff_items({"synonyms": ["A", "B"]}, {"synonyms": ["B", "C"]})
        assert [(r["field"], r["change"], r["a"], r["b"]) for r in rows] == [
            ("synonyms", "Removed", "A", ""),
            ("synonyms", "Added", "", "C"),
        ]

    def test_unchanged_scalar_list_has_no_rows(self):
        assert ps.diff_items({"synonyms": ["A", "B"]}, {"synonyms": ["B", "A"]}) == []

    def test_data_element_concepts_matched_by_concept_id(self):
        a = {"dataElementConcepts": [{"conceptId": "C1", "shortName": "Cat", "dataType": "string"}, {"conceptId": "C2", "shortName": "Gone"}]}
        b = {"dataElementConcepts": [{"conceptId": "C1", "shortName": "Cat", "dataType": "integer"}, {"conceptId": "C3", "shortName": "New"}]}
        rows = {r["field"]: r for r in ps.diff_items(a, b)}
        changed = rows["dataElementConcepts \u203a Cat (C1) \u203a dataType"]
        assert (changed["change"], changed["a"], changed["b"]) == ("Changed", "string", "integer")
        assert rows["dataElementConcepts \u203a Gone (C2)"]["change"] == "Removed"
        assert rows["dataElementConcepts \u203a New (C3)"]["change"] == "Added"
        assert len(rows) == 3

    def test_list_of_dicts_without_ids_falls_back_to_json(self):
        (r,) = ps.diff_items({"x": [{"a": 1}]}, {"x": [{"a": 2}]})
        assert r["field"] == "x" and '"a": 1' in r["a"] and '"a": 2' in r["b"]


SEP = " \u203a "


def _var(name, **kw):
    base = {"name": name, "role": "Topic", "codelist": {"conceptId": "C1", "submissionValue": "CL"}, "mandatoryValue": True}
    base.update(kw)
    return base


class TestSpecializationVariables:
    def test_variables_matched_by_name_with_nested_paths(self):
        a = {"variables": [_var("V1"), _var("V2")]}
        b = {"variables": [_var("V1", role="Qualifier", codelist={"conceptId": "C1", "submissionValue": "NEW"}), _var("V3")]}
        rows = {r["field"]: r for r in ps.diff_items(a, b)}
        assert rows[f"variables{SEP}V1{SEP}role"]["change"] == "Changed"
        assert rows[f"variables{SEP}V1{SEP}codelist.submissionValue"]["b"] == "NEW"
        assert rows[f"variables{SEP}V2"]["change"] == "Removed"
        assert rows[f"variables{SEP}V3"]["change"] == "Added"
        assert len(rows) == 4

    def test_duplicate_names_fall_back_to_json_row(self):
        (r,) = ps.diff_items({"variables": [_var("V1"), _var("V1")]}, {"variables": [_var("V1")]})
        assert r["field"] == "variables"

    def test_detail_rows_flatten_nested_dicts_in_list_items(self):
        (row,) = ps.detail_rows({"variables": [_var("DDTESTCD", relationship={"subject": "A", "object": "B"}, flags=["x", "y"])]})
        (item,) = row["items"]
        details = dict(item["details"])
        assert item["label"] == "DDTESTCD"
        assert details["codelist.submissionValue"] == "CL"
        assert details["relationship.subject"] == "A"
        assert details["flags"] == "x, y"
        assert not any(v.startswith("{") for v in details.values())


class TestWholeFieldAddedOrRemoved:
    def test_dict_field_only_in_one_side_expands_to_dotted_rows(self):
        rows = {r["field"]: r for r in ps.diff_items({"assignedTerm": {"value": "X", "conceptId": "C9"}}, {})}
        assert rows["assignedTerm.value"]["change"] == "Removed" and rows["assignedTerm.value"]["a"] == "X"
        assert rows["assignedTerm.conceptId"]["a"] == "C9"
        assert len(rows) == 2

    def test_scalar_list_only_in_one_side_is_one_comma_joined_row(self):
        (r,) = ps.diff_items({}, {"valueList": ["A", "B", "C"]})
        assert (r["field"], r["change"], r["a"], r["b"]) == ("valueList", "Added", "", "A, B, C")

    def test_scalar_list_emptied_is_one_removed_row(self):
        (r,) = ps.diff_items({"valueList": ["A", "B"]}, {"valueList": []})
        assert (r["change"], r["a"]) == ("Removed", "A, B")

    def test_no_raw_json_for_variable_gaining_nested_field(self):
        a = {"variables": [{"name": "V1", "role": "Topic"}]}
        b = {"variables": [{"name": "V1", "role": "Topic", "relationship": {"subject": "V1", "object": "V2"}}]}
        rows = {r["field"]: r for r in ps.diff_items(a, b)}
        assert rows[f"variables{SEP}V1{SEP}relationship.subject"]["change"] == "Added"
        assert not any(r["b"].startswith("{") for r in rows.values())


class TestDomains:
    def test_list_domains_sorted_ascending_case_insensitive(self):
        c = MagicMock()
        c.get_sdtm_spec_domains.return_value = [{"name": "VS"}, {"name": "ae"}, {"name": "LB"}]
        assert ps.list_domains(c) == ["ae", "LB", "VS"]

    def test_list_domains_with_errors(self):
        c = MagicMock()
        c.get_sdtm_spec_domains.return_value = [{"error": "down"}]
        assert ps.list_domains(c, with_errors=True) == ([], ["down"])

    def test_domain_specs_sorted_by_title(self):
        c = MagicMock()
        c.get_domain_specs.return_value = [
            {"href": "/mdr/specializations/sdtm/datasetspecializations/SYSBP", "title": "Systolic Blood Pressure"},
            {"href": "/mdr/specializations/sdtm/datasetspecializations/BMI", "title": "Body Mass Index"},
        ]
        items, errors = ps.domain_specs(c, "VS")
        assert items == [{"id": "BMI", "title": "Body Mass Index"}, {"id": "SYSBP", "title": "Systolic Blood Pressure"}]
        assert errors == []
        c.get_domain_specs.assert_called_once_with("VS")

    def test_domain_specs_errors(self):
        c = MagicMock()
        c.get_domain_specs.return_value = [{"error": "down"}]
        assert ps.domain_specs(c, "VS") == ([], ["down"])

    def test_latest_spec_package_date_picks_newest_with_specs(self):
        assert ps.latest_spec_package_date(_client()) == ("2025-01-01", [])

    def test_latest_spec_package_date_none_without_spec_packages(self):
        c = _client()
        c.get_spec_packages.return_value = []
        assert ps.latest_spec_package_date(c) == (None, [])

    def test_latest_spec_package_date_surfaces_list_errors(self):
        c = _client()
        c.get_spec_packages.return_value = [{"error": "boom"}]
        assert ps.latest_spec_package_date(c) == (None, ["boom"])


class TestCategories:
    def test_list_categories_sorted_case_insensitive_and_deduped(self):
        c = MagicMock()
        c.get_bc_categories.return_value = [{"name": "lipids"}, {"name": "Zeta"}, {"name": "Alpha"}, {"name": "Alpha"}]
        assert ps.list_categories(c) == ["Alpha", "lipids", "Zeta"]

    def test_list_categories_with_errors(self):
        c = MagicMock()
        c.get_bc_categories.return_value = [{"error": "boom"}]
        assert ps.list_categories(c, with_errors=True) == ([], ["boom"])

    def test_category_bcs_sorted_by_title_with_ids(self):
        c = MagicMock()
        c.get_category_bcs.return_value = [
            {"href": "/mdr/bc/biomedicalconcepts/C2", "title": "Zinc"},
            {"href": "/mdr/bc/biomedicalconcepts/C1", "title": "amylase"},
        ]
        items, errors = ps.category_bcs(c, "Lab")
        c.get_category_bcs.assert_called_once_with("Lab")
        assert items == [{"id": "C1", "title": "amylase"}, {"id": "C2", "title": "Zinc"}] and errors == []

    def test_category_bcs_surfaces_errors(self):
        c = MagicMock()
        c.get_category_bcs.return_value = [{"error": "boom"}]
        assert ps.category_bcs(c, "Lab") == ([], ["boom"])


# ── Lifecycle (#112) ──────────────────────────────────────────────────────

LC_DATES = ["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"]


def _lc_client(members, details, kind="bc", dates=None, current=None):
    """Fake client for lifecycle tests.

    Release packages are deltas: each lists only the items loaded in that
    release. ``members``: {date: [ids] | "error"}; ``details``:
    {(date, id): dict | "error"}. ``dates`` defaults to the releases named in
    ``members``; ``current`` (ids in the Library's current list, or "error")
    defaults to every id in any release.
    """
    dates = dates if dates is not None else (sorted(members) or LC_DATES)
    if current is None:
        current = sorted({i for m in members.values() if m != "error" for i in m})
    c = MagicMock()
    if current == "error":
        cur_links = [{"error": "current down"}]
    elif kind == "bc":
        cur_links = [{"href": f"/mdr/bc/biomedicalconcepts/{i}", "title": i} for i in current]
    else:
        cur_links = [{"href": f"/mdr/specializations/sdtm/datasetspecializations/{i}", "title": i} for i in current] + [
            {"href": "/mdr/specializations/cdash/datasetspecializations/CDASHONLY", "title": "x"}
        ]
    c.get_biomedical_concepts.return_value = cur_links if kind == "bc" else []
    c.get_dataset_specializations.return_value = cur_links if kind == "spec" else []
    root = "/mdr/bc/packages" if kind == "bc" else "/mdr/specializations/sdtm/packages"
    sub = "biomedicalconcepts" if kind == "bc" else "datasetspecializations"
    pkgs = [{"href": f"{root}/{d}/{sub}", "title": d} for d in dates]
    c.get_bc_packages.return_value = pkgs if kind == "bc" else []
    c.get_spec_packages.return_value = pkgs if kind == "spec" else []

    def _members(d):
        m = members.get(d, [])
        if m == "error":
            return [{"error": f"list {d} down"}]
        return [{"href": f"{root}/{d}/{sub}/{i}", "title": f"Title {i} {d}"} for i in m]

    def _detail(d, i):
        v = details.get((d, i), {"conceptId": i})
        return {"error": f"detail {d} down"} if v == "error" else v

    if kind == "bc":
        c.get_package_bcs.side_effect = _members
        c.get_package_bc.side_effect = _detail
    else:
        c.get_package_specs.side_effect = _members
        c.get_package_spec.side_effect = _detail
    return c


def _statuses(result):
    return [(e["date"], e["status"]) for e in result["events"]]


class TestLifecycle:
    def test_introduced_then_changed_then_unchanged(self):
        c = _lc_client(
            {"2022-01-01": [], "2023-01-01": ["C1"], "2024-01-01": ["C1"], "2025-01-01": ["C1"]},
            {
                ("2023-01-01", "C1"): {"conceptId": "C1", "definition": "old"},
                ("2024-01-01", "C1"): {"conceptId": "C1", "definition": "new"},
                ("2025-01-01", "C1"): {"conceptId": "C1", "definition": "new"},
            },
        )
        out = ps.lifecycle(c, "bc", "C1")
        assert _statuses(out) == [("2023-01-01", "Introduced"), ("2024-01-01", "Changed"), ("2025-01-01", "Unchanged")]
        assert out["found"] is True and out["errors"] == []

    def test_introduced_event_carries_full_metadata(self):
        c = _lc_client({"2023-01-01": ["C1"]}, {("2023-01-01", "C1"): {"conceptId": "C1", "shortName": "Glucose"}})
        first = ps.lifecycle(c, "bc", "C1")["events"][0]
        assert {"field": "shortName", "value": "Glucose", "items": None} in first["rows"]
        assert first["diffs"] == []

    def test_changed_event_carries_field_diffs_against_previous_version(self):
        c = _lc_client(
            {"2023-01-01": ["C1"], "2024-01-01": ["C1"]},
            {("2023-01-01", "C1"): {"conceptId": "C1", "definition": "old"}, ("2024-01-01", "C1"): {"conceptId": "C1", "definition": "new"}},
        )
        changed = ps.lifecycle(c, "bc", "C1")["events"][1]
        assert changed["diffs"] == [{"field": "definition", "change": "Changed", "a": "old", "b": "new"}]
        assert changed["previous"] == "2023-01-01"

    def test_links_are_ignored_when_diffing(self):
        c = _lc_client(
            {"2023-01-01": ["C1"], "2024-01-01": ["C1"]},
            {
                ("2023-01-01", "C1"): {"conceptId": "C1", "_links": {"self": {"href": "/2023"}}},
                ("2024-01-01", "C1"): {"conceptId": "C1", "_links": {"self": {"href": "/2024"}}},
            },
        )
        assert _statuses(ps.lifecycle(c, "bc", "C1"))[1] == ("2024-01-01", "Unchanged")

    def test_releases_that_did_not_load_the_item_are_skipped(self):
        """Packages are deltas: absence means "not loaded in that release",
        never a removal. A later load is diffed against the previous load."""
        c = _lc_client(
            {"2022-01-01": ["C1"], "2023-01-01": ["C9"], "2024-01-01": ["C9"], "2025-01-01": ["C1"]},
            {("2022-01-01", "C1"): {"conceptId": "C1", "definition": "a"}, ("2025-01-01", "C1"): {"conceptId": "C1", "definition": "b"}},
        )
        out = ps.lifecycle(c, "bc", "C1")
        assert _statuses(out) == [("2022-01-01", "Introduced"), ("2025-01-01", "Changed")]
        assert out["events"][1]["previous"] == "2022-01-01"
        assert out["events"][1]["diffs"] == [{"field": "definition", "change": "Changed", "a": "a", "b": "b"}]

    def test_not_in_latest_release_is_not_a_removal(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": ["C1"], "2024-01-01": ["C9"]}, {})
        assert _statuses(ps.lifecycle(c, "bc", "C1")) == [("2022-01-01", "Introduced"), ("2023-01-01", "Unchanged")]

    def test_withdrawn_when_missing_from_current_library_list(self):
        c = _lc_client({"2022-01-01": ["C1", "C9"]}, {}, current=["C9"])
        assert ps.lifecycle(c, "bc", "C1")["withdrawn"] is True
        assert ps.lifecycle(c, "bc", "C9")["withdrawn"] is False

    def test_withdrawn_unknown_when_current_list_fails(self):
        c = _lc_client({"2022-01-01": ["C1"]}, {}, current="error")
        out = ps.lifecycle(c, "bc", "C1")
        assert out["withdrawn"] is None and "current down" in out["errors"]

    def test_releases_before_introduction_are_not_shown(self):
        c = _lc_client({"2022-01-01": ["C9"], "2023-01-01": ["C9"], "2024-01-01": ["C1", "C9"]}, {})
        assert _statuses(ps.lifecycle(c, "bc", "C1")) == [("2024-01-01", "Introduced")]

    def test_failed_member_list_is_unavailable_not_removed(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": "error", "2024-01-01": ["C1"]}, {})
        out = ps.lifecycle(c, "bc", "C1")
        assert _statuses(out) == [("2022-01-01", "Introduced"), ("2023-01-01", "Unavailable"), ("2024-01-01", "Unchanged")]
        assert "list 2023-01-01 down" in out["errors"]

    def test_failed_detail_is_unavailable_and_baseline_is_kept(self):
        c = _lc_client(
            {"2022-01-01": ["C1"], "2023-01-01": ["C1"], "2024-01-01": ["C1"]},
            {
                ("2022-01-01", "C1"): {"conceptId": "C1", "definition": "a"},
                ("2023-01-01", "C1"): "error",
                ("2024-01-01", "C1"): {"conceptId": "C1", "definition": "b"},
            },
        )
        out = ps.lifecycle(c, "bc", "C1")
        assert _statuses(out) == [("2022-01-01", "Introduced"), ("2023-01-01", "Unavailable"), ("2024-01-01", "Changed")]
        assert out["events"][2]["previous"] == "2022-01-01"
        assert "detail 2023-01-01 down" in out["errors"]

    def test_failed_detail_on_first_appearance_still_introduces_later(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": ["C1"]}, {("2022-01-01", "C1"): "error"})
        assert _statuses(ps.lifecycle(c, "bc", "C1")) == [("2022-01-01", "Unavailable"), ("2023-01-01", "Introduced")]

    def test_unknown_item_is_not_found(self):
        c = _lc_client({"2022-01-01": ["C9"]}, {})
        out = ps.lifecycle(c, "bc", "NOPE")
        assert out["found"] is False and out["events"] == []

    def test_title_comes_from_latest_version(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": ["C1"]}, {})
        assert ps.lifecycle(c, "bc", "C1")["title"] == "Title C1 2023-01-01"

    def test_package_list_error_is_reported(self):
        c = _lc_client({}, {})
        c.get_bc_packages.return_value = [{"error": "pkgs down"}]
        out = ps.lifecycle(c, "bc", "C1")
        assert out["errors"] == ["pkgs down"] and out["events"] == []

    def test_spec_kind_uses_spec_endpoints(self):
        c = _lc_client({"2023-01-01": ["SYSBP"]}, {}, kind="spec")
        out = ps.lifecycle(c, "spec", "SYSBP")
        assert _statuses(out) == [("2023-01-01", "Introduced")]
        c.get_package_bcs.assert_not_called()

    def test_member_lists_fetched_once_per_release(self):
        c = _lc_client({d: ["C1"] for d in LC_DATES}, {})
        ps.lifecycle(c, "bc", "C1")
        assert c.get_package_bcs.call_count == len(LC_DATES)


class TestLifecycleItems:
    def test_union_of_all_releases_sorted_by_title_with_withdrawn_flag(self):
        c = _lc_client({"2022-01-01": ["C1", "C2"], "2023-01-01": ["C2", "C3"]}, {}, current=["C2", "C3"])
        items, errors = ps.lifecycle_items(c, "bc")
        assert errors == []
        assert [(i["id"], i["withdrawn"]) for i in items] == [("C1", True), ("C2", False), ("C3", False)]
        # Title comes from the newest release containing the item.
        assert {i["id"]: i["title"] for i in items}["C2"] == "Title C2 2023-01-01"

    def test_item_missing_from_latest_package_is_not_withdrawn(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": ["C2"]}, {})
        items, _ = ps.lifecycle_items(c, "bc")
        assert [(i["id"], i["withdrawn"]) for i in items] == [("C1", False), ("C2", False)]

    def test_withdrawn_flag_not_set_when_current_list_failed(self):
        c = _lc_client({"2022-01-01": ["C1"]}, {}, current="error")
        items, errors = ps.lifecycle_items(c, "bc")
        assert [(i["id"], i["withdrawn"]) for i in items] == [("C1", False)]
        assert errors == ["current down"]

    def test_failed_release_list_is_reported(self):
        c = _lc_client({"2022-01-01": ["C1"], "2023-01-01": "error"}, {})
        items, errors = ps.lifecycle_items(c, "bc")
        assert [i["id"] for i in items] == ["C1"] and errors == ["list 2023-01-01 down"]

    def test_spec_items_use_sdtm_current_list_only(self):
        c = _lc_client({"2023-01-01": ["SYSBP"]}, {}, kind="spec", current=["SYSBP"])
        items, _ = ps.lifecycle_items(c, "spec")
        assert [(i["id"], i["withdrawn"]) for i in items] == [("SYSBP", False)]
