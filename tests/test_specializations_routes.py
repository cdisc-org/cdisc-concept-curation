"""Tests for routes/specializations.py."""

from unittest.mock import MagicMock, patch

from extensions import db
from models.audit import AuditLog
from models.bc import BiomedicalConcept
from models.specialization import DatasetSpecialization

LIBRARY_LINKS = [
    {"href": "/mdr/bc/biomedicalconcepts/C64849", "title": "Hemoglobin A1c"},
]

DOMAIN_CODES = [
    {"code": "AE", "label": "Adverse Event Domain"},
    {"code": "LB", "label": "Laboratory Test Results Domain"},
    {"code": "VS", "label": "Vital Signs Domain"},
]


def _patch_client(**kwargs):
    """Patch the CDISCApiClient used by the specializations blueprint."""
    client = MagicMock()
    client.get_biomedical_concepts.return_value = kwargs.get("bcs", LIBRARY_LINKS)
    client.get_specialization.return_value = kwargs.get("spec", {})
    client.get_sdtm_domain_codes.return_value = kwargs.get("domains", DOMAIN_CODES)
    patcher = patch("routes.specializations.CDISCApiClient", return_value=client)
    return patcher, client


class TestIndex:
    def test_lists_specializations(self, client, app, sample_bc):
        with app.app_context():
            spec = DatasetSpecialization(vlm_group_id="C12345.SDTM", bc_id=sample_bc, domain="SDTM", short_name="Test Spec")
            db.session.add(spec)
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200
        assert b"C12345.SDTM" in resp.data

    def test_index_survives_library_error(self, client):
        patcher, _ = _patch_client(bcs=[{"error": "401"}])
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200


class TestCloneSpecialization:
    def test_expands_panel_prefilled_but_leaves_id_blank(self, client, app, sample_bc):
        with app.app_context():
            spec = DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Source Spec")
            spec.variables = [{"sdtm_variable": "RESULT", "data_type": "decimal"}]
            db.session.add(spec)
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/?clone_from=VLM1")
        body = resp.data.decode()
        assert resp.status_code == 200
        assert 'class="collapse mb-3 show"' in body
        assert "Source Spec" in body
        assert "RESULT" in body
        vlm_input = body.split('id="vlm_group_id"')[1].split(">")[0]
        assert 'value=""' in vlm_input

    def test_unknown_source_flashes_but_index_still_renders(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/?clone_from=NOPE", follow_redirects=True)
        assert resp.status_code == 200
        assert b"NOPE" in resp.data

    def test_does_not_lock_form_even_if_source_is_published(self, client, app, sample_bc):
        with app.app_context():
            spec = DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Source Spec", status="published")
            db.session.add(spec)
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/?clone_from=VLM1")
        body = resp.data.decode()
        fieldset_tag = body.split("<fieldset")[1].split(">")[0]
        assert "disabled" not in fieldset_tag


class TestCreate:
    def test_create_persists_spec(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "CDASH", "short_name": "Manual Spec"},
            )
        assert resp.status_code == 302
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM1")
            assert spec is not None
            assert spec.domain == "CDASH"
            assert spec.variables == []

    def test_create_defaults_to_provisional_status(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM2", "bc_id": sample_bc, "domain": "CDASH", "short_name": "Manual Spec"},
            )
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM2")
            assert spec.status == "provisional"

    def test_create_requires_ids(self, client, app):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post("/specializations/", data={"vlm_group_id": "", "bc_id": ""})
        assert resp.status_code == 302
        with app.app_context():
            assert DatasetSpecialization.query.count() == 0

    def test_create_requires_domain(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": ""},
            )
        assert resp.status_code == 302
        with app.app_context():
            assert DatasetSpecialization.query.count() == 0

    def test_real_sdtm_domain_code_persists(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "VS", "short_name": "Vitals Spec"},
            )
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM1")
            assert spec.domain == "VS"

    def test_create_writes_audit_log(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "SDTM", "short_name": "Manual Spec"},
            )
        with app.app_context():
            log = AuditLog.query.filter_by(entity_type="DatasetSpecialization", entity_id="VLM1", action="created").first()
            assert log is not None
            assert log.after_state["short_name"] == "Manual Spec"

    def test_create_persists_variable_rows_from_form(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={
                    "vlm_group_id": "VLM1",
                    "bc_id": sample_bc,
                    "domain": "SDTM",
                    "short_name": "Manual Spec",
                    "variables[0][sdtm_variable]": "RESULT",
                    "variables[0][data_type]": "decimal",
                    "variables[0][mandatory_variable]": "Y",
                },
            )
        assert resp.status_code == 302
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM1")
            assert len(spec.variables) == 1
            assert spec.variables[0]["sdtm_variable"] == "RESULT"
            assert spec.variables[0]["data_type"] == "decimal"
            assert spec.variables[0]["mandatory_variable"] == "Y"


class TestEditUpsert:
    def test_posting_existing_vlm_group_id_updates_instead_of_duplicating(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Original"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={
                    "vlm_group_id": "VLM1",
                    "bc_id": sample_bc,
                    "domain": "CDASH",
                    "short_name": "Renamed",
                    "variables[0][sdtm_variable]": "RESULT",
                    "variables[0][data_type]": "decimal",
                },
            )
        assert resp.status_code == 302
        with app.app_context():
            assert DatasetSpecialization.query.count() == 1
            spec = db.session.get(DatasetSpecialization, "VLM1")
            assert spec.domain == "CDASH"
            assert spec.short_name == "Renamed"
            assert len(spec.variables) == 1
            assert spec.variables[0]["sdtm_variable"] == "RESULT"
            assert spec.variables[0]["data_type"] == "decimal"

    def test_update_blocked_when_published(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Original", status="published"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "CDASH", "short_name": "Renamed"},
                follow_redirects=True,
            )
        assert resp.status_code == 200
        assert b"Ready to Publish" in resp.data
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM1")
            assert spec.domain == "SDTM"
            assert spec.short_name == "Original"

    def test_new_vlm_group_id_still_creatable_when_other_specs_published(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Original", status="published"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM2", "bc_id": sample_bc, "domain": "CDASH", "short_name": "Brand New"},
            )
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(DatasetSpecialization, "VLM2") is not None

    def test_edit_writes_updated_audit_log(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Original"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "SDTM", "short_name": "Renamed"},
            )
        with app.app_context():
            log = AuditLog.query.filter_by(entity_type="DatasetSpecialization", entity_id="VLM1", action="updated").first()
            assert log is not None
            assert log.before_state["short_name"] == "Original"
            assert log.after_state["short_name"] == "Renamed"


class TestDelete:
    def test_delete_removes_spec(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post("/specializations/VLM1/delete")
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(DatasetSpecialization, "VLM1") is None

    def test_delete_writes_audit_log(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", short_name="Doomed Spec"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            client.post("/specializations/VLM1/delete")
        with app.app_context():
            log = AuditLog.query.filter_by(entity_type="DatasetSpecialization", entity_id="VLM1", action="deleted").first()
            assert log is not None
            assert log.before_state["short_name"] == "Doomed Spec"

    def test_delete_unknown_404(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post("/specializations/NOPE/delete")
        assert resp.status_code == 404

    def test_delete_blocked_when_published(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM", status="published"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post("/specializations/VLM1/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Ready to Publish" in resp.data
        with app.app_context():
            assert db.session.get(DatasetSpecialization, "VLM1") is not None


class TestDetail:
    def test_detail_renders(self, client, app, sample_bc):
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/VLM1")
        assert resp.status_code == 200

    def test_detail_404_for_unknown(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/NOPE")
        assert resp.status_code == 404

    def test_detail_expands_the_edit_form_panel(self, client, app, sample_bc):
        """The Edit link on the list page routes here; the pre-filled form
        must actually be visible, not left inside a collapsed <div>."""
        with app.app_context():
            db.session.add(DatasetSpecialization(vlm_group_id="VLM1", bc_id=sample_bc, domain="SDTM"))
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/VLM1")
        body = resp.data.decode()
        assert 'id="specialization-form-panel"' in body
        assert 'class="collapse mb-3 show"' in body

    def test_index_form_panel_collapsed_by_default(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/")
        body = resp.data.decode()
        assert 'class="collapse mb-3 "' in body


class TestLibraryDetail:
    def test_renders_library_spec(self, client):
        patcher, _ = _patch_client(spec={"shortName": "HBA1C Spec", "datasetSpecializationId": "HBA1C"})
        with patcher:
            resp = client.get("/specializations/library/mdr/specializations/sdtm/datasetspecializations/HBA1C")
        assert resp.status_code == 200

    def test_error_redirects_to_dashboard(self, client):
        patcher, _ = _patch_client(spec={"error": "404 not found"})
        with patcher:
            resp = client.get("/specializations/library/mdr/specializations/sdtm/datasetspecializations/NOPE")
        assert resp.status_code == 302
        assert resp.headers["Location"] in ("/", "http://localhost/")


class TestGenerateFromDecRemoved:
    """Issue #99: DEC templates never yield correct specializations, so the feature was removed."""

    def test_index_has_no_generate_button(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "generate-from-dec-btn" not in html
        assert "Generate from DEC Templates" not in html

    def test_generate_from_dec_endpoint_removed(self, client):
        resp = client.post("/specializations/generate-from-dec", json={"bc_id": "X"})
        assert resp.status_code in (404, 405)

    def test_generate_endpoint_removed(self, client, sample_bc):
        resp = client.post(f"/specializations/generate/{sample_bc}", data={"domain": "SDTM"})
        assert resp.status_code in (404, 405)


class TestCreateWithLibraryOnlyBc:
    def test_selecting_library_only_bc_creates_local_stub(self, client, app):
        """Picking a 'CDISC Library' option that has no local BC row yet
        must not create an orphaned FK reference — it should create a
        minimal local BC stub so the specialization links correctly."""
        patcher, _ = _patch_client(bcs=[{"href": "/mdr/bc/biomedicalconcepts/C64849", "title": "Hemoglobin A1c"}])
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "C64849.SDTM", "bc_id": "C64849", "domain": "SDTM", "short_name": "HBA1C Spec"},
            )
        assert resp.status_code == 302
        with app.app_context():
            bc = db.session.get(BiomedicalConcept, "C64849")
            assert bc is not None
            assert bc.status == "provisional"
            spec = db.session.get(DatasetSpecialization, "C64849.SDTM")
            assert spec is not None
            assert spec.bc_id == "C64849"
            assert spec.bc is not None
            assert spec.bc.bc_id == "C64849"

    def test_existing_local_bc_is_not_modified(self, client, app, sample_bc):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.post(
                "/specializations/",
                data={"vlm_group_id": "VLM1", "bc_id": sample_bc, "domain": "SDTM", "short_name": "Manual Spec"},
            )
        assert resp.status_code == 302
        with app.app_context():
            bc = db.session.get(BiomedicalConcept, sample_bc)
            assert bc.short_name == "Test Concept"


class TestBcOptionsSorting:
    def test_library_bcs_sorted_alphabetically(self, client):
        unsorted_links = [
            {"href": "/mdr/bc/biomedicalconcepts/C2", "title": "Zebra Concept"},
            {"href": "/mdr/bc/biomedicalconcepts/C1", "title": "Alpha Concept"},
        ]
        patcher, _ = _patch_client(bcs=unsorted_links)
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert body.index("Alpha Concept") < body.index("Zebra Concept")


class TestDomainSelector:
    def test_domain_options_rendered_from_sdtm_codelist(self, client):
        patcher, _ = _patch_client()
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Adverse Event Domain" in body
        assert "Vital Signs Domain" in body

    def test_error_entries_excluded_from_options(self, client):
        patcher, _ = _patch_client(domains=[{"error": "unreachable"}])
        with patcher:
            resp = client.get("/specializations/")
        assert resp.status_code == 200


def _spec_with_vars(app, bc_id, vlm_group_id="VLM1"):
    with app.app_context():
        spec = DatasetSpecialization(vlm_group_id=vlm_group_id, bc_id=bc_id, domain="LB", short_name="Ketones LB")
        spec.variables = [
            {"sdtm_variable": "LBTESTCD", "codelist": "LBTESTCD", "data_type": "text"},
            {"sdtm_variable": "LBORRES", "value_list": "POSITIVE; NEGATIVE"},
        ]
        db.session.add(spec)
        db.session.commit()


class TestExport:
    def test_xlsx_export_has_sdtm_sheet_with_variables(self, client, app, sample_bc):
        import io

        import openpyxl

        _spec_with_vars(app, sample_bc)
        resp = client.get("/specializations/VLM1/export?format=xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.mimetype
        assert "attachment" in resp.headers["Content-Disposition"]
        assert "VLM1" in resp.headers["Content-Disposition"]
        wb = openpyxl.load_workbook(io.BytesIO(resp.data))
        assert "SDTM_LB" in wb.sheetnames
        ws = wb["SDTM_LB"]
        assert ws.max_row == 3
        headers = [c.value for c in ws[1]]
        assert ws.cell(row=2, column=headers.index("vlm_group_id") + 1).value == "VLM1"
        assert ws.cell(row=3, column=headers.index("sdtm_variable") + 1).value == "LBORRES"

    def test_xlsx_is_default_format(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        resp = client.get("/specializations/VLM1/export")
        assert "spreadsheetml" in resp.mimetype

    def test_csv_export(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        resp = client.get("/specializations/VLM1/export?format=csv")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert ".csv" in resp.headers["Content-Disposition"]
        lines = resp.data.decode().strip().splitlines()
        assert len(lines) == 3
        assert "LBTESTCD" in lines[1]

    def test_csv_filename_is_safely_encoded_for_quotes_and_non_latin1(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc, vlm_group_id='A"B\u2014C')
        from urllib.parse import quote

        resp = client.get("/specializations/" + quote('A"B\u2014C') + "/export?format=csv")
        assert resp.status_code == 200
        disposition = resp.headers["Content-Disposition"]
        assert 'A"B' not in disposition  # a raw quote would end the quoted filename early
        assert "filename*=UTF-8''" in disposition  # RFC 5987 form for the non-Latin-1 dash
        disposition.encode("latin-1")  # WSGI header values must be latin-1 encodable

    def test_unknown_format_is_400(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        assert client.get("/specializations/VLM1/export?format=pdf").status_code == 400

    def test_export_404_for_unknown_spec(self, client):
        assert client.get("/specializations/NOPE/export?format=csv").status_code == 404

    def test_export_unaffected_by_published_status(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        with app.app_context():
            db.session.get(DatasetSpecialization, "VLM1").status = "published"
            db.session.commit()
        assert client.get("/specializations/VLM1/export?format=csv").status_code == 200


class TestPrintView:
    def test_print_view_shows_every_field_label_and_value(self, client, app, sample_bc):
        from services.ingestion import VARIABLE_FIELD_DEFS

        _spec_with_vars(app, sample_bc)
        resp = client.get("/specializations/VLM1/print")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Ketones LB" in body
        assert "LBTESTCD" in body and "POSITIVE; NEGATIVE" in body
        for _, label in VARIABLE_FIELD_DEFS:
            assert label in body

    def test_print_view_is_standalone_and_has_print_button(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        body = client.get("/specializations/VLM1/print").data.decode()
        assert "window.print()" in body
        assert "@media print" in body
        assert 'class="navbar' not in body

    def test_print_404_for_unknown_spec(self, client):
        assert client.get("/specializations/NOPE/print").status_code == 404


class TestEditCard:
    def _body(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        patcher, _ = _patch_client()
        with patcher:
            return client.get("/specializations/VLM1").data.decode()

    def test_button_order(self, client, app, sample_bc):
        body = self._body(client, app, sample_bc)
        positions = [body.index(label) for label in ("Edit Variable Row", "Add Variable Row", "Save Specialization", ">\n          Cancel")]
        assert positions == sorted(positions)

    def test_edit_button_disabled_until_row_selected(self, client, app, sample_bc):
        import re

        body = self._body(client, app, sample_bc)
        tag = re.search(r'<button[^>]*id="edit-spec-var-btn"[^>]*>', body).group(0)
        assert "disabled" in tag

    def test_offcanvas_card_opens_on_right_with_all_fields(self, client, app, sample_bc):
        from services.ingestion import VARIABLE_FIELD_DEFS

        body = self._body(client, app, sample_bc)
        assert 'id="variable-row-card"' in body
        assert "offcanvas-end" in body
        for field, _ in VARIABLE_FIELD_DEFS:
            assert f'data-card-field="{field}"' in body

    def test_table_shows_all_columns_read_only_with_hidden_inputs(self, client, app, sample_bc):
        from services.ingestion import VARIABLE_FIELD_DEFS

        body = self._body(client, app, sample_bc)
        for _, label in VARIABLE_FIELD_DEFS:
            assert f'<th scope="col">{label}</th>' in body
        # Each stored value is still posted via hidden inputs, unchanged name format.
        assert 'type="hidden" name="variables[0][sdtm_variable]" value="LBTESTCD"' in body
        assert 'type="hidden" name="variables[1][value_list]" value="POSITIVE; NEGATIVE"' in body
        assert 'type="text" class="form-control form-control-sm"\n                         name="variables[' not in body

    def test_export_and_print_links_on_detail_page(self, client, app, sample_bc):
        body = self._body(client, app, sample_bc)
        assert "/specializations/VLM1/export?format=xlsx" in body
        assert "/specializations/VLM1/export?format=csv" in body
        assert "/specializations/VLM1/print" in body

    def test_list_page_has_export_links_per_row(self, client, app, sample_bc):
        _spec_with_vars(app, sample_bc)
        patcher, _ = _patch_client()
        with patcher:
            body = client.get("/specializations/").data.decode()
        assert "/specializations/VLM1/export?format=xlsx" in body


class TestStatusLabels:
    def _set_status(self, app, sample_bc, status):
        with app.app_context():
            spec = db.session.get(DatasetSpecialization, "VLM1")
            if spec is None:
                _spec_with_vars(app, sample_bc)
                spec = db.session.get(DatasetSpecialization, "VLM1")
            spec.status = status
            db.session.commit()

    def _print_body(self, client, app, sample_bc, status):
        self._set_status(app, sample_bc, status)
        return client.get("/specializations/VLM1/print").data.decode()

    def test_print_view_uses_app_status_labels(self, client, app, sample_bc):
        expected = {"provisional": "Provisional", "sme_review": "SME Review", "cdisc_approval": "CDISC Approval", "published": "Ready to Publish"}
        for status, label in expected.items():
            body = self._print_body(client, app, sample_bc, status)
            assert f"<span>Status:</span> {label}<" in body

    def test_ready_to_publish_never_printed_as_published(self, client, app, sample_bc):
        body = self._print_body(client, app, sample_bc, "published")
        assert "Ready to Publish" in body
        assert "<span>Status:</span> Published" not in body


class TestLockedSpecCard:
    def _body(self, client, app, sample_bc, status):
        _spec_with_vars(app, sample_bc)
        with app.app_context():
            db.session.get(DatasetSpecialization, "VLM1").status = status
            db.session.commit()
        patcher, _ = _patch_client()
        with patcher:
            return client.get("/specializations/VLM1").data.decode()

    def test_published_spec_marks_table_locked_and_disables_card_actions(self, client, app, sample_bc):
        import re

        body = self._body(client, app, sample_bc, "published")
        assert 'data-locked="true"' in body
        for btn_id in ("card-apply-btn", "card-delete-btn"):
            tag = re.search(rf'<button[^>]*id="{btn_id}"[^>]*>', body).group(0)
            assert "disabled" in tag

    def test_editable_spec_is_not_locked(self, client, app, sample_bc):
        import re

        body = self._body(client, app, sample_bc, "provisional")
        assert 'data-locked="false"' in body
        tag = re.search(r'<button[^>]*id="card-apply-btn"[^>]*>', body).group(0)
        assert "disabled" not in tag

    def test_card_shows_which_row_is_being_edited(self, client, app, sample_bc):
        body = self._body(client, app, sample_bc, "provisional")
        assert 'id="variable-row-card-subtitle"' in body
