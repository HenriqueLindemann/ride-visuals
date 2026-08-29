"""Analytics report command."""

from __future__ import annotations

import argparse
import json

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import LOCALES, THEMES


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("report", help="Gera relatórios consolidados e dashboards")
    parser.add_argument(
        "report_type",
        choices=["progress", "dashboard", "timeline"],
        help="Tipo de relatório",
    )
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
    parser.add_argument("--locale", choices=LOCALES, help="Idioma do conteúdo visual")
    parser.add_argument("--theme", choices=THEMES, help="Tema editorial compartilhado")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Gera relatórios de dados, dashboards e progresso esportivo."""
    runtime = RuntimeConfig.from_args(args)
    reports_dir = runtime.outputs_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.report_type == "dashboard":
        from ride_visuals.analytics.dashboard import AnalyticsDashboardGenerator

        print("[Relatório] Gerando painel visual e infográfico de analytics esportivo...")
        generator = AnalyticsDashboardGenerator(
            runtime.catalog_db,
            runtime.streams_dir,
            reports_dir,
            locale=runtime.locale,
            theme=runtime.theme,
            selection=runtime.selection,
        )
        output = generator.generate_dashboard(
            reports_dir / f"ride_summary_{runtime.selection.slug()}.png"
        )
        print(f"[Relatório] Infográfico gerado com sucesso em: {output}")
        return

    if args.report_type == "timeline":
        from ride_visuals.analytics.season_timeline import SeasonTimelineGenerator

        print("[Relatório] Gerando timeline unificada da telemetria...")
        generator = SeasonTimelineGenerator(
            runtime.catalog_db,
            reports_dir,
            locale=runtime.locale,
            theme=runtime.theme,
            selection=runtime.selection,
        )
        locale_tag = runtime.locale.lower().replace("-", "_")
        output = generator.generate(
            reports_dir
            / f"ride_telemetry_timeline_{runtime.selection.slug()}_{locale_tag}_16_9.png"
        )
        print(f"[Relatório] Timeline gerada com sucesso em: {output}")
        return

    from ride_visuals.video.progress_movie import ProgressMovieRenderer

    renderer = ProgressMovieRenderer(
        runtime.catalog_db,
        runtime.streams_dir,
        reports_dir,
        locale=runtime.locale,
        theme=runtime.theme,
        selection=runtime.selection,
    )
    metrics = renderer.extract_summary_metrics()
    output_json = reports_dir / f"progress_metrics_{runtime.selection.slug()}.json"
    with output_json.open("w", encoding="utf-8") as output_file:
        json.dump(metrics, output_file, indent=2, ensure_ascii=False)
    print(f"[Relatório] Métricas consolidadas exportadas em: {output_json}")
