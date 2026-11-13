"""Tests for routes/reports.py — Reports > Packages and Comparison."""

from unittest.mock import MagicMock, patch


def _client_mock():
    c = MagicMock()
    c.get_bc_packages.return_value = [{"href": "/mdr/bc/packages/2023-02-13/biomedicalconcepts", "title": "t"}, {"href": "/mdr/bc/packages/2024-05-01/biomedicalconcepts", "title": "t"}]
    c.get_spec_packages.return_value = [
        {"href": "/mdr/specializations/sdtm/packages/2023-02-13/datasetspecializations", "title": "t"},
        {"href": "/mdr/specializations/sdtm/packages/2024-05-01/datasetspecializations", "title": "t"},
    ]
    c.get_package_bcs.side_effect = lambda d: {
        "2023-02-13": [{"href": "/p/C1", "title": "One"}, {"href": "/p/C2", "title": "Two"}],
        "2024-05-01": [{"href": "/p/C2", "title": "Two"}, {"href": "/p/C3", "title": "Three"}],
    }[d]
    c.get_package_specs.return_value = [{"href": "/p/SPEC1", "title": "Spec One"}]
    c.get_package_bc.side_effect = lambda d, i: {"conceptId": i, "definition": f"def {d}", "shortName": "SN"}
    c.get_package_spec.return_value = {"datasetSpecializationId": "SPEC1", "domain": "VS"}
    c.get_sdtm_spec_domains.return_value = [{"name": "VS"}, {"name": "AE"}, {"name": "LB"}]
    c.get_domain_specs.side_effect = lambda d: {
        "VS": [
            {"href": "/mdr/specializations/sdtm/datasetspecializations/SYSBP", "title": "Systolic Blood Pressure"},
            {"href": "/mdr/specializations/sdtm/datasetspecializations/BMI", "title": "Body Mass Index"},
        ],
        "AE": [],
    }.get(d, [])
    c.get_bc_categories.return_value = [{"name": "Lipid Measurements"}, {"name": "laboratory Procedures"}, {"name": "Empty Cat"}]
    c.get_category_bcs.side_effect = lambda n: {
        "Lipid Measurements": [
            {"href": "/mdr/bc/biomedicalconcepts/C64812", "title": "Triglyceride Measurement"},
            {"href": "/mdr/bc/biomedicalconcepts/C105586", "title": "Cholesterol Measurement"},
        ],
    }.get(n, [])
    return c


def _patch():
    return patch("routes.reports.CDISCApiClient", return_value=_client_mock())


def test_sidebar_has_reports_menu(client):
    with _patch():
        html = client.get("/reports/packages").get_data(as_text=True)
    assert "Reports" in html and "/reports/packages" in html and "/reports/comparison" in html


def test_packages_list_descending(client):
    with _patch():
        html = client.get("/reports/packages").get_data(as_text=True)
    assert html.index("2024-05-01") < html.index("2023-02-13")
    assert "/reports/packages/2024-05-01" in html


def test_package_detail_lists_bcs_and_specs(client):
    with _patch():
        resp = client.get("/reports/packages/2023-02-13")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "One" in html and "Two" in html and "Spec One" in html
    assert "/reports/packages/2023-02-13/bc/C1" in html
    assert "/reports/packages/2023-02-13/spec/SPEC1" in html


def test_package_detail_rejects_bad_date(client):
    with _patch():
        assert client.get("/reports/packages/not-a-date").status_code == 404


def test_bc_detail_table(client):
    with _patch():
        html = client.get("/reports/packages/2023-02-13/bc/C1").get_data(as_text=True)
    assert "<table" in html and "definition" in html and "def 2023-02-13" in html


def test_bc_detail_renders_data_element_concepts_as_list(client):
    c = _client_mock()
    c.get_package_bc.side_effect = None
    c.get_package_bc.return_value = {
        "conceptId": "C1",
        "synonyms": ["Syn A"],
        "dataElementConcepts": [{"conceptId": "C25372", "shortName": "Category", "dataType": "string", "exampleSet": ["Chemistry"]}],
    }
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/packages/2023-02-13/bc/C1").get_data(as_text=True)
    assert "<ul" in html and "<li" in html
    assert "Category (C25372)" in html and "Chemistry" in html and "Syn A" in html
    assert "{&#34;conceptId&#34;" not in html and '{"conceptId"' not in html


def test_bc_detail_error_redirects(client):
    c = _client_mock()
    c.get_package_bc.side_effect = None
    c.get_package_bc.return_value = {"error": "nope"}
    with patch("routes.reports.CDISCApiClient", return_value=c):
        resp = client.get("/reports/packages/2023-02-13/bc/C1")
    assert resp.status_code == 302


def test_spec_detail_table(client):
    with _patch():
        html = client.get("/reports/packages/2023-02-13/spec/SPEC1").get_data(as_text=True)
    assert "<table" in html and "domain" in html and "VS" in html


def test_comparison_form_has_dropdowns_and_compare_button(client):
    with _patch():
        html = client.get("/reports/comparison").get_data(as_text=True)
    assert 'name="a"' in html and 'name="b"' in html and "Compare" in html
    assert "Removed" not in html


def test_comparison_results(client):
    with _patch():
        html = client.get("/reports/comparison?a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "Added" in html and "Removed" in html
    assert "Three" in html and "One" in html
    assert "/reports/comparison/diff" in html


def test_comparison_same_package_warns(client):
    with _patch():
        html = client.get("/reports/comparison?a=2023-02-13&b=2023-02-13").get_data(as_text=True)
    assert "different" in html.lower()


def test_comparison_invalid_date_is_rejected(client):
    with _patch():
        resp = client.get("/reports/comparison?a=../x&b=2024-05-01")
    assert resp.status_code == 400


def test_diff_fragment_shows_changed_fields(client):
    with _patch():
        html = client.get("/reports/comparison/diff?kind=bc&id=C2&a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "definition" in html and "def 2023-02-13" in html and "def 2024-05-01" in html


def test_diff_fragment_no_changes(client):
    c = _client_mock()
    c.get_package_bc.side_effect = lambda d, i: {"conceptId": i}
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/comparison/diff?kind=bc&id=C2&a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "No field differences" in html


def test_diff_bad_kind(client):
    with _patch():
        assert client.get("/reports/comparison/diff?kind=zzz&id=C2&a=2023-02-13&b=2024-05-01").status_code == 400


def _breadcrumb(html):
    start = html.index('aria-label="breadcrumb"')
    return html[start : html.index("</nav>", start)]


def test_packages_breadcrumb(client):
    with _patch():
        crumb = _breadcrumb(client.get("/reports/packages").get_data(as_text=True))
    assert "Reports" in crumb
    assert 'aria-current="page"' in crumb and "Packages" in crumb
    assert crumb.count("<a ") == 1  # Reports links back; Packages is the current page


def test_package_detail_breadcrumb(client):
    with _patch():
        crumb = _breadcrumb(client.get("/reports/packages/2023-02-13").get_data(as_text=True))
    assert 'href="/reports/packages"' in crumb
    assert crumb.index("Reports") < crumb.index("Packages") < crumb.index("2023-02-13")
    assert 'aria-current="page">2023-02-13' in crumb.replace("\n", "").replace("  ", "")


def test_item_breadcrumb_links_back_through_every_level(client):
    with _patch():
        for kind, item in (("bc", "C1"), ("spec", "SPEC1")):
            crumb = _breadcrumb(client.get(f"/reports/packages/2023-02-13/{kind}/{item}").get_data(as_text=True))
            assert crumb.count("<a ") == 3
            assert 'href="/reports/packages"' in crumb
            assert 'href="/reports/packages/2023-02-13"' in crumb
            assert crumb.index("Reports") < crumb.index("Packages") < crumb.index("2023-02-13") < crumb.index(item)
            assert f'aria-current="page">{item}' in crumb.replace("\n", "").replace("  ", "")


def test_diff_fragment_is_a_table_with_change_column_and_per_item_rows(client):
    c = _client_mock()
    c.get_package_bc.side_effect = lambda d, i: {
        "2023-02-13": {"conceptId": i, "dataElementConcepts": [{"conceptId": "C9", "shortName": "Cat", "dataType": "string"}]},
        "2024-05-01": {"conceptId": i, "dataElementConcepts": [{"conceptId": "C9", "shortName": "Cat", "dataType": "integer"}]},
    }[d]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/comparison/diff?kind=bc&id=C2&a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "<table" in html and "<th" in html
    for header in ("Field", "Change", "2023-02-13", "2024-05-01"):
        assert header in html
    assert "Changed" in html and "dataType" in html and "integer" in html
    assert '{"conceptId"' not in html and "{&#34;conceptId&#34;" not in html


SPEC_A = {"datasetSpecializationId": "S1", "domain": "DD", "variables": [{"name": "DDTESTCD", "role": "Topic", "codelist": {"conceptId": "C1", "submissionValue": "OLD"}}]}
SPEC_B = {"datasetSpecializationId": "S1", "domain": "DD", "variables": [{"name": "DDTESTCD", "role": "Topic", "codelist": {"conceptId": "C1", "submissionValue": "NEW"}}]}


def test_spec_diff_fragment_is_same_table_format(client):
    c = _client_mock()
    c.get_package_spec.side_effect = lambda d, i: {"2023-02-13": SPEC_A, "2024-05-01": SPEC_B}[d]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/comparison/diff?kind=spec&id=S1&a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "<table" in html
    for header in ("Field", "Change", "2023-02-13", "2024-05-01"):
        assert header in html
    assert "DDTESTCD" in html and "codelist.submissionValue" in html and "OLD" in html and "NEW" in html
    assert '{"name"' not in html and "{&#34;name&#34;" not in html


def test_spec_item_page_shows_variables_as_nested_list(client):
    c = _client_mock()
    c.get_package_spec.side_effect = None
    c.get_package_spec.return_value = SPEC_A
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/packages/2023-02-13/spec/S1").get_data(as_text=True)
    assert "<ul" in html and "DDTESTCD" in html and "codelist.submissionValue" in html and "OLD" in html
    assert "{&#34;conceptId&#34;" not in html


def test_comparison_page_spec_rows_have_expand_buttons(client):
    with _patch():
        html = client.get("/reports/comparison?a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "kind=spec" in html and "diff-toggle" in html


def test_comparison_shows_fetch_errors_and_does_not_diff_failed_side(client):
    c = _client_mock()
    c.get_package_bcs.side_effect = lambda d: [{"error": "timeout talking to Library"}] if d == "2024-05-01" else [{"href": "/p/C1", "title": "One"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/comparison?a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "timeout talking to Library" in html
    assert "Removed since" not in html.split("SDTM Dataset Specializations")[0]  # BC section not diffed against an empty list
    assert "Could not compare" in html


def test_comparison_explains_kind_missing_from_one_package(client):
    c = _client_mock()
    c.get_spec_packages.return_value = [{"href": "/mdr/specializations/sdtm/packages/2024-05-01/datasetspecializations", "title": "t"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/comparison?a=2023-02-13&b=2024-05-01").get_data(as_text=True)
    assert "no sdtm specialization package for 2023-02-13" in html.lower()
    assert "2023-02-13" not in [call.args[0] for call in c.get_package_specs.call_args_list]  # never requests the missing package


def test_bc_only_package_page_has_no_error_banner(client):
    c = _client_mock()
    c.get_spec_packages.return_value = []
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/packages/2023-02-13").get_data(as_text=True)
    c.get_package_specs.assert_not_called()
    assert "CDISC Library error" not in html
    assert "no sdtm" in html.lower()


def test_unknown_package_date_is_404(client):
    with _patch():
        assert client.get("/reports/packages/1999-01-01").status_code == 404


def test_dot_segment_ids_are_rejected(client):
    with _patch():
        assert client.get("/reports/comparison/diff?kind=bc&id=..&a=2023-02-13&b=2024-05-01").status_code == 400
        assert client.get("/reports/packages/2023-02-13/bc/..").status_code == 404


# ── SDTM Domains (#106) ────────────────────────────────────────────────


def test_sidebar_has_sdtm_domains_item(client):
    with _patch():
        html = client.get("/reports/packages").get_data(as_text=True)
    assert "SDTM Domains" in html and 'href="/reports/domains"' in html


def test_domains_list_ascending_and_linked(client):
    with _patch():
        html = client.get("/reports/domains").get_data(as_text=True)
    assert html.index(">AE<") < html.index(">LB<") < html.index(">VS<")
    assert 'href="/reports/domains/VS"' in html


def test_domains_nav_item_is_active(client):
    with _patch():
        html = client.get("/reports/domains/VS").get_data(as_text=True)
    nav = html[html.index('href="/reports/domains"') :]
    assert "active" in nav[: nav.index("</a>")]


def test_domains_api_error_shows_banner_not_500(client):
    c = _client_mock()
    c.get_sdtm_spec_domains.return_value = [{"error": "boom"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        resp = client.get("/reports/domains")
    assert resp.status_code == 200 and "boom" in resp.get_data(as_text=True)


def test_domain_specs_listed_by_title_with_latest_package_links(client):
    with _patch():
        html = client.get("/reports/domains/VS").get_data(as_text=True)
    assert html.index("Body Mass Index") < html.index("Systolic Blood Pressure")
    # latest spec package in the mock is 2024-05-01
    assert 'href="/reports/packages/2024-05-01/spec/SYSBP"' in html


def test_domain_with_no_specs_shows_empty_state(client):
    with _patch():
        resp = client.get("/reports/domains/AE")
    assert resp.status_code == 200 and "No specializations" in resp.get_data(as_text=True)


def test_unknown_domain_is_404(client):
    with _patch():
        assert client.get("/reports/domains/ZZ").status_code == 404


def test_domain_specs_without_spec_package_are_plain_text_with_notice(client):
    c = _client_mock()
    c.get_spec_packages.return_value = []
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/domains/VS").get_data(as_text=True)
    assert "Systolic Blood Pressure" in html and "/spec/SYSBP" not in html
    assert "No SDTM specialization package" in html


def test_domain_specs_package_list_error_is_shown_not_reported_as_missing(client):
    c = _client_mock()
    c.get_spec_packages.return_value = [{"error": "boom"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/domains/VS").get_data(as_text=True)
    assert "CDISC Library error: boom" in html
    assert "No SDTM specialization package" not in html
    assert "Systolic Blood Pressure" in html and "/spec/SYSBP" not in html


def test_domain_specs_breadcrumb(client):
    with _patch():
        crumb = _breadcrumb(client.get("/reports/domains/VS").get_data(as_text=True))
    assert 'href="/reports/domains"' in crumb
    assert crumb.index("Reports") < crumb.index("SDTM Domains") < crumb.index("VS")


# ── BC Categories (#3) ──────────────────────────────────────────────────


def test_sidebar_has_bc_categories_item(client):
    with _patch():
        html = client.get("/reports/packages").get_data(as_text=True)
    assert "BC Categories" in html and 'href="/reports/categories"' in html


def test_categories_list_alphabetical_and_linked(client):
    with _patch():
        html = client.get("/reports/categories").get_data(as_text=True)
    # case-insensitive ascending: "Empty Cat" < "laboratory Procedures" < "Lipid Measurements"
    assert html.index(">Empty Cat<") < html.index(">laboratory Procedures<") < html.index(">Lipid Measurements<")
    assert 'href="/reports/categories/Lipid%20Measurements"' in html


def test_categories_nav_item_is_active(client):
    with _patch():
        html = client.get("/reports/categories/Lipid%20Measurements").get_data(as_text=True)
    nav = html[html.index('href="/reports/categories"') :]
    assert "active" in nav[: nav.index("</a>")]


def test_categories_api_error_shows_banner_not_500(client):
    c = _client_mock()
    c.get_bc_categories.return_value = [{"error": "boom"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        resp = client.get("/reports/categories")
    assert resp.status_code == 200 and "boom" in resp.get_data(as_text=True)


def test_category_bcs_sorted_and_link_to_library_detail(client):
    with _patch():
        html = client.get("/reports/categories/Lipid%20Measurements").get_data(as_text=True)
    assert html.index("Cholesterol Measurement") < html.index("Triglyceride Measurement")
    assert 'href="/bc/library/C64812"' in html and 'href="/bc/library/C105586"' in html


def test_category_with_no_bcs_shows_empty_state(client):
    with _patch():
        resp = client.get("/reports/categories/Empty%20Cat")
    assert resp.status_code == 200 and "No biomedical concepts" in resp.get_data(as_text=True)


def test_unknown_category_is_404(client):
    with _patch():
        assert client.get("/reports/categories/Nope").status_code == 404


def test_category_detail_with_failed_category_list_redirects_with_error(client):
    c = _client_mock()
    c.get_bc_categories.return_value = [{"error": "boom"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        resp = client.get("/reports/categories/Lipid%20Measurements")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/reports/categories")


def test_category_bcs_api_error_is_shown(client):
    c = _client_mock()
    c.get_category_bcs.side_effect = lambda n: [{"error": "bcboom"}]
    with patch("routes.reports.CDISCApiClient", return_value=c):
        html = client.get("/reports/categories/Lipid%20Measurements").get_data(as_text=True)
    assert "bcboom" in html


def test_category_breadcrumb(client):
    with _patch():
        crumb = _breadcrumb(client.get("/reports/categories/Lipid%20Measurements").get_data(as_text=True))
    assert 'href="/reports/categories"' in crumb
    assert crumb.index("Reports") < crumb.index("BC Categories") < crumb.index("Lipid Measurements")
