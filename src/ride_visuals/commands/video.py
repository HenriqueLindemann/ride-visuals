"""Video command registration and dispatch."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import (
    COLLECTION_MOTIONS,
    COLLECTION_STYLES,
    LOCALES,
    MAP_DETAILS,
    OVERLAY_FORMATS,
    THEMES,
    VIDEO_ASPECTS,
    VIDEO_TYPES,
)
from ride_visuals.selection import ActivitySelection


@dataclass(frozen=True)
class VideoCommandContext:
    """Resolved inputs shared by the video render branches."""

    args: argparse.Namespace
    runtime: RuntimeConfig
    outputs_dir: Path
    selection: ActivitySelection
    selection_tag: str
    write_keyframes: bool

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> VideoCommandContext:
        runtime = RuntimeConfig.from_args(args)
        return cls(
            args=args,
            runtime=runtime,
            outputs_dir=runtime.outputs_dir / "videos",
            selection=runtime.selection,
            selection_tag=runtime.selection.slug(),
            write_keyframes=not args.no_keyframes,
        )


def register(subparsers: argparse._SubParsersAction) -> None:
    from ride_visuals.maps.tiles import TILE_PROVIDERS

    parser = subparsers.add_parser("video", help="Renderiza vídeos de rotas, progresso e coleções")
    parser.add_argument(
        "video_type",
        choices=VIDEO_TYPES,
        help="Tipo de vídeo ou overlay",
    )
    parser.add_argument(
        "activity_id",
        type=int,
        nargs="?",
        default=0,
        help="ID da atividade (para clean/telemetry/overlay)",
    )
    parser.add_argument(
        "--motion",
        choices=COLLECTION_MOTIONS,
        default="chronological",
        help=(
            "Cinemática da coleção; elapsed alinha as largadas e preserva a duração real "
            "de cada rota"
        ),
    )
    parser.add_argument(
        "--style",
        choices=COLLECTION_STYLES,
        default="orange",
        help="Paleta aplicada somente aos traçados",
    )
    parser.add_argument(
        "--basemap",
        choices=["plain", *TILE_PROVIDERS],
        default="plain",
        help="Fundo georreferenciado para vídeos de coleção ou atividade",
    )
    parser.add_argument(
        "--map-detail",
        choices=MAP_DETAILS,
        default="standard",
        help="Tiles padrão ou uma camada extra de resolução antes do downsample",
    )
    parser.add_argument("--preview", action="store_true", help="Renderiza versão curta/preview rápido")
    parser.add_argument(
        "--no-keyframes",
        action="store_true",
        help="Não extrai frames de inspeção 0/50/100",
    )
    parser.add_argument("--clean", action="store_true", help="Renderiza coleção sem painel de telemetria")
    parser.add_argument(
        "--aspect",
        choices=VIDEO_ASPECTS,
        default="16:9",
        help=(
            "Canvas do vídeo: paisagem, vertical, Instagram Story horizontal "
            "(gire o telefone) ou UHD 3840x2160"
        ),
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "remotion"],
        default="auto",
        help="Motor visual para atividades e overlays",
    )
    parser.add_argument("--locale", choices=LOCALES, help="Idioma do conteúdo visual")
    parser.add_argument("--theme", choices=THEMES, help="Tema visual compartilhado")
    parser.add_argument(
        "--title",
        help="Override the title of an individual activity (an empty string hides the title)",
    )
    parser.add_argument(
        "--background-image",
        type=str,
        help="Imagem JPEG/PNG/WebP usada atrás da atividade (incompatível com --basemap)",
    )
    parser.add_argument(
        "--background-blur",
        type=float,
        default=0.0,
        help="Desfoque do fundo em pixels (0–100)",
    )
    parser.add_argument(
        "--background-dim",
        type=float,
        default=0.35,
        help="Escurecimento do fundo (0–1)",
    )
    parser.add_argument(
        "--progress-bar",
        action=argparse.BooleanOptionalAction,
        dest="show_progress_bar",
        default=False,
        help="Show the optional progress percentage and bar in activity and collection videos",
    )
    parser.add_argument(
        "--background-tracks",
        action=argparse.BooleanOptionalAction,
        dest="background_tracks",
        default=None,
        help="Show faint background/inactive routes before they are ridden",
    )
    parser.add_argument(
        "--overlay-format",
        choices=OVERLAY_FORMATS,
        default="png",
        help="PNG estático, WebM alpha ou ProRes 4444 MOV",
    )
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Renderiza vídeos com ou sem telemetria, filme de progresso e coleções completas."""
    context = VideoCommandContext.from_args(args)
    if args.video_type == "timeline":
        from ride_visuals.commands.video_collection import render_timeline

        return render_timeline(context)
    if args.video_type == "collection":
        from ride_visuals.commands.video_collection import render_collection

        return render_collection(context)
    if args.video_type == "progress":
        from ride_visuals.commands.video_collection import render_progress

        return render_progress(context)

    from ride_visuals.commands.video_activity import render_activity

    return render_activity(context)
