"""Shared FFmpeg writer for Pillow-based video renderers."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PIL import Image


class RawVideoEncoder:
    """Stream fixed-size RGB frames to a normalized H.264/AAC MP4."""

    def __init__(
        self,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        operation: str,
    ) -> None:
        self.output_path = Path(output_path)
        self.width = width
        self.height = height
        self.fps = fps
        self.operation = operation
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr: list[bytes] = []
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> "RawVideoEncoder":
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{self.width}x{self.height}", "-pix_fmt", "rgb24",
            "-r", str(self.fps), "-i", "-",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            "-movflags", "+faststart", str(self.output_path),
        ]
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self._process.stderr is not None
        self._stderr_thread = threading.Thread(
            target=lambda: self._stderr.append(self._process.stderr.read()),
            daemon=True,
        )
        self._stderr_thread.start()
        return self

    def write(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height):
            raise ValueError(
                f"Video frame has size {frame.size}; expected {(self.width, self.height)}"
            )
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Video encoder is not running")
        self._process.stdin.write(frame.tobytes())

    def __exit__(self, exc_type, exc, traceback) -> bool:
        assert self._process is not None
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()

        if exc_type is not None and self._process.poll() is None:
            self._process.terminate()
        self._process.wait()
        if self._stderr_thread is not None:
            self._stderr_thread.join()

        if exc_type is None and self._process.returncode != 0:
            error = b"".join(self._stderr).decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg {self.operation} error: {error}")
        return False
