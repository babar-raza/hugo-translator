"""
HuggingFace Hub model discovery and auto-registration.

Discovers translation models from HuggingFace Hub and automatically
registers them to the model registry.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml
from huggingface_hub import HfApi

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredModel:
    """
    Metadata for a discovered model from HuggingFace Hub.
    """

    model_id: str
    hf_model_name: str
    name: str
    backend: str
    languages: List[str]
    downloads: int
    likes: int
    tags: List[str]
    description: str


class ModelDiscovery:
    """
    Discover and register translation models from HuggingFace Hub.
    """

    def __init__(self, registry_path: Path | str = "config/model_registry.yaml"):
        """
        Initialize model discovery.

        Args:
            registry_path: Path to model registry YAML file
        """
        self.registry_path = Path(registry_path)
        self.api = HfApi()
        self.existing_models = self._load_existing_models()

    def _load_existing_models(self) -> set:
        """
        Load existing model IDs from registry.

        Returns:
            Set of existing model IDs
        """
        if not self.registry_path.exists():
            return set()

        with open(self.registry_path, "r") as f:
            data = yaml.safe_load(f)

        models = data.get("models", [])
        return {model["model_id"] for model in models}

    def discover_translation_models(
        self,
        limit: int = 50,
        min_downloads: int = 1000,
        sort: str = "downloads",
        languages: Optional[List[str]] = None,
    ) -> List[DiscoveredModel]:
        """
        Discover translation models from HuggingFace Hub.

        Args:
            limit: Maximum number of models to discover
            min_downloads: Minimum number of downloads required
            sort: Sort criterion (downloads, likes, trending)
            languages: Filter by language codes (e.g., ['en', 'de', 'fr'])

        Returns:
            List of discovered models
        """
        logger.info(f"Discovering translation models (limit={limit}, min_downloads={min_downloads})...")

        # Search for translation models using direct parameters
        models = self.api.list_models(
            task="translation",
            library="transformers",
            sort=sort,
            direction=-1,  # Descending order
            limit=limit * 2,  # Get extra to filter
        )

        discovered = []
        for model in models:
            if len(discovered) >= limit:
                break

            # Skip if already in registry
            model_id_candidate = self._generate_model_id(model.modelId)
            if model_id_candidate in self.existing_models:
                logger.debug(f"Skipping {model.modelId} (already in registry)")
                continue

            # Skip if too few downloads
            if model.downloads < min_downloads:
                continue

            # Extract language info
            model_languages = self._extract_languages(model.tags)
            if languages and not any(lang in model_languages for lang in languages):
                continue

            discovered_model = DiscoveredModel(
                model_id=model_id_candidate,
                hf_model_name=model.modelId,
                name=self._generate_display_name(model.modelId),
                backend="huggingface",
                languages=model_languages,
                downloads=model.downloads,
                likes=model.likes,
                tags=model.tags or [],
                description=f"Auto-discovered from HuggingFace Hub ({model.downloads:,} downloads)",
            )
            discovered.append(discovered_model)

        logger.info(f"Discovered {len(discovered)} new translation models")
        return discovered

    def _generate_model_id(self, hf_model_name: str) -> str:
        """
        Generate model_id from HuggingFace model name.

        Args:
            hf_model_name: HuggingFace model name (e.g., "facebook/m2m100_418M")

        Returns:
            model_id (e.g., "m2m100_418m")
        """
        # Extract model name after last slash
        name = hf_model_name.split("/")[-1]

        # Convert to lowercase and replace special chars
        model_id = name.lower().replace("-", "_").replace(".", "_")

        # Remove consecutive underscores
        while "__" in model_id:
            model_id = model_id.replace("__", "_")

        return model_id.strip("_")

    def _generate_display_name(self, hf_model_name: str) -> str:
        """
        Generate display name from HuggingFace model name.

        Args:
            hf_model_name: HuggingFace model name

        Returns:
            Human-readable display name
        """
        name = hf_model_name.split("/")[-1]
        # Convert underscores/dashes to spaces, capitalize words
        return " ".join(word.capitalize() for word in name.replace("_", " ").replace("-", " ").split())

    def _extract_languages(self, tags: List[str]) -> List[str]:
        """
        Extract language codes from model tags.

        Args:
            tags: List of model tags

        Returns:
            List of language codes
        """
        if not tags:
            return []

        # Common language tag prefixes
        lang_prefixes = ["language:", "lang:", ""]

        languages = []
        for tag in tags:
            tag_lower = tag.lower()

            # Check for language codes (2-3 letter codes)
            for prefix in lang_prefixes:
                if tag_lower.startswith(prefix):
                    lang_code = tag_lower[len(prefix):]
                    if 2 <= len(lang_code) <= 3 and lang_code.isalpha():
                        languages.append(lang_code)

        # Deduplicate and sort
        return sorted(set(languages))

    def register_models(
        self,
        models: List[DiscoveredModel],
        dry_run: bool = False,
    ) -> int:
        """
        Register discovered models to model registry.

        Args:
            models: List of discovered models to register
            dry_run: If True, print what would be added without modifying file

        Returns:
            Number of models registered
        """
        if not models:
            logger.warning("No models to register")
            return 0

        # Load existing registry
        with open(self.registry_path, "r") as f:
            registry_data = yaml.safe_load(f)

        existing_count = len(registry_data.get("models", []))

        # Add new models
        for model in models:
            model_entry = {
                "model_id": model.model_id,
                "name": model.name,
                "hf_model_name": model.hf_model_name,
                "backend": model.backend,
                "languages": model.languages if model.languages else ["multilingual"],
                "tags": ["auto-discovered"] + model.tags[:5],  # Limit tags
                "metadata": {
                    "downloads": model.downloads,
                    "likes": model.likes,
                    "description": model.description,
                    "auto_discovered": True,
                },
            }

            if dry_run:
                logger.info(f"[DRY RUN] Would register: {model.model_id} ({model.hf_model_name})")
            else:
                registry_data["models"].append(model_entry)
                logger.info(f"Registered: {model.model_id} ({model.hf_model_name})")

        if dry_run:
            logger.info(f"[DRY RUN] Would add {len(models)} models to registry")
            return 0

        # Save updated registry
        with open(self.registry_path, "w") as f:
            yaml.dump(
                registry_data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        new_count = len(registry_data.get("models", []))
        logger.info(f"Registry updated: {existing_count} → {new_count} models (+{len(models)})")

        return len(models)

    def discover_and_register(
        self,
        limit: int = 10,
        min_downloads: int = 1000,
        dry_run: bool = False,
        languages: Optional[List[str]] = None,
    ) -> int:
        """
        Discover and register models in one step.

        Args:
            limit: Maximum models to discover
            min_downloads: Minimum downloads threshold
            dry_run: Preview without modifying registry
            languages: Filter by language codes

        Returns:
            Number of models registered
        """
        models = self.discover_translation_models(
            limit=limit,
            min_downloads=min_downloads,
            languages=languages,
        )

        return self.register_models(models, dry_run=dry_run)
