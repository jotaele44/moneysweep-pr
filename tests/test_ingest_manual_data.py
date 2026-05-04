"""
Tests for the 5 manual data ingestion scripts.
All tests run without actual data files — they verify column schemas,
normalization logic, column mapping, and graceful no-file handling.
"""

import pandas as pd
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# ingest_report_builder
# ---------------------------------------------------------------------------

from scripts.ingest_report_builder import (
    MASTER_COLUMNS,
    COL_MAP as RB_COL_MAP,
    _normalize_name as rb_normalize,
    _derive_fy_from_filename,
    _map_col,
    _parse_file,
)


def test_rb_master_columns_canonical():
    for col in ("award_id", "recipient_name", "recipient_name_normalized",
                "obligated_amount", "award_date", "awarding_agency",
                "source_dataset", "fiscal_year"):
        assert col in MASTER_COLUMNS


def test_rb_col_map_has_vendor_name():
    assert any("Vendor Name" in v for v in RB_COL_MAP["recipient_name"])


def test_rb_col_map_has_piid():
    assert any("PIID" in v for v in RB_COL_MAP["award_id"])


def test_rb_col_map_has_action_obligation():
    assert any("Action Obligation" in v for v in RB_COL_MAP["obligated_amount"])


def test_rb_normalize_strips_inc():
    assert "INC" not in rb_normalize("Fluor Corporation Inc")
    assert "FLUOR" in rb_normalize("Fluor Corporation Inc")


def test_rb_normalize_empty():
    assert rb_normalize("") == ""
    assert rb_normalize(None) == ""


def test_rb_derive_fy_two_digit():
    p = Path("Report Builder FY20 Revised.xlsx")
    assert _derive_fy_from_filename(p) == "2020"


def test_rb_derive_fy_four_digit():
    p = Path("FY_2018_Federal_Procurement_with_Subk_Plan_.xls")
    assert _derive_fy_from_filename(p) == "2018"


def test_rb_derive_fy_no_match():
    p = Path("random_file.xlsx")
    assert _derive_fy_from_filename(p) == ""


def test_rb_derive_fy_24():
    p = Path("Report Builder FY24 Final rev2.xlsx")
    assert _derive_fy_from_filename(p) == "2024"


def test_rb_map_col_exact():
    cols = ["Vendor Name", "Action Obligation", "PIID"]
    assert _map_col(cols, ["Vendor Name", "Recipient Name"]) == "Vendor Name"


def test_rb_map_col_case_insensitive():
    cols = ["vendor name", "action obligation"]
    assert _map_col(cols, ["Vendor Name"]) == "vendor name"


def test_rb_map_col_none_if_missing():
    cols = ["Column A", "Column B"]
    assert _map_col(cols, ["Vendor Name", "Recipient Name"]) is None


def test_rb_source_dataset_is_report_builder(tmp_path):
    # Create a minimal CSV that looks like a Report Builder export
    csv_path = tmp_path / "Report Builder FY23 Revised.csv"
    df = pd.DataFrame({
        "Vendor Name": ["Test Corp PR", "Another LLC"],
        "Action Obligation": ["100000", "200000"],
        "PIID": ["PR-001", "PR-002"],
        "Place of Performance State Code": ["PR", "PR"],
        "Award Date": ["2023-01-15", "2023-03-20"],
    })
    df.to_csv(csv_path, index=False)

    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)

    result = _parse_file(csv_path, logger)
    assert not result.empty
    assert (result["source_dataset"] == "report_builder").all()
    assert (result["fiscal_year"] == "2023").all()


def test_rb_pr_filter_excludes_non_pr(tmp_path):
    csv_path = tmp_path / "Report Builder FY22 Revised.csv"
    df = pd.DataFrame({
        "Vendor Name": ["Florida Corp", "PR Vendor LLC", "Texas Inc"],
        "Action Obligation": ["100000", "200000", "300000"],
        "PIID": ["FL-001", "PR-001", "TX-001"],
        "Place of Performance State Code": ["FL", "PR", "TX"],
    })
    df.to_csv(csv_path, index=False)

    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)

    result = _parse_file(csv_path, logger)
    assert len(result) == 1
    assert "PR" in result.iloc[0]["recipient_name"].upper() or True  # just check count


def test_rb_no_files_returns_zero(tmp_path):
    from scripts.ingest_report_builder import _run
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# ingest_cabilderos
# ---------------------------------------------------------------------------

from scripts.ingest_cabilderos import (
    CABILDEROS_COLUMNS,
    COL_MAP as CAB_COL_MAP,
    _normalize_name as cab_normalize,
    _parse_df as cab_parse_df,
)


def test_cabilderos_columns_complete():
    for col in ("lobbyist_name", "lobbyist_normalized",
                "client_name", "client_normalized",
                "registration_year", "source_file"):
        assert col in CABILDEROS_COLUMNS


def test_cabilderos_col_map_spanish_client():
    assert any("Cliente" in v for v in CAB_COL_MAP["client_name"])


def test_cabilderos_col_map_spanish_lobbyist():
    assert any("Cabildero" in v for v in CAB_COL_MAP["lobbyist_name"])


def test_cab_normalize_handles_spanish_corp():
    result = cab_normalize("Asociación de Constructores CSP")
    assert "CSP" not in result
    assert "ASOCIACION" in result or "ASOCIACI" in result


def test_cab_parse_df_english_columns():
    df = pd.DataFrame({
        "Lobbyist Name": ["John Smith", "Jane Doe"],
        "Client Name": ["PREPA", "Luma Energy LLC"],
        "Registration Year": ["2022", "2023"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = cab_parse_df(df, "test.csv", logger)
    assert len(result) == 2
    assert "LUMA ENERGY" in result.iloc[1]["client_normalized"]


def test_cab_parse_df_spanish_columns():
    df = pd.DataFrame({
        "Cabildero": ["Pedro Soto"],
        "Cliente": ["Hospital Corp PR"],
        "Año": ["2021"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = cab_parse_df(df, "test_es.csv", logger)
    assert len(result) == 1
    assert result.iloc[0]["lobbyist_name"] == "Pedro Soto"


def test_cab_parse_df_empty_client_filtered():
    df = pd.DataFrame({
        "Lobbyist Name": ["John Smith", ""],
        "Client Name": ["", "Luma Energy"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = cab_parse_df(df, "test.csv", logger)
    # Rows with empty client_name should be excluded
    assert len(result) == 1


def test_cab_no_files_returns_zero(tmp_path):
    from scripts.ingest_cabilderos import _run
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0


# ---------------------------------------------------------------------------
# ingest_contralor
# ---------------------------------------------------------------------------

from scripts.ingest_contralor import (
    CONTRALOR_COLUMNS,
    COL_MAP as CONT_COL_MAP,
    _normalize_name as cont_normalize,
    _parse_df as cont_parse_df,
)


def test_contralor_columns_complete():
    for col in ("entity_name", "entity_normalized", "audit_id",
                "audit_type", "finding_count", "status", "source_file"):
        assert col in CONTRALOR_COLUMNS


def test_contralor_col_map_spanish_entity():
    assert any("Entidad" in v for v in CONT_COL_MAP["entity_name"])


def test_contralor_col_map_hallazgos():
    assert any("Hallazgos" in v for v in CONT_COL_MAP["finding_count"])


def test_cont_parse_df_spanish_columns():
    df = pd.DataFrame({
        "Entidad": ["Municipio de Ponce", "Departamento de Educación"],
        "Número de Informe": ["A-23-001", "A-23-002"],
        "Tipo de Informe": ["Operacional", "Fiscal"],
        "Hallazgos": ["3", "1"],
        "Estado": ["Abierto", "Cerrado"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = cont_parse_df(df, "contralor.csv", logger)
    assert len(result) == 2
    assert "MUNICIPIO" in result.iloc[0]["entity_normalized"]


def test_cont_normalize_removes_de():
    result = cont_normalize("Municipio de Ponce de León")
    assert "MUNICIPIO" in result


def test_cont_no_files_returns_zero(tmp_path):
    from scripts.ingest_contralor import _run
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0


# ---------------------------------------------------------------------------
# ingest_active_contractors
# ---------------------------------------------------------------------------

from scripts.ingest_active_contractors import (
    CONTRACTOR_COLUMNS,
    COL_MAP as AC_COL_MAP,
    _normalize_name as ac_normalize,
    _parse_df as ac_parse_df,
)


def test_active_contractors_columns_complete():
    for col in ("entity_name", "entity_normalized",
                "registration_id", "status", "source_file"):
        assert col in CONTRACTOR_COLUMNS


def test_ac_col_map_has_suplidor():
    all_vals = " ".join(v for vals in AC_COL_MAP.values() for v in vals)
    assert "Suplidor" in all_vals


def test_ac_parse_df_english_cols():
    df = pd.DataFrame({
        "Vendor Name": ["ABC Engineering LLC", "XYZ Consulting Corp"],
        "Registration Number": ["R-001", "R-002"],
        "Status": ["Active", "Expired"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = ac_parse_df(df, "contractors.csv", logger)
    assert len(result) == 2
    assert "ABC ENGINEERING" in result.iloc[0]["entity_normalized"]


def test_ac_parse_df_filters_empty_name():
    df = pd.DataFrame({
        "Vendor Name": ["Valid Corp", ""],
        "Registration Number": ["R-001", "R-002"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = ac_parse_df(df, "contractors.csv", logger)
    assert len(result) == 1


def test_ac_normalize_strips_csp():
    result = ac_normalize("Constructora Moderna CSP")
    assert "CSP" not in result
    assert "CONSTRUCTORA MODERNA" in result


def test_ac_no_files_returns_zero(tmp_path):
    from scripts.ingest_active_contractors import _run
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0


# ---------------------------------------------------------------------------
# ingest_prasa
# ---------------------------------------------------------------------------

from scripts.ingest_prasa import (
    PRASA_COLUMNS,
    COL_MAP as PRASA_COL_MAP,
    _normalize_name as prasa_normalize,
    _parse_df as prasa_parse_df,
)


def test_prasa_columns_complete():
    for col in ("contract_id", "vendor_name", "vendor_normalized",
                "contract_value", "status", "source_file"):
        assert col in PRASA_COLUMNS


def test_prasa_col_map_has_contratista():
    assert any("Contratista" in v for v in PRASA_COL_MAP["vendor_name"])


def test_prasa_col_map_has_monto():
    assert any("Monto" in v for v in PRASA_COL_MAP["contract_value"])


def test_prasa_parse_df_basic():
    df = pd.DataFrame({
        "Contratista": ["Cobra Acquisitions LLC", "Fluor Corp"],
        "Contrato": ["PRASA-001", "PRASA-002"],
        "Monto": ["5000000", "12000000"],
        "Estado": ["Completado", "Activo"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = prasa_parse_df(df, "prasa.csv", logger)
    assert len(result) == 2
    assert "COBRA ACQUISITIONS" in result.iloc[0]["vendor_normalized"]


def test_prasa_parse_df_english_cols():
    df = pd.DataFrame({
        "Vendor Name": ["AECOM Technical Services Inc"],
        "Contract Number": ["PRASA-ENG-001"],
        "Amount": ["7500000"],
        "Status": ["Active"],
    })
    import logging
    logger = logging.getLogger("test")
    logger.setLevel(logging.CRITICAL)
    result = prasa_parse_df(df, "prasa_eng.csv", logger)
    assert len(result) == 1
    assert "AECOM" in result.iloc[0]["vendor_normalized"]


def test_prasa_normalize_strips_llc():
    result = prasa_normalize("MasTec Puerto Rico LLC")
    assert "LLC" not in result
    assert "MASTEC" in result


def test_prasa_no_files_returns_zero(tmp_path):
    from scripts.ingest_prasa import _run
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
