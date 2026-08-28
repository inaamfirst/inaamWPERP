from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ModuleStatus = Literal["implemented", "scaffold", "disabled"]
ModuleReleaseStatus = Literal["production_ready", "foundation_only"]


class ModuleManifest(BaseModel):
    id: str = Field(min_length=2)
    name: str = Field(min_length=2)
    version: str = Field(min_length=1)
    description: str
    status: ModuleStatus = "scaffold"
    release_status: ModuleReleaseStatus = "production_ready"
    release_note: str | None = None
    enabled_by_default: bool = True
    dependencies: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    api_routes: list[str] = Field(default_factory=list)
    migrations: list[str] = Field(default_factory=list)
    desktop_pages: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "release_status": self.release_status,
            "release_note": self.release_note,
            "enabled_by_default": self.enabled_by_default,
            "dependencies": self.dependencies,
        }


def default_modules_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "modules"


def load_module_manifest(module_dir: Path) -> ModuleManifest:
    manifest_path = module_dir / "module.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing module manifest: {manifest_path}")

    manifest = ModuleManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.id != module_dir.name:
        raise ValueError(f"Module id {manifest.id!r} must match folder {module_dir.name!r}")
    return manifest


def load_module_manifests(modules_dir: Path | None = None) -> list[ModuleManifest]:
    root = modules_dir or default_modules_dir()
    manifests = [
        load_module_manifest(path)
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / "module.json").exists()
    ]
    ids = [manifest.id for manifest in manifests]
    duplicates = sorted({module_id for module_id in ids if ids.count(module_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate module ids: {', '.join(duplicates)}")

    available = set(ids)
    for manifest in manifests:
        missing = sorted(set(manifest.dependencies) - available)
        if missing:
            raise ValueError(f"Module {manifest.id!r} has missing dependencies: {missing}")
    return manifests


def dump_manifest_template(path: Path, manifest: ModuleManifest) -> None:
    path.write_text(
        json.dumps(manifest.model_dump(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
