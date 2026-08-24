"""Local privacy-zone configuration shared by maps and collection videos."""

from pathlib import Path

import pandas as pd


def load_privacy_zones(path: Path | None) -> list[dict[str, float]]:
    """Load privacy zones from a small, provider-neutral CSV file."""
    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Privacy-zone file not found: {path}")

    frame = pd.read_csv(path)
    if not {"latitude", "longitude"}.issubset(frame.columns):
        raise ValueError(
            "Privacy-zone CSV must contain latitude, longitude, and optional radius_km columns"
        )
    return [
        {
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "radius_m": float(row.get("radius_km", 0.2)) * 1000.0,
        }
        for _, row in frame.iterrows()
    ]
