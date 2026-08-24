from pathlib import Path

from ride_visuals.analytics.dashboard import AnalyticsDashboardGenerator


def test_dashboard_formats_month_labels(tmp_path: Path):
    generator = AnalyticsDashboardGenerator(
        tmp_path / "catalog.duckdb",
        tmp_path / "streams",
        tmp_path / "outputs",
        locale="pt-BR",
    )

    assert generator._month_labels(["2026-02", "2026-08"]) == ["FEV", "AGO"]
