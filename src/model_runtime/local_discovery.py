"""
Local filesystem model discovery engine.

Scans configured roots across multiple drives and folders to discover
usable translation and LLM models. Models are registered with absolute
paths and used in-place -- never copied, moved, or modified.

Supported model formats:
- HuggingFace Transformers (M2M100, NLLB, MarianMT/OPUS, etc.)
- CTranslate2
- GGUF
- Ollama manifests
- SentencePiece tokenizer models
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# GGUF magic number (little-endian): "GGUF" = 0x46475547
GGUF_MAGIC = b"GGUF"

DEFAULT_SKIP_PATTERNS: list[str] = [
    "$RECYCLE.BIN",
    "System Volume Information",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "tmp",
    "temp",
    ".tmp",
    ".temp",
]

# Model type classification from config.json model_type field
MODEL_TYPE_FAMILIES: dict[str, str] = {
    "m2m_100": "m2m100",
    "m2m100": "m2m100",
    "nllb": "nllb",
    "nllb_moe": "nllb",
    "marian": "marian",
    "mbart": "mbart",
    "small100": "small100",
    "opus-mt": "opus",
}


@dataclass
class ScanRoot:
    """A configured root path to scan for models."""

    path: Path
    label: str
    enabled: bool = True
    max_depth: int = 4
    scan_type: str = "auto"  # "auto" | "hf_cache" | "ollama" | "directory"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "label": self.label,
            "enabled": self.enabled,
            "max_depth": self.max_depth,
            "scan_type": self.scan_type,
        }


@dataclass
class DiscoveredLocalModel:
    """A model found on the local filesystem."""

    model_id: str
    display_name: str
    model_family: str  # m2m100, nllb, opus, marian, gguf, ollama, etc.
    model_type: str  # transformers model_type or format-specific type
    backend_type: str  # huggingface, ctranslate2, opus, local_llm
    model_format: str  # transformers, ctranslate2, gguf, ollama, sentencepiece
    absolute_path: Path
    path_exists: bool = True
    detected_from: str = ""  # detector function name
    detected_files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    last_modified: str = ""
    source_language: str | None = None
    target_language: str | None = None
    supported_language_pairs: list[tuple[str, str]] | Literal["all"] = "all"
    multilingual: bool = True
    tokenizer_type: str | None = None
    quantization: str | None = None
    device_hint: str = "cpu"
    load_priority: int = 50  # 0=highest, 100=lowest
    health_status: str = "discovered"  # discovered, available, unavailable
    validation_status: str = "discovered"  # discovered, metadata_valid, loadable, usable, failed
    validation_error: str | None = None
    confidence: float = 0.5  # 0.0-1.0
    notes: str | None = None
    created_by_discovery: bool = True
    discovery_run_id: str | None = None
    hf_model_id: str | None = None

    def to_registry_dict(self) -> dict[str, Any]:
        """Convert to dict compatible with ModelInfo.from_dict()."""
        # Determine backend for ModelInfo
        backend = self.backend_type

        # Build supported_pairs
        if self.supported_language_pairs == "all":
            supported_pairs = "all"
        else:
            supported_pairs = [list(pair) for pair in self.supported_language_pairs]

        # Estimate size in MB and RAM
        size_mb = self.size_bytes / (1024 * 1024) if self.size_bytes else 0
        min_ram_gb = max(1.0, (size_mb / 1024) * 2 + 1.0)

        result: dict[str, Any] = {
            "model_id": self.model_id,
            "name": self.display_name,
            "backend": backend,
            "supported_pairs": supported_pairs,
            "model_size_mb": int(size_mb),
            "min_ram_gb": round(min_ram_gb, 1),
            "optimal_device": self.device_hint,
            "local_path": str(self.absolute_path),
            "hf_model_id": self.hf_model_id,
            "description": (
                f"Auto-discovered {self.model_family} model ({self.model_format}). "
                f"Confidence: {self.confidence:.0%}."
            ),
        }

        # LLM-specific fields for Ollama models
        if backend == "local_llm" and self.model_format == "ollama":
            result["provider"] = "ollama"
            result["model_name"] = self.display_name
            result["base_url"] = "http://localhost:11434"

        return result

    def to_dict(self) -> dict[str, Any]:
        """Full serialization for reports."""
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "model_family": self.model_family,
            "model_type": self.model_type,
            "backend_type": self.backend_type,
            "model_format": self.model_format,
            "absolute_path": str(self.absolute_path),
            "path_exists": self.path_exists,
            "detected_from": self.detected_from,
            "detected_files": self.detected_files,
            "size_bytes": self.size_bytes,
            "last_modified": self.last_modified,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "supported_language_pairs": (
                self.supported_language_pairs
                if self.supported_language_pairs == "all"
                else [list(p) for p in self.supported_language_pairs]
            ),
            "multilingual": self.multilingual,
            "tokenizer_type": self.tokenizer_type,
            "quantization": self.quantization,
            "device_hint": self.device_hint,
            "load_priority": self.load_priority,
            "health_status": self.health_status,
            "validation_status": self.validation_status,
            "validation_error": self.validation_error,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_by_discovery": self.created_by_discovery,
            "discovery_run_id": self.discovery_run_id,
            "hf_model_id": self.hf_model_id,
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _parse_hf_id(dir_name: str) -> str | None:
    """Parse HuggingFace model ID from cache directory name."""
    if not dir_name.startswith("models--"):
        return None
    parts = dir_name.split("--")[1:]
    if len(parts) < 2:
        return None
    org = parts[0]
    model = "--".join(parts[1:])
    return f"{org}/{model}"


def _parse_opus_language_pair(hf_id: str) -> tuple[str, str] | None:
    """Extract (src, tgt) language pair from Helsinki-NLP/opus-mt-XX-YY model ID or path."""
    # Use re.search to handle full paths like /tmp/Helsinki-NLP/opus-mt-en-fr
    match = re.search(r"Helsinki-NLP[/_]opus-mt-([a-z]{2,3})-([a-z]{2,3})$", hf_id, re.IGNORECASE)
    if match:
        return (match.group(1).lower(), match.group(2).lower())
    return None


def _compute_dir_size_bytes(directory: Path) -> int:
    """Compute total size of directory in bytes. Handles permission errors."""
    if not directory.exists():
        return 0
    total = 0
    try:
        for file_path in directory.rglob("*"):
            try:
                if file_path.is_file():
                    total += file_path.stat().st_size
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return total


def _generate_model_id(path: Path, model_format: str, hf_id: str | None = None) -> str:
    """Generate deterministic model_id from path and format."""
    if hf_id:
        base = hf_id.replace("/", "_").replace("-", "_").lower()
    else:
        base = path.stem.replace("-", "_").replace(".", "_").lower()

    # Prefix with format for disambiguation
    prefix = f"disc_{model_format[:3]}_"
    model_id = prefix + base

    # Remove consecutive underscores
    while "__" in model_id:
        model_id = model_id.replace("__", "_")

    return model_id.strip("_")


def _is_safe_to_scan(path: Path, skip_patterns: list[str]) -> bool:
    """Check if path is safe to scan (not in skip list)."""
    name = path.name
    for pattern in skip_patterns:
        if name.lower() == pattern.lower():
            return False
    return True


def _get_last_modified(path: Path) -> str:
    """Get ISO 8601 timestamp of last modification."""
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    except (OSError, PermissionError):
        return ""


def get_default_scan_roots() -> list[ScanRoot]:
    """Get platform-aware default scan roots."""
    roots: list[ScanRoot] = []

    # HuggingFace cache
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    roots.append(
        ScanRoot(
            path=hf_cache,
            label="hf_cache",
            max_depth=3,
            scan_type="hf_cache",
        )
    )

    # Ollama models
    if platform.system() == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            ollama_dir = Path(localappdata) / "Ollama" / "models"
        else:
            ollama_dir = Path.home() / ".ollama" / "models"
    else:
        ollama_dir = Path.home() / ".ollama" / "models"

    roots.append(
        ScanRoot(
            path=ollama_dir,
            label="ollama",
            max_depth=3,
            scan_type="ollama",
        )
    )

    return roots


def get_env_scan_roots() -> list[ScanRoot]:
    """Get scan roots from HUGO_TRANSLATOR_MODEL_SEARCH_ROOTS env var (semicolon-separated)."""
    env_val = os.environ.get("HUGO_TRANSLATOR_MODEL_SEARCH_ROOTS", "")
    if not env_val.strip():
        return []

    roots: list[ScanRoot] = []
    for i, raw_path in enumerate(env_val.split(";")):
        raw_path = raw_path.strip()
        if not raw_path:
            continue
        roots.append(
            ScanRoot(
                path=Path(raw_path),
                label=f"env_root_{i}",
                max_depth=4,
                scan_type="auto",
            )
        )
    return roots


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_hf_cache_models(cache_dir: Path) -> list[DiscoveredLocalModel]:
    """Detect models in a HuggingFace cache directory."""
    results: list[DiscoveredLocalModel] = []

    if not cache_dir.exists():
        logger.debug(f"HF cache dir does not exist: {cache_dir}")
        return results

    for child in cache_dir.iterdir():
        try:
            if not child.is_dir():
                continue

            hf_id = _parse_hf_id(child.name)
            if not hf_id:
                continue

            # Find latest snapshot
            snapshots_dir = child / "snapshots"
            if not snapshots_dir.exists():
                continue

            try:
                snapshots = [s for s in snapshots_dir.iterdir() if s.is_dir()]
            except (PermissionError, OSError):
                continue

            if not snapshots:
                continue

            snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

            # Try to detect model type from config.json
            model = _detect_from_config_json(snapshot, hf_id)
            if model:
                model.detected_from = "detect_hf_cache_models"
                results.append(model)
                continue

            # Check for CT2 model
            ct2 = detect_ctranslate2_model(snapshot)
            if ct2:
                ct2.hf_model_id = hf_id
                ct2.detected_from = "detect_hf_cache_models"
                results.append(ct2)
                continue

        except (PermissionError, OSError) as e:
            logger.debug(f"Skipping {child}: {e}")
            continue

    return results


def _detect_from_config_json(
    model_dir: Path, hf_id: str | None = None
) -> DiscoveredLocalModel | None:
    """Detect model type from config.json in a model directory."""
    config_path = model_dir / "config.json"
    if not config_path.exists():
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    model_type = config.get("model_type", "").lower()
    name_or_path = config.get("_name_or_path", hf_id or "")

    # Classify model family
    family = MODEL_TYPE_FAMILIES.get(model_type, "transformers")

    # Detect language pairs for Opus/Marian
    supported_pairs: list[tuple[str, str]] | Literal["all"] = "all"
    multilingual = True
    src_lang = None
    tgt_lang = None

    if hf_id and _parse_opus_language_pair(hf_id):
        pair = _parse_opus_language_pair(hf_id)
        if pair:
            src_lang, tgt_lang = pair
            supported_pairs = [pair, (tgt_lang, src_lang)]
            multilingual = False
            family = "opus"

    elif model_type == "marian" and name_or_path:
        pair = _parse_opus_language_pair(name_or_path)
        if pair:
            src_lang, tgt_lang = pair
            supported_pairs = [pair, (tgt_lang, src_lang)]
            multilingual = False
            family = "marian"

    # Detect files present
    detected_files = []
    for fname in [
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "pytorch_model.bin",
        "model.safetensors",
        "sentencepiece.bpe.model",
        "spm.model",
        "source.spm",
        "target.spm",
        "vocab.json",
        "merges.txt",
        "generation_config.json",
        "tokenizer.model",
    ]:
        if (model_dir / fname).exists():
            detected_files.append(fname)

    # Detect tokenizer type
    tokenizer_type = None
    if (model_dir / "sentencepiece.bpe.model").exists() or (model_dir / "spm.model").exists():
        tokenizer_type = "sentencepiece"
    elif (model_dir / "tokenizer.json").exists():
        tokenizer_type = "fast_tokenizer"
    elif (model_dir / "vocab.json").exists():
        tokenizer_type = "bpe"

    size_bytes = _compute_dir_size_bytes(model_dir)
    size_mb = size_bytes / (1024 * 1024)

    # Verify model weight files exist — reject tokenizer-only cache entries
    _WEIGHT_FILES = [
        "pytorch_model.bin",
        "model.safetensors",
        "tf_model.h5",
        "flax_model.msgpack",
        "model.ckpt.index",
    ]
    has_weights = any((model_dir / w).exists() for w in _WEIGHT_FILES)
    if not has_weights:
        # Also check sharded weights
        has_weights = any(model_dir.glob("pytorch_model-*.bin")) or any(
            model_dir.glob("model-*.safetensors")
        )
    if not has_weights:
        logger.debug(
            f"Skipping {model_dir}: config.json present but no weight files "
            f"(tokenizer-only cache). detected_files={detected_files}"
        )
        return None

    model_id = _generate_model_id(model_dir, "transformers", hf_id)

    return DiscoveredLocalModel(
        model_id=model_id,
        display_name=hf_id or model_dir.name,
        model_family=family,
        model_type=model_type or "unknown",
        backend_type="huggingface",
        model_format="transformers",
        absolute_path=model_dir,
        path_exists=True,
        detected_files=detected_files,
        size_bytes=size_bytes,
        last_modified=_get_last_modified(model_dir),
        source_language=src_lang,
        target_language=tgt_lang,
        supported_language_pairs=supported_pairs,
        multilingual=multilingual,
        tokenizer_type=tokenizer_type,
        device_hint="cuda" if size_mb > 500 else "cpu",
        load_priority=30 if not multilingual else 50,
        health_status="available",
        validation_status="weights_verified",
        confidence=0.95,
        hf_model_id=hf_id,
    )


def detect_transformers_model(model_dir: Path) -> DiscoveredLocalModel | None:
    """Detect a Transformers model from a standalone directory (not HF cache)."""
    return _detect_from_config_json(model_dir)


def detect_ollama_models(ollama_dir: Path) -> list[DiscoveredLocalModel]:
    """Detect Ollama models from manifests directory."""
    results: list[DiscoveredLocalModel] = []

    manifests_dir = ollama_dir / "manifests" / "registry.ollama.ai" / "library"
    if not manifests_dir.exists():
        # Try alternative structure
        manifests_dir = ollama_dir / "manifests"
        if not manifests_dir.exists():
            logger.debug(f"Ollama manifests dir not found: {ollama_dir}")
            return results

    blobs_dir = ollama_dir / "blobs"

    try:
        for model_name_dir in manifests_dir.iterdir():
            if not model_name_dir.is_dir():
                continue

            for tag_file in model_name_dir.iterdir():
                try:
                    if tag_file.is_dir():
                        # Tag might be in a subdirectory
                        for sub_tag in tag_file.iterdir():
                            if sub_tag.is_file():
                                _parse_ollama_manifest(
                                    sub_tag,
                                    model_name_dir.name,
                                    f"{tag_file.name}/{sub_tag.name}",
                                    blobs_dir,
                                    results,
                                )
                    elif tag_file.is_file():
                        _parse_ollama_manifest(
                            tag_file,
                            model_name_dir.name,
                            tag_file.name,
                            blobs_dir,
                            results,
                        )
                except (PermissionError, OSError) as e:
                    logger.debug(f"Skipping Ollama manifest {tag_file}: {e}")

    except (PermissionError, OSError) as e:
        logger.debug(f"Error scanning Ollama manifests: {e}")

    return results


def _parse_ollama_manifest(
    manifest_path: Path,
    model_name: str,
    tag: str,
    blobs_dir: Path,
    results: list[DiscoveredLocalModel],
) -> None:
    """Parse a single Ollama manifest file."""
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    # Calculate total size from layers
    total_size = 0
    layer_count = 0
    for layer in manifest.get("layers", []):
        size = layer.get("size", 0)
        total_size += size
        layer_count += 1

    display_name = f"{model_name}:{tag}"
    model_id = _generate_model_id(manifest_path, "ollama", display_name)

    results.append(
        DiscoveredLocalModel(
            model_id=model_id,
            display_name=display_name,
            model_family="ollama",
            model_type="ollama",
            backend_type="local_llm",
            model_format="ollama",
            absolute_path=manifest_path.parent.parent.parent,  # ollama models dir
            path_exists=True,
            detected_from="detect_ollama_models",
            detected_files=[manifest_path.name],
            size_bytes=total_size,
            last_modified=_get_last_modified(manifest_path),
            supported_language_pairs="all",
            multilingual=True,
            device_hint="cuda" if total_size > 4 * 1024**3 else "cpu",
            load_priority=60,
            health_status="available",
            validation_status="metadata_valid",
            confidence=0.85,
            notes=f"{layer_count} layers, Ollama manifest",
        )
    )


def detect_ctranslate2_model(model_dir: Path) -> DiscoveredLocalModel | None:
    """Detect a CTranslate2 model from model.bin + model_spec.json or similar."""
    model_bin = model_dir / "model.bin"
    if not model_bin.exists():
        return None

    # Check for CT2 signature files
    spec_path = model_dir / "model_spec.json"
    has_spec = spec_path.exists()

    # Also check for shared_vocabulary.json (another CT2 indicator)
    has_shared_vocab = (model_dir / "shared_vocabulary.json").exists()
    has_source_vocab = (model_dir / "source_vocabulary.json").exists()

    if not (has_spec or has_shared_vocab or has_source_vocab):
        return None

    # Read quantization from spec
    quantization = None
    if has_spec:
        try:
            with open(spec_path, encoding="utf-8") as f:
                spec = json.load(f)
            quantization = spec.get("quantization", None)
        except (json.JSONDecodeError, OSError):
            pass

    detected_files = ["model.bin"]
    if has_spec:
        detected_files.append("model_spec.json")

    size_bytes = _compute_dir_size_bytes(model_dir)
    # Include parent dir name to disambiguate (e.g. en-fr/ct2_int8 → en_fr_ct2_int8)
    parent_name = model_dir.parent.name
    _ct2_id = f"{parent_name}/{model_dir.name}" if parent_name != "." else model_dir.name
    model_id = _generate_model_id(model_dir, "ct2", hf_id=_ct2_id)

    # Extract language pair from directory structure (e.g. en-fr/ct2_int8 or standalone en-fr/)
    src_lang: str | None = None
    tgt_lang: str | None = None
    # Match simple XX-YY or XXX-YY language pair patterns directly
    _LANG_PAIR_RE = re.compile(r"^([a-z]{2,3})-([a-z]{2,3})$")
    for _candidate in [parent_name, model_dir.name]:
        _m = _LANG_PAIR_RE.match(_candidate)
        if _m:
            src_lang, tgt_lang = _m.group(1), _m.group(2)
            break
    # Also try _parse_opus_language_pair for HF-style names
    if not src_lang:
        _pair = _parse_opus_language_pair(parent_name) or _parse_opus_language_pair(model_dir.name)
        if _pair:
            src_lang, tgt_lang = _pair

    model_family = "opus" if src_lang and tgt_lang else "ctranslate2"
    supported_pairs = (
        [(src_lang, tgt_lang), (tgt_lang, src_lang)] if src_lang and tgt_lang else "all"
    )
    multilingual = not (src_lang and tgt_lang)

    return DiscoveredLocalModel(
        model_id=model_id,
        display_name=f"CT2: {parent_name}/{model_dir.name}",
        model_family=model_family,
        model_type="ctranslate2",
        backend_type="ctranslate2",
        model_format="ctranslate2",
        absolute_path=model_dir,
        path_exists=True,
        detected_from="detect_ctranslate2_model",
        detected_files=detected_files,
        size_bytes=size_bytes,
        last_modified=_get_last_modified(model_dir),
        source_language=src_lang,
        target_language=tgt_lang,
        supported_language_pairs=supported_pairs,
        multilingual=multilingual,
        quantization=quantization,
        device_hint="cpu" if quantization == "int8" else "cuda",
        load_priority=20,  # CT2 is fast, prefer it
        health_status="available",
        validation_status="metadata_valid",
        confidence=0.9,
    )


def detect_gguf_model(file_path: Path) -> DiscoveredLocalModel | None:
    """Detect a GGUF model from file with magic bytes validation."""
    if not file_path.is_file():
        return None
    if file_path.suffix.lower() != ".gguf":
        return None

    # Validate magic bytes
    try:
        with open(file_path, "rb") as f:
            magic = f.read(4)
        if magic != GGUF_MAGIC:
            return None
    except (OSError, PermissionError):
        return None

    # Parse quantization from filename (e.g., llama-2-7b-chat.Q4_K_M.gguf)
    quantization = None
    quant_match = re.search(r"[._-](Q\d+_K_[A-Z]+|Q\d+_[A-Z]+|Q\d+|F\d+)", file_path.stem)
    if quant_match:
        quantization = quant_match.group(1)

    size_bytes = file_path.stat().st_size
    model_id = _generate_model_id(file_path, "gguf")

    return DiscoveredLocalModel(
        model_id=model_id,
        display_name=file_path.stem,
        model_family="gguf",
        model_type="gguf",
        backend_type="local_llm",
        model_format="gguf",
        absolute_path=file_path,
        path_exists=True,
        detected_from="detect_gguf_model",
        detected_files=[file_path.name],
        size_bytes=size_bytes,
        last_modified=_get_last_modified(file_path),
        supported_language_pairs="all",
        multilingual=True,
        quantization=quantization,
        device_hint="cuda" if size_bytes > 4 * 1024**3 else "cpu",
        load_priority=70,
        health_status="available",
        validation_status="metadata_valid",
        confidence=0.85,
        notes=f"GGUF file, {size_bytes / (1024**3):.1f} GB",
    )


def detect_sentencepiece_model(file_path: Path) -> DiscoveredLocalModel | None:
    """Detect standalone SentencePiece model file (.model extension)."""
    if not file_path.is_file():
        return None
    if file_path.suffix.lower() != ".model":
        return None

    # Exclude known non-sentencepiece .model files
    if file_path.name in ("model.model",):
        return None

    size_bytes = file_path.stat().st_size

    # SentencePiece models are typically small (< 10MB); skip very large files
    if size_bytes > 50 * 1024 * 1024:
        return None

    model_id = _generate_model_id(file_path, "spm")

    return DiscoveredLocalModel(
        model_id=model_id,
        display_name=f"SPM: {file_path.name}",
        model_family="sentencepiece",
        model_type="sentencepiece",
        backend_type="huggingface",
        model_format="sentencepiece",
        absolute_path=file_path,
        path_exists=True,
        detected_from="detect_sentencepiece_model",
        detected_files=[file_path.name],
        size_bytes=size_bytes,
        last_modified=_get_last_modified(file_path),
        tokenizer_type="sentencepiece",
        load_priority=90,
        health_status="discovered",
        validation_status="discovered",
        confidence=0.3,  # Low confidence -- usually a supporting artifact
        notes="Standalone SentencePiece model; likely a tokenizer component, not a full model.",
    )


# ---------------------------------------------------------------------------
# Main discovery class
# ---------------------------------------------------------------------------


class LocalModelDiscovery:
    """
    Discover local models across configured scan roots.

    Read-only scanner that never copies, moves, or modifies model files.
    """

    def __init__(
        self,
        scan_roots: list[ScanRoot] | None = None,
        skip_patterns: list[str] | None = None,
        enabled_formats: list[str] | None = None,
        follow_symlinks: bool = False,
    ):
        self.scan_roots = scan_roots or get_default_scan_roots()
        self.skip_patterns = skip_patterns or list(DEFAULT_SKIP_PATTERNS)
        self.enabled_formats = enabled_formats or [
            "transformers",
            "ctranslate2",
            "gguf",
            "ollama",
            "sentencepiece",
        ]
        self.follow_symlinks = follow_symlinks

        # Tracking for reports
        self.errors: list[dict[str, str]] = []
        self.skipped_roots: list[dict[str, str]] = []

    def discover_all(self) -> list[DiscoveredLocalModel]:
        """
        Run discovery across all configured scan roots.

        Returns:
            Deduplicated list of discovered models.
        """
        all_models: list[DiscoveredLocalModel] = []
        self.errors = []
        self.skipped_roots = []

        # Add env-var roots
        env_roots = get_env_scan_roots()
        effective_roots = list(self.scan_roots) + env_roots

        for root in effective_roots:
            if not root.enabled:
                self.skipped_roots.append({"path": str(root.path), "reason": "disabled"})
                continue

            if not root.path.exists():
                self.skipped_roots.append({"path": str(root.path), "reason": "not_found"})
                logger.info(f"Scan root not found (skipping): {root.path}")
                continue

            scan_type = root.scan_type
            if scan_type == "auto":
                scan_type = self._auto_detect_scan_type(root.path)

            logger.info(
                f"Scanning [{root.label}] {root.path} (type={scan_type}, depth={root.max_depth})"
            )

            try:
                if scan_type == "hf_cache":
                    models = detect_hf_cache_models(root.path)
                elif scan_type == "ollama":
                    models = detect_ollama_models(root.path)
                elif scan_type == "directory":
                    models = self._scan_directory(root.path, root.max_depth)
                else:
                    models = self._scan_directory(root.path, root.max_depth)

                all_models.extend(models)
                logger.info(f"  Found {len(models)} model(s) in [{root.label}]")

            except (PermissionError, OSError) as e:
                self.errors.append(
                    {
                        "path": str(root.path),
                        "error_type": type(e).__name__,
                        "message": str(e),
                    }
                )
                logger.warning(f"Error scanning [{root.label}] {root.path}: {e}")

        # Deduplicate by normalized absolute path
        deduplicated = self._deduplicate(all_models)
        logger.info(
            f"Discovery complete: {len(deduplicated)} unique models "
            f"(from {len(all_models)} total detections)"
        )
        return deduplicated

    def _auto_detect_scan_type(self, path: Path) -> str:
        """Heuristic to detect scan type from path structure."""
        path_str = str(path).lower().replace("\\", "/")

        if "huggingface" in path_str and "hub" in path_str:
            return "hf_cache"
        if ".cache/huggingface" in path_str:
            return "hf_cache"
        if "ollama" in path_str and "models" in path_str:
            return "ollama"
        if ".ollama" in path_str:
            return "ollama"

        return "directory"

    def _scan_directory(self, root: Path, max_depth: int) -> list[DiscoveredLocalModel]:
        """Scan a generic directory for models up to max_depth."""
        results: list[DiscoveredLocalModel] = []
        root_depth = len(root.parts)

        for entry in self._walk_directory(root, root_depth, max_depth):
            try:
                if entry.is_file():
                    # Check GGUF
                    if "gguf" in self.enabled_formats:
                        gguf = detect_gguf_model(entry)
                        if gguf:
                            results.append(gguf)
                            continue

                    # Check SentencePiece
                    if "sentencepiece" in self.enabled_formats:
                        spm = detect_sentencepiece_model(entry)
                        if spm:
                            results.append(spm)
                            continue

                elif entry.is_dir():
                    # Check Transformers model
                    if "transformers" in self.enabled_formats:
                        tf = detect_transformers_model(entry)
                        if tf:
                            results.append(tf)
                            continue

                    # Check CT2
                    if "ctranslate2" in self.enabled_formats:
                        ct2 = detect_ctranslate2_model(entry)
                        if ct2:
                            results.append(ct2)
                            continue

            except (PermissionError, OSError) as e:
                self.errors.append(
                    {
                        "path": str(entry),
                        "error_type": type(e).__name__,
                        "message": str(e),
                    }
                )

        return results

    def _walk_directory(self, directory: Path, root_depth: int, max_depth: int) -> list[Path]:
        """Bounded recursive directory walk with skip pattern enforcement."""
        entries: list[Path] = []

        current_depth = len(directory.parts) - root_depth
        if current_depth > max_depth:
            return entries

        try:
            for child in directory.iterdir():
                # Skip symlinks unless explicitly enabled
                if child.is_symlink() and not self.follow_symlinks:
                    continue

                if not _is_safe_to_scan(child, self.skip_patterns):
                    continue

                entries.append(child)

                # Recurse into subdirectories (but not detected model dirs)
                if child.is_dir() and current_depth < max_depth:
                    # Don't recurse into directories that look like models
                    if (child / "config.json").exists():
                        continue
                    if (child / "model.bin").exists():
                        continue
                    entries.extend(self._walk_directory(child, root_depth, max_depth))

        except (PermissionError, OSError) as e:
            self.errors.append(
                {
                    "path": str(directory),
                    "error_type": type(e).__name__,
                    "message": str(e),
                }
            )

        return entries

    def _deduplicate(self, models: list[DiscoveredLocalModel]) -> list[DiscoveredLocalModel]:
        """Deduplicate models by normalized absolute path."""
        seen: dict[str, DiscoveredLocalModel] = {}
        for model in models:
            try:
                key = str(model.absolute_path.resolve())
            except (OSError, ValueError):
                key = str(model.absolute_path)

            if key not in seen or model.confidence > seen[key].confidence:
                seen[key] = model

        return list(seen.values())
