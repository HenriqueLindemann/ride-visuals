"""Validação de arquivos de vídeo MP4 e conformidade com padrões de mídia."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any
from PIL import Image


class MediaValidator:
    """Valida duração, resolução, codecs (H.264; AAC opcional) e flag faststart de vídeos MP4."""

    @staticmethod
    def validate_video(file_path: Path) -> Dict[str, Any]:
        file_path = Path(file_path)
        if not file_path.exists():
            return {"valid": False, "error": f"Arquivo não encontrado: {file_path}"}

        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            return {"valid": True, "warning": "ffprobe não disponível para validação profunda."}

        cmd = [
            ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path)
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(res.stdout)
        except Exception as e:
            return {"valid": False, "error": f"Falha ao executar ffprobe: {e}"}

        streams = info.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not video_streams:
            return {"valid": False, "error": "Nenhum stream de vídeo encontrado."}

        v_stream = video_streams[0]
        v_codec = v_stream.get("codec_name")
        width = int(v_stream.get("width", 0))
        height = int(v_stream.get("height", 0))
        duration = float(info.get("format", {}).get("duration", 0.0))
        pixel_format = v_stream.get("pix_fmt")

        has_audio = len(audio_streams) > 0
        a_codec = audio_streams[0].get("codec_name") if has_audio else None

        # Checar se moov atom está no início (faststart)
        # Faststart é padrão se os primeiros 100KB contêm b"moov"
        with open(file_path, "rb") as f:
            header_bytes = f.read(102400)
            has_faststart = b"moov" in header_bytes

        violations = []
        if v_codec != "h264":
            violations.append("video codec must be H.264")
        if pixel_format != "yuv420p":
            violations.append("pixel format must be yuv420p")
        supported_canvases = {(1920, 1080), (1080, 1920), (3840, 2160)}
        if "_preview" in file_path.stem:
            supported_canvases = supported_canvases | {(960, 540), (540, 960)}
        if (width, height) not in supported_canvases:
            violations.append("canvas must use a canonical project preset")

        if duration <= 0.5:
            violations.append("duration is empty")
        elif "_preview" not in file_path.stem and abs(duration - 15.0) > 0.15:
            violations.append("final MP4 must be 15 seconds")
        elif "_preview" in file_path.stem and duration > 10.15:
            violations.append("preview must be at most 10 seconds")
        if has_audio and a_codec != "aac":
            violations.append("audio track must be AAC when present")
        if not has_faststart:
            violations.append("faststart moov atom is missing")

        valid = not violations

        return {
            "valid": valid,
            "filename": file_path.name,
            "width": width,
            "height": height,
            "duration_s": round(duration, 2),
            "video_codec": v_codec,
            "pixel_format": pixel_format,
            "audio_codec": a_codec,
            "has_faststart": has_faststart,
            "size_bytes": file_path.stat().st_size,
            "violations": violations,
        }

    @staticmethod
    def validate_transparent_still(file_path: Path) -> Dict[str, Any]:
        """Verify that an overlay PNG preserves a real alpha channel."""
        file_path = Path(file_path)
        try:
            with Image.open(file_path) as image:
                has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
                alpha_extrema = image.convert("RGBA").getchannel("A").getextrema() if has_alpha else (255, 255)
                has_transparency = alpha_extrema[0] < 255
                width, height = image.size
        except Exception as exc:
            return {"valid": False, "error": f"Falha ao abrir PNG: {exc}"}
        supported_dimensions = {(1920, 1080), (1080, 1920), (3840, 2160)}
        if "_preview" in file_path.stem:
            supported_dimensions = supported_dimensions | {(960, 540), (540, 960)}
        valid = has_alpha and has_transparency and (width, height) in supported_dimensions
        return {
            "valid": valid,
            "filename": file_path.name,
            "width": width,
            "height": height,
            "has_alpha": has_alpha,
            "has_transparency": has_transparency,
            "violations": [] if valid else ["PNG must contain transparent pixels at a supported canvas size"],
        }

    @staticmethod
    def validate_transparent_video(file_path: Path) -> Dict[str, Any]:
        """Verify duration, codec and alpha metadata for WebM/MOV overlays."""
        file_path = Path(file_path)
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            return {"valid": False, "error": "ffprobe não disponível."}
        cmd = [
            ffprobe_bin, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(file_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(res.stdout)
            stream = next(s for s in info.get("streams", []) if s.get("codec_type") == "video")
        except Exception as exc:
            return {"valid": False, "error": f"Falha ao executar ffprobe: {exc}"}

        codec = stream.get("codec_name")
        pixel_format = stream.get("pix_fmt", "")
        tags = {str(key).lower(): value for key, value in stream.get("tags", {}).items()}
        alpha_tag = str(tags.get("alpha_mode", "0")) == "1"
        has_alpha = "a" in pixel_format or alpha_tag
        duration = float(info.get("format", {}).get("duration", 0.0))
        expected_codec = "vp9" if file_path.suffix.lower() == ".webm" else "prores"
        dimensions = (int(stream.get("width", 0)), int(stream.get("height", 0)))
        supported_dimensions = {(1920, 1080), (1080, 1920), (3840, 2160)}
        if "_preview" in file_path.stem:
            supported_dimensions = supported_dimensions | {(960, 540), (540, 960)}
        violations = []
        if codec != expected_codec:
            violations.append(f"codec must be {expected_codec}")
        if not has_alpha:
            violations.append("alpha channel is missing")
        if dimensions not in supported_dimensions:
            violations.append("canvas must use a canonical project preset")

        if duration <= 0.5:
            violations.append("duration is empty")
        elif "_preview" in file_path.stem and duration > 10.15:
            violations.append("preview must be at most 10 seconds")
        elif "_preview" not in file_path.stem and abs(duration - 15.0) > 0.15:
            violations.append("transparent video must be 15 seconds")
        return {
            "valid": not violations,
            "filename": file_path.name,
            "width": dimensions[0],
            "height": dimensions[1],
            "duration_s": round(duration, 2),
            "video_codec": codec,
            "pixel_format": pixel_format,
            "has_alpha": has_alpha,
            "violations": violations,
        }
