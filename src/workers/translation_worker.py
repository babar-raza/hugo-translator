"""
Translation Worker - MCP Server for distributed translation processing.

This worker runs as a separate service/container and exposes MCP tools
for translation operations. It maintains its own L1 cache and connects
to shared L2/L3 TM storage.
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.model_runtime import HardwareDetector, ModelLoader, ModelRegistry
from src.observability.logger import StructuredLogger
from src.observability.metrics import MetricsCollector
from src.tm import TranslationMemory
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.translation_engine import TranslationEngine
from src.utils.config_loader import ConfigService

logger = logging.getLogger(__name__)


class TranslationWorker:
    """
    Translation worker that processes translation jobs.

    Each worker instance:
    - Hosts TranslationEngine with loaded models
    - Maintains L1 in-memory cache
    - Connects to shared L2/L3 TM storage
    - Exposes MCP tools for translation operations
    """

    def __init__(
        self,
        config_path: str = "config/global.yaml",
        site_profiles_dir: str = "config/site_profiles",
        tm_path: str = "data/tm",
        worker_id: str | None = None,
    ):
        """
        Initialize translation worker.

        Args:
            config_path: Path to global configuration file
            site_profiles_dir: Directory containing site profiles
            tm_path: Path to translation memory storage
            worker_id: Unique worker identifier (auto-generated if None)
        """
        self.worker_id = worker_id or f"worker-{id(self)}"
        self.config_path = config_path
        self.site_profiles_dir = site_profiles_dir
        self.tm_path = tm_path

        # Components (initialized in setup())
        self.config_service: ConfigService | None = None
        self.tm: TranslationMemory | None = None
        self.model_loader: ModelLoader | None = None
        self.engine: TranslationEngine | None = None
        self.structured_logger: StructuredLogger | None = None
        self.metrics: MetricsCollector | None = None

        # MCP Server
        self.mcp_server = Server("translation-worker")
        self._register_tools()

        # State
        self._initialized = False
        self._running = False

        logger.info(f"Translation worker {self.worker_id} created")

    async def setup(self) -> None:
        """Initialize all worker components."""
        if self._initialized:
            logger.warning(f"Worker {self.worker_id} already initialized")
            return

        try:
            logger.info(f"Initializing worker {self.worker_id}...")

            # Initialize configuration
            self.config_service = ConfigService(
                config_root=self.config_path
            )
            logger.info("Configuration service initialized")

            # Initialize observability
            self.structured_logger = StructuredLogger(
                name=f"worker.{self.worker_id}"
            )
            self.metrics = MetricsCollector(
                worker_id=self.worker_id,
                push_interval=60,
            )
            logger.info("Observability initialized")

            # Initialize translation memory layers
            l1_cache = L1Cache(max_size=10000)  # Per-worker cache

            # Setup L2 persistent TM path
            from src.tm.l2_persistent import L2_DB_NAME
            _l2_cfg = self.config_service.get_config() if self.config_service else {}
            _l2_max_mb = _l2_cfg.get("tm_defaults", {}).get("l2_max_size_mb", 2048)
            l2_path = Path(self.tm_path) / L2_DB_NAME
            l2_path.mkdir(parents=True, exist_ok=True)
            l2_persistent = L2PersistentTM(str(l2_path), max_size_mb=_l2_max_mb)

            # Setup L3 semantic TM (optional)
            l3_path = Path(self.tm_path) / "l3_faiss"
            l3_path.mkdir(parents=True, exist_ok=True)
            l3_semantic = L3SemanticTM(
                index_path=str(l3_path),
                embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                use_gpu=False
            )

            self.tm = TranslationMemory(
                l1_cache=l1_cache,
                l2_persistent=l2_persistent,
                l3_semantic=l3_semantic
            )
            logger.info("Translation memory initialized")

            # Detect hardware and initialize model runtime
            detector = HardwareDetector()
            hardware = detector.detect()
            logger.info(f"Hardware detected: {len(hardware.cuda_devices)} GPUs, {hardware.cpu_count} CPUs")

            registry = ModelRegistry(registry_path="config/model_registry.yaml")
            raw_config = self.config_service.get_config()
            self.model_loader = ModelLoader(
                registry=registry,
                device=hardware.recommended_device,
                config=raw_config,
            )
            logger.info("Model runtime initialized")

            # Initialize translation engine
            self.engine = TranslationEngine(
                config_service=self.config_service,
                tm=self.tm,
                model_loader=self.model_loader,
                logger=self.structured_logger,
            )
            logger.info("Translation engine initialized")

            self._initialized = True
            logger.info(f"Worker {self.worker_id} initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize worker {self.worker_id}: {e}")
            raise

    async def shutdown(self) -> None:
        """Clean up worker resources."""
        logger.info(f"Shutting down worker {self.worker_id}...")

        self._running = False

        # Close translation memory
        if self.tm:
            self.tm.close()
            logger.info("Translation memory closed")

        # Unload models
        if self.model_loader:
            self.model_loader.unload_all()
            logger.info("Models unloaded")

        # Stop metrics collection
        if self.metrics:
            self.metrics.stop()
            logger.info("Metrics collector stopped")

        logger.info(f"Worker {self.worker_id} shut down successfully")

    def _register_tools(self) -> None:
        """Register MCP tools for translation operations."""

        @self.mcp_server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available translation tools."""
            return [
                Tool(
                    name="translate_hugo_file",
                    description="Translate a single Hugo markdown file to target languages",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "site_id": {
                                "type": "string",
                                "description": "Site profile ID (e.g., 'products.aspose.org')",
                            },
                            "file_path": {
                                "type": "string",
                                "description": "Path to Hugo markdown file",
                            },
                            "target_langs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Target language codes (e.g., ['fr', 'de'])",
                            },
                        },
                        "required": ["site_id", "file_path", "target_langs"],
                    },
                ),
                Tool(
                    name="translate_directory",
                    description="Translate all Hugo markdown files in a directory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "site_id": {
                                "type": "string",
                                "description": "Site profile ID",
                            },
                            "directory_path": {
                                "type": "string",
                                "description": "Path to directory containing markdown files",
                            },
                            "target_langs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Target language codes",
                            },
                            "recursive": {
                                "type": "boolean",
                                "description": "Process subdirectories recursively",
                                "default": True,
                            },
                        },
                        "required": ["site_id", "directory_path", "target_langs"],
                    },
                ),
                Tool(
                    name="tm_exact_lookup",
                    description="Look up exact translation from Translation Memory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "site_id": {"type": "string"},
                            "source_text": {"type": "string"},
                            "source_lang": {"type": "string"},
                            "target_lang": {"type": "string"},
                        },
                        "required": ["site_id", "source_text", "source_lang", "target_lang"],
                    },
                ),
                Tool(
                    name="tm_semantic_lookup",
                    description="Find similar translations using semantic search",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "site_id": {"type": "string"},
                            "source_text": {"type": "string"},
                            "source_lang": {"type": "string"},
                            "target_lang": {"type": "string"},
                            "k": {
                                "type": "integer",
                                "description": "Number of results to return",
                                "default": 5,
                            },
                        },
                        "required": ["site_id", "source_text", "source_lang", "target_lang"],
                    },
                ),
                Tool(
                    name="health_check",
                    description="Check worker health and status",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_stats",
                    description="Get worker statistics and metrics",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]

        @self.mcp_server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls."""
            if not self._initialized:
                await self.setup()

            try:
                if name == "translate_hugo_file":
                    result = await self._translate_file(
                        site_id=arguments["site_id"],
                        file_path=arguments["file_path"],
                        target_langs=arguments["target_langs"],
                    )
                    return [TextContent(type="text", text=str(result))]

                elif name == "translate_directory":
                    result = await self._translate_directory(
                        site_id=arguments["site_id"],
                        directory_path=arguments["directory_path"],
                        target_langs=arguments["target_langs"],
                        recursive=arguments.get("recursive", True),
                    )
                    return [TextContent(type="text", text=str(result))]

                elif name == "tm_exact_lookup":
                    result = await self._tm_exact_lookup(
                        site_id=arguments["site_id"],
                        source_text=arguments["source_text"],
                        source_lang=arguments["source_lang"],
                        target_lang=arguments["target_lang"],
                    )
                    return [TextContent(type="text", text=str(result))]

                elif name == "tm_semantic_lookup":
                    result = await self._tm_semantic_lookup(
                        site_id=arguments["site_id"],
                        source_text=arguments["source_text"],
                        source_lang=arguments["source_lang"],
                        target_lang=arguments["target_lang"],
                        k=arguments.get("k", 5),
                    )
                    return [TextContent(type="text", text=str(result))]

                elif name == "health_check":
                    result = await self._health_check()
                    return [TextContent(type="text", text=str(result))]

                elif name == "get_stats":
                    result = await self._get_stats()
                    return [TextContent(type="text", text=str(result))]

                else:
                    raise ValueError(f"Unknown tool: {name}")

            except Exception as e:
                error_msg = f"Error executing {name}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return [TextContent(type="text", text=error_msg)]

    async def _translate_file(
        self,
        site_id: str,
        file_path: str,
        target_langs: list[str],
    ) -> dict[str, Any]:
        """Translate a single file."""
        logger.info(f"Translating file: {file_path} for site {site_id}")

        # Record metrics
        if self.metrics:
            self.metrics.increment("translations.files.started")

        try:
            result = self.engine.translate_file(
                site_id=site_id,
                file_path=file_path,
                target_langs=target_langs,
            )

            if self.metrics:
                self.metrics.increment("translations.files.completed")

            return {
                "status": "success",
                "file_path": file_path,
                "target_langs": target_langs,
                "result": result.to_dict(),
            }

        except Exception as e:
            if self.metrics:
                self.metrics.increment("translations.files.failed")

            logger.error(f"Translation failed for {file_path}: {e}")
            return {
                "status": "error",
                "file_path": file_path,
                "error": str(e),
            }

    async def _translate_directory(
        self,
        site_id: str,
        directory_path: str,
        target_langs: list[str],
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Translate all files in a directory."""
        logger.info(f"Translating directory: {directory_path} for site {site_id}")

        if self.metrics:
            self.metrics.increment("translations.directories.started")

        try:
            result = self.engine.translate_directory(
                site_id=site_id,
                directory_path=directory_path,
                target_langs=target_langs,
                recursive=recursive,
            )

            if self.metrics:
                self.metrics.increment("translations.directories.completed")

            return {
                "status": "success",
                "directory_path": directory_path,
                "result": result.to_dict(),
            }

        except Exception as e:
            if self.metrics:
                self.metrics.increment("translations.directories.failed")

            logger.error(f"Directory translation failed for {directory_path}: {e}")
            return {
                "status": "error",
                "directory_path": directory_path,
                "error": str(e),
            }

    async def _tm_exact_lookup(
        self,
        site_id: str,
        source_text: str,
        source_lang: str,
        target_lang: str,
    ) -> dict[str, Any]:
        """Look up exact translation in TM."""
        from src.tm.models import LookupRequest

        request = LookupRequest(
            site_id=site_id,
            source_text=source_text,
            source_lang=source_lang,
            target_lang=target_lang,
            context={},
        )

        result = self.tm.exact_lookup(request)

        if result and result.target_text:
            return {
                "status": "found",
                "source_text": source_text,
                "target_text": result.target_text,
                "source": result.source,
            }
        else:
            return {
                "status": "not_found",
                "source_text": source_text,
            }

    async def _tm_semantic_lookup(
        self,
        site_id: str,
        source_text: str,
        source_lang: str,
        target_lang: str,
        k: int = 5,
    ) -> dict[str, Any]:
        """Find similar translations using semantic search."""
        from src.tm.models import LookupRequest

        request = LookupRequest(
            site_id=site_id,
            source_text=source_text,
            source_lang=source_lang,
            target_lang=target_lang,
            context={},
        )

        candidates = self.tm.semantic_lookup(request, k=k)

        return {
            "status": "success",
            "source_text": source_text,
            "candidates": [
                {
                    "target_text": c.target_text,
                    "similarity": c.similarity,
                    "source": c.source,
                }
                for c in candidates
            ],
        }

    async def _health_check(self) -> dict[str, Any]:
        """Check worker health."""
        return {
            "status": "healthy" if self._initialized else "initializing",
            "worker_id": self.worker_id,
            "initialized": self._initialized,
            "running": self._running,
            "tm_status": "connected" if self.tm else "disconnected",
            "model_loaded": self.model_loader.has_loaded_models() if self.model_loader else False,
        }

    async def _get_stats(self) -> dict[str, Any]:
        """Get worker statistics."""
        stats = {
            "worker_id": self.worker_id,
            "initialized": self._initialized,
        }

        if self.tm:
            stats["tm_stats"] = self.tm.get_stats().to_dict()

        if self.model_loader:
            stats["loaded_models"] = self.model_loader.get_loaded_models()

        if self.metrics:
            stats["metrics"] = self.metrics.get_all()

        return stats

    async def run(self) -> None:
        """Run the worker server."""
        self._running = True

        # Setup signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: asyncio.create_task(self.shutdown()))

        # Initialize if not already done
        if not self._initialized:
            await self.setup()

        # Run MCP server
        logger.info(f"Starting MCP server for worker {self.worker_id}")
        async with stdio_server() as (read_stream, write_stream):
            await self.mcp_server.run(
                read_stream,
                write_stream,
                self.mcp_server.create_initialization_options(),
            )


async def main() -> None:
    """Main entry point for translation worker."""
    import os

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Get configuration from environment
    config_path = os.getenv("CONFIG_PATH", "config/global.yaml")
    site_profiles_dir = os.getenv("SITE_PROFILES_DIR", "config/site_profiles")
    tm_path = os.getenv("TM_PATH", "data/tm")
    worker_id = os.getenv("WORKER_ID")

    # Create and run worker
    worker = TranslationWorker(
        config_path=config_path,
        site_profiles_dir=site_profiles_dir,
        tm_path=tm_path,
        worker_id=worker_id,
    )

    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
