"""Importação de arquivos FIT avulsos para a coleção."""

from __future__ import annotations

import argparse
from pathlib import Path

from ride_visuals.commands.common import RuntimeConfig, print_ingest_stats


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ingest-fit",
        help="Importa arquivos FIT avulsos na coleção",
        description=(
            "Copia arquivos .fit/.fit.gz avulsos para o export e os registra "
            "no activities.csv, depois ingere apenas as novas atividades. "
            "Útil para atividades gravadas fora da Strava ou baixadas "
            "individualmente."
        ),
    )
    parser.add_argument("files", nargs="+", help="Arquivos .fit ou .fit.gz a importar")
    parser.add_argument(
        "--name",
        help="Nome da atividade (padrão: nome do arquivo); válido para um único arquivo",
    )
    parser.add_argument(
        "--type",
        help="Tipo da atividade (padrão: mapeado do campo sport do FIT)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria importado sem alterar arquivos",
    )
    parser.add_argument("--bulk-dir", type=str, help="Caminho para o diretório bulk_download")
    parser.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    parser.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Importa os FITs avulsos e ingere as atividades novas no catálogo."""
    from ride_visuals.ingest.pipeline import IngestPipeline
    from ride_visuals.ingest.standalone import (
        STATUS_IMPORTED,
        StandaloneFitImporter,
    )

    if args.name and len(args.files) > 1:
        raise SystemExit("--name só pode ser usado com um único arquivo")

    runtime = RuntimeConfig.from_args(args)
    importer = StandaloneFitImporter(
        bulk_dir=runtime.bulk_dir,
        name=args.name,
        activity_type=args.type,
        dry_run=args.dry_run,
    )

    print("[Importação FIT] Fonte dos arquivos: usuário")
    print(f"  Export: {importer.csv_file}")
    print(f"  Pasta de atividades: {importer.activities_dir}")

    labels = {"imported": "Importado", "duplicate": "Duplicado", "error": "Erro"}
    results = importer.import_files([Path(f) for f in args.files])
    for result in results:
        print(f"  [{labels[result.status]}] {result.source.name}: {result.message}")

    imported = [r for r in results if r.status == STATUS_IMPORTED]
    if not imported:
        print("\nNada a ingestar; catálogo inalterado.")
        return
    if args.dry_run:
        print(f"\n[dry-run] {len(imported)} atividade(s) seria(m) importada(s). Nada foi alterado.")
        return

    # Garante que o tipo recém-importado passe pelo filtro de ingestão mesmo
    # fora dos activity_types configurados.
    imported_types = {r.activity_type for r in imported if r.activity_type}
    activity_types = sorted(set(runtime.activity_types) | imported_types)
    if imported_types - set(runtime.activity_types):
        extra = ", ".join(sorted(imported_types - set(runtime.activity_types)))
        print(f"  Filtro de tipos ampliado para incluir: {extra}")

    for result in imported:
        if not runtime.selection.matches(result.start_date):
            print(
                f"  [Aviso] {result.name} ({result.start_date:%Y-%m-%d}) fora do recorte "
                "temporal selecionado; será importada no activities.csv mas não no catálogo."
            )

    pipeline = IngestPipeline(
        bulk_dir=runtime.bulk_dir,
        catalog_db_path=runtime.catalog_db,
        streams_dir=runtime.streams_dir,
        selection=runtime.selection,
        activity_types=activity_types,
        only_ids={r.activity_id for r in imported if r.activity_id},
    )
    stats = pipeline.run_ingest()
    print_ingest_stats(stats)
