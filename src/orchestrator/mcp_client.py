"""
MCP Client for Orchestrator to communicate with Translation Workers.

Provides high-level interface for dispatching translation jobs to workers via MCP.
"""

import asyncio
import logging
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class WorkerClient:
    """
    MCP client for communicating with a single translation worker.

    Manages connection to worker and provides methods for invoking worker tools.
    """

    def __init__(self, worker_id: str, command: str, args: list[str] | None = None):
        """
        Initialize worker client.

        Args:
            worker_id: Unique worker identifier
            command: Command to launch worker process (e.g., "python -m src.workers.translation_worker")
            args: Optional command-line arguments
        """
        self.worker_id = worker_id
        self.command = command
        self.args = args or []

        # MCP session
        self.session: ClientSession | None = None
        self._read_stream: Any | None = None
        self._write_stream: Any | None = None

        # Connection state
        self._connected = False

    async def connect(self) -> None:
        """Connect to worker process."""
        if self._connected:
            logger.warning(f"Worker {self.worker_id} already connected")
            return

        try:
            # Split command into executable and args
            cmd_parts = self.command.split()
            server_params = StdioServerParameters(
                command=cmd_parts[0],
                args=cmd_parts[1:] + self.args,
                env=None,
            )

            # Create MCP client connection
            read_stream, write_stream = await stdio_client(server_params)
            self._read_stream = read_stream
            self._write_stream = write_stream

            # Create session
            self.session = ClientSession(read_stream, write_stream)

            # Initialize session
            await self.session.initialize()

            self._connected = True
            logger.info(f"Connected to worker {self.worker_id}")

        except Exception as e:
            logger.error(f"Failed to connect to worker {self.worker_id}: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from worker."""
        if not self._connected:
            return

        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
                self.session = None

            self._connected = False
            logger.info(f"Disconnected from worker {self.worker_id}")

        except Exception as e:
            logger.error(f"Error disconnecting from worker {self.worker_id}: {e}")

    async def translate_file(
        self,
        site_id: str,
        file_path: str,
        target_langs: list[str],
    ) -> dict[str, Any]:
        """
        Translate a single file via worker.

        Args:
            site_id: Site profile ID
            file_path: Path to Hugo markdown file
            target_langs: Target language codes

        Returns:
            Translation result dictionary
        """
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(
                "translate_hugo_file",
                arguments={
                    "site_id": site_id,
                    "file_path": file_path,
                    "target_langs": target_langs,
                },
            )

            return self._parse_result(result)

        except Exception as e:
            logger.error(f"Error translating file via worker {self.worker_id}: {e}")
            raise

    async def translate_directory(
        self,
        site_id: str,
        directory_path: str,
        target_langs: list[str],
        recursive: bool = True,
    ) -> dict[str, Any]:
        """
        Translate directory via worker.

        Args:
            site_id: Site profile ID
            directory_path: Path to directory
            target_langs: Target language codes
            recursive: Process subdirectories

        Returns:
            Translation result dictionary
        """
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(
                "translate_directory",
                arguments={
                    "site_id": site_id,
                    "directory_path": directory_path,
                    "target_langs": target_langs,
                    "recursive": recursive,
                },
            )

            return self._parse_result(result)

        except Exception as e:
            logger.error(f"Error translating directory via worker {self.worker_id}: {e}")
            raise

    async def tm_exact_lookup(
        self,
        site_id: str,
        source_text: str,
        source_lang: str,
        target_lang: str,
    ) -> str | None:
        """
        Look up exact translation in TM.

        Args:
            site_id: Site profile ID
            source_text: Source text
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            Translation if found, None otherwise
        """
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(
                "tm_exact_lookup",
                arguments={
                    "site_id": site_id,
                    "source_text": source_text,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                },
            )

            data = self._parse_result(result)
            return data.get("target_text") if data.get("status") == "found" else None

        except Exception as e:
            logger.error(f"Error in TM exact lookup via worker {self.worker_id}: {e}")
            return None

    async def health_check(self) -> dict[str, Any]:
        """
        Check worker health.

        Returns:
            Health status dictionary
        """
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(
                "health_check",
                arguments={},
            )

            return self._parse_result(result)

        except Exception as e:
            logger.error(f"Error checking health of worker {self.worker_id}: {e}")
            return {
                "status": "unhealthy",
                "worker_id": self.worker_id,
                "error": str(e),
            }

    async def get_stats(self) -> dict[str, Any]:
        """
        Get worker statistics.

        Returns:
            Statistics dictionary
        """
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(
                "get_stats",
                arguments={},
            )

            return self._parse_result(result)

        except Exception as e:
            logger.error(f"Error getting stats from worker {self.worker_id}: {e}")
            return {}

    @staticmethod
    def _parse_result(result: Any) -> dict[str, Any]:
        """Parse MCP result into dictionary."""
        import json

        if hasattr(result, "content"):
            # Extract text from content
            text = result.content[0].text if result.content else "{}"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}

        return {}

    def is_connected(self) -> bool:
        """Check if connected to worker."""
        return self._connected


class WorkerPool:
    """
    Pool of worker clients for load balancing and fault tolerance.

    Manages multiple worker connections and distributes jobs across them.
    """

    def __init__(self, workers: list[WorkerClient] | None = None):
        """
        Initialize worker pool.

        Args:
            workers: List of WorkerClient instances
        """
        self.workers: list[WorkerClient] = workers or []
        self._current_index = 0
        self._lock = asyncio.Lock()

    async def add_worker(self, worker: WorkerClient) -> None:
        """
        Add worker to pool.

        Args:
            worker: WorkerClient instance
        """
        async with self._lock:
            self.workers.append(worker)
            logger.info(f"Added worker {worker.worker_id} to pool (total: {len(self.workers)})")

    async def remove_worker(self, worker_id: str) -> bool:
        """
        Remove worker from pool.

        Args:
            worker_id: Worker identifier

        Returns:
            True if removed, False if not found
        """
        async with self._lock:
            for i, worker in enumerate(self.workers):
                if worker.worker_id == worker_id:
                    await worker.disconnect()
                    del self.workers[i]
                    logger.info(f"Removed worker {worker_id} from pool")
                    return True
            return False

    async def get_next_worker(self) -> WorkerClient | None:
        """
        Get next available worker (round-robin).

        Returns:
            WorkerClient or None if no workers available
        """
        async with self._lock:
            if not self.workers:
                return None

            # Round-robin selection
            worker = self.workers[self._current_index]
            self._current_index = (self._current_index + 1) % len(self.workers)

            # Ensure worker is connected
            if not worker.is_connected():
                try:
                    await worker.connect()
                except Exception as e:
                    logger.error(f"Failed to connect to worker {worker.worker_id}: {e}")
                    return await self.get_next_worker()  # Try next worker

            return worker

    async def translate_file(
        self,
        site_id: str,
        file_path: str,
        target_langs: list[str],
    ) -> dict[str, Any]:
        """Translate file using next available worker."""
        worker = await self.get_next_worker()
        if not worker:
            raise RuntimeError("No workers available")

        return await worker.translate_file(site_id, file_path, target_langs)

    async def translate_directory(
        self,
        site_id: str,
        directory_path: str,
        target_langs: list[str],
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Translate directory using next available worker."""
        worker = await self.get_next_worker()
        if not worker:
            raise RuntimeError("No workers available")

        return await worker.translate_directory(
            site_id, directory_path, target_langs, recursive
        )

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """
        Check health of all workers.

        Returns:
            Dictionary mapping worker_id to health status
        """
        results = {}
        for worker in self.workers:
            try:
                health = await worker.health_check()
                results[worker.worker_id] = health
            except Exception as e:
                results[worker.worker_id] = {
                    "status": "unhealthy",
                    "error": str(e),
                }

        return results

    async def disconnect_all(self) -> None:
        """Disconnect all workers."""
        for worker in self.workers:
            try:
                await worker.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting worker {worker.worker_id}: {e}")

    def size(self) -> int:
        """Get number of workers in pool."""
        return len(self.workers)

    def __len__(self) -> int:
        """Return number of workers."""
        return len(self.workers)
