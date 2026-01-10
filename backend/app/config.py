from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"
    internal_assets_dir: Path = Path(__file__).resolve().parents[1] / "assets"

    projects_dir: Path = data_dir / "projects"
    uploads_dir: Path = data_dir / "uploads"
    runs_dir: Path = data_dir / "runs"
    vector_store_dir: Path = data_dir / "vector_store"
    outputs_dir: Path = data_dir / "outputs"

    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000",)


SETTINGS = Settings()

