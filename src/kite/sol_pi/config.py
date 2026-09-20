"""SoL-Pi JSON configuration (arXiv:2609.20519, NVlabs/SoL-Pi)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kite.config import kite_home
from kite.context.discovery import find_project_root

DEFAULT_CACHE_WRITE_READ_RATIO = 12.5
DEFAULT_REDUCER_PROVIDER = "openai-codex"
DEFAULT_REDUCER_MODEL = "gpt-5.6-luna"

FEATURE_KEYS = (
    "actionFusion",
    "observationPack",
    "evidencePreservingReducer",
    "onlineContextCompact",
)
STRING_KEYS = ("evidencePreservingReducerModel", "evidencePreservingReducerProvider")
CONFIG_KEYS = frozenset({"version", *FEATURE_KEYS, *STRING_KEYS, "cacheWriteReadRatio"})


@dataclass(frozen=True, slots=True)
class SolPiConfig:
    version: int = 1
    action_fusion: bool = False
    observation_pack: bool = False
    evidence_preserving_reducer: bool = False
    evidence_preserving_reducer_model: str = DEFAULT_REDUCER_MODEL
    evidence_preserving_reducer_provider: str = DEFAULT_REDUCER_PROVIDER
    online_context_compact: bool = False
    cache_write_read_ratio: float = DEFAULT_CACHE_WRITE_READ_RATIO

    @property
    def enabled(self) -> bool:
        return (
            self.action_fusion
            or self.observation_pack
            or self.evidence_preserving_reducer
            or self.online_context_compact
        )


def _json_key_to_field(key: str) -> str:
    if key == "actionFusion":
        return "action_fusion"
    if key == "observationPack":
        return "observation_pack"
    if key == "evidencePreservingReducer":
        return "evidence_preserving_reducer"
    if key == "evidencePreservingReducerModel":
        return "evidence_preserving_reducer_model"
    if key == "evidencePreservingReducerProvider":
        return "evidence_preserving_reducer_provider"
    if key == "onlineContextCompact":
        return "online_context_compact"
    if key == "cacheWriteReadRatio":
        return "cache_write_read_ratio"
    return key


def find_config_path(cwd: str | Path = ".", *, allow_project: bool = True) -> Path | None:
    root = find_project_root(Path(cwd).expanduser().resolve())
    if allow_project:
        project_path = root / ".kite" / "sol-pi.json"
        if project_path.is_file():
            return project_path
    global_path = kite_home() / "sol-pi.json"
    return global_path if global_path.is_file() else None


def load_sol_pi_config(cwd: str | Path = ".", *, allow_project: bool = True) -> SolPiConfig:
    path = find_config_path(cwd, allow_project=allow_project)
    if path is None:
        return SolPiConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read SoL-Pi config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to read SoL-Pi config {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"SoL-Pi config must be a JSON object: {path}")

    for key in raw:
        if key not in CONFIG_KEYS:
            raise ValueError(f"Unknown SoL-Pi config key: {key}")

    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"SoL-Pi config version must be 1: {path}")

    for key in FEATURE_KEYS:
        if key in raw and not isinstance(raw[key], bool):
            raise ValueError(f"SoL-Pi config {key} must be boolean: {path}")

    ratio = raw.get("cacheWriteReadRatio", DEFAULT_CACHE_WRITE_READ_RATIO)
    if not isinstance(ratio, (int, float)) or ratio < 0:
        raise ValueError(f"SoL-Pi config cacheWriteReadRatio must be a finite non-negative number: {path}")

    def _string_field(key: str, default: str) -> str:
        value = raw.get(key, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"SoL-Pi config {key} must be a non-empty string: {path}")
        return value.strip()

    kwargs: dict[str, Any] = {
        "version": 1,
        "cache_write_read_ratio": float(ratio),
        "evidence_preserving_reducer_model": _string_field(
            "evidencePreservingReducerModel", DEFAULT_REDUCER_MODEL
        ),
        "evidence_preserving_reducer_provider": _string_field(
            "evidencePreservingReducerProvider", DEFAULT_REDUCER_PROVIDER
        ),
    }
    for key in FEATURE_KEYS:
        field = _json_key_to_field(key)
        kwargs[field] = bool(raw.get(key, False))

    return SolPiConfig(**kwargs)
