from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"
    internal_assets_dir: Path = Path(__file__).resolve().parents[1] / "assets"
    internal_materials_dir: Path = internal_assets_dir / "internal_materials"
    agent_kb_dir: Path = internal_assets_dir / "agent_kb"
    agent_prompts_dir: Path = internal_assets_dir / "agent_prompts"

    projects_dir: Path = data_dir / "projects"
    uploads_dir: Path = data_dir / "uploads"
    runs_dir: Path = data_dir / "runs"
    vector_store_dir: Path = data_dir / "vector_store"
    outputs_dir: Path = data_dir / "outputs"

    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000",)


SETTINGS = Settings()

