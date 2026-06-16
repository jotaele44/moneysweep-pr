from pathlib import Path

from scripts.alerts.run_project_alerts import run


def test_project_alert_runner_failsoft_no_inputs(tmp_path):
    result = run(tmp_path)
    assert result["status"] == "no_inputs"
    assert result["event_count"] == 0
    assert Path(result["event_path"]).exists()
    assert Path(result["ledger_path"]).exists()
    assert Path(result["spiderweb_path"]).exists()


def test_project_alert_runner_reads_master_and_writes_spiderweb_queue(tmp_path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True)
    master = processed / "pr_all_awards_master.csv"
    master.write_text(
        "award_id,source_dataset,award_date,awarding_agency,recipient_name,obligated_amount,municipio,description\n"
        "A-1,compras_pr,2026-06-16,DDEC,Example Contractor LLC,2450000,Cabo Rojo,Proyecto Esencia engineering site work\n",
        encoding="utf-8",
    )
    result = run(tmp_path)
    assert result["status"] == "ok"
    assert result["record_count"] == 1
    assert result["event_count"] == 1
    assert result["spiderweb_count"] == 1
