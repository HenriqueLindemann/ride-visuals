"""Environment diagnostics command."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ride_visuals.commands.common import load_config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("doctor", help="Verifica ambiente e dependências")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Executa diagnóstico do ambiente de execução e ferramentas instaladas."""
    print("==================================================")
    print(" Ride Visuals — System check")
    print("==================================================")

    tools = {
        "Python": (sys.executable, True),
        "FFmpeg": (shutil.which("ffmpeg"), True),
        "FFprobe": (shutil.which("ffprobe"), True),
        "Node": (shutil.which("node"), True),
        "npm": (shutil.which("npm"), True),
    }

    all_ok = True
    for name, (path, required) in tools.items():
        if path:
            print(f"  [OK] {name:<12} -> {path}")
        else:
            status = "[ERRO]" if required else "[AVISO (Opcional)]"
            print(f"  {status} {name:<12} -> Não encontrado no PATH")
            if required:
                all_ok = False

    modules = [
        "fitdecode",
        "gpxpy",
        "duckdb",
        "pyarrow",
        "pandas",
        "numpy",
        "matplotlib",
        "PIL",
        "dateutil",
        "pytz",
    ]
    for module in modules:
        try:
            __import__(module)
            print(f"  [OK] Python mod   -> {module}")
        except ImportError:
            print(f"  [ERRO] Python mod -> {module} NÃO INSTALADO")
            all_ok = False

    from ride_visuals.video.engines.remotion import RemotionVideoEngine

    config = load_config()
    configured_renderer = config.get("paths", {}).get("renderer_dir")
    renderer_dir = Path(configured_renderer) if configured_renderer else None
    for error in RemotionVideoEngine(renderer_dir=renderer_dir).doctor():
        print(f"  [ERRO] Renderer     -> {error}")
        all_ok = False

    print("--------------------------------------------------")
    if all_ok:
        print(" Diagnóstico concluído: Ambiente pronto para execução.")
    else:
        print(" Diagnóstico com pendências: Verifique os itens acima.")
    print("==================================================")
    if not all_ok:
        raise SystemExit(1)
