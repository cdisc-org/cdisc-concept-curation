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
