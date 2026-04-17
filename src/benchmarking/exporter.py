"""Data export functionality for benchmark database.

Supports exporting benchmark data to multiple formats:
- CSV: Flat file for spreadsheet analysis
- JSON: Structured data for programmatic use
- SQLite: Full database copy for archival

Features:
- Export filters: date range, model_id, device, metric types
- Export progress tracking for large datasets
- Compression support (gzip for CSV/JSON)

Phase 4.3: Data Retention & Export
"""

import csv
import gzip
import json
import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class ExportFilter:
    """Filter criteria for data export.

    Attributes:
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        model_ids: List of model IDs to include (None = all)
        devices: List of devices to include (None = all)
        tables: List of tables to export (None = all exportable)
    """

    start_date: str | None = None
    end_date: str | None = None
    model_ids: list[str] | None = None
    devices: list[str] | None = None
    tables: list[str] | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "model_ids": self.model_ids,
            "devices": self.devices,
            "tables": self.tables,
        }


@dataclass
class ExportProgress:
    """Progress tracking for export operation.

    Attributes:
        table: Current table being exported
        rows_exported: Rows exported so far
        total_rows: Total rows to export (estimated)
        percent_complete: Completion percentage
    """

    table: str
    rows_exported: int
    total_rows: int
    percent_complete: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "table": self.table,
            "rows_exported": self.rows_exported,
            "total_rows": self.total_rows,
            "percent_complete": self.percent_complete,
        }


@dataclass
class ExportResult:
    """Result of export operation.

    Attributes:
        format: Export format (csv, json, sqlite)
        output_path: Path to exported file
        rows_exported: Total rows exported
        tables_exported: Tables exported
        file_size_bytes: Size of exported file
        compressed: Whether output was compressed
        duration_seconds: Export duration
        error: Error message if failed
    """

    format: str
    output_path: str
    rows_exported: int
    tables_exported: list[str]
    file_size_bytes: int
    compressed: bool
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "format": self.format,
            "output_path": self.output_path,
            "rows_exported": self.rows_exported,
            "tables_exported": self.tables_exported,
            "file_size_bytes": self.file_size_bytes,
            "compressed": self.compressed,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class BenchmarkExporter:
    """Exports benchmark data to various formats.

    Features:
    - Export to CSV, JSON, or SQLite formats
    - Filter by date range, model, device
    - Compression support (gzip)
    - Progress callbacks for large exports
    - Telemetry event emission

    Example:
        exporter = BenchmarkExporter(db_path="data/benchmarks.db")

        # Export all data to CSV
        result = exporter.export_csv("export.csv")

        # Export filtered data to JSON with compression
        filter = ExportFilter(
            start_date="2024-01-01",
            model_ids=["m2m100_418m"],
            devices=["cpu"]
        )
        result = exporter.export_json("export.json.gz", filter=filter, compress=True)

        # Full SQLite backup
        result = exporter.export_sqlite("backup.db")
    """

    # Tables that can be exported
    EXPORTABLE_TABLES = [
        "benchmark_runs",
        "benchmark_results",
        "system_info",
        "benchmark_trends",
        "performance_baselines",
        "recommendation_feedback",
        "recommendation_weights",
    ]

    def __init__(
        self,
        db_path: Path | str,
        engines: Optional["SharedEngines"] = None,
    ):
        """Initialize exporter.

        Args:
            db_path: Path to benchmark database
            engines: Optional SharedEngines for logging/telemetry
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.engines = engines

        if engines:
            logger.info("BenchmarkExporter initialized with SharedEngines support")

    def _create_connection(self) -> sqlite3.Connection:
        """Create database connection with proper settings.

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _emit_telemetry(self, event: str, **kwargs) -> None:
        """Emit telemetry event.

        Args:
            event: Event name
            **kwargs: Event parameters
        """
        if self.engines:
            self.engines.telemetry.track_event(event, **kwargs)

    def export_csv(
        self,
        output_path: str | Path,
        filter: ExportFilter | None = None,
        compress: bool = False,
        progress_callback: Callable[[ExportProgress], None] | None = None,
    ) -> ExportResult:
        """Export benchmark data to CSV format.

        Creates one CSV file per table, or a single compressed archive.

        Args:
            output_path: Output file path (directory for multiple files)
            filter: Optional export filter
            compress: Whether to compress output with gzip
            progress_callback: Optional callback for progress updates

        Returns:
            ExportResult object
        """
        start_time = datetime.now(UTC)
        output_path = Path(output_path)

        self._emit_telemetry(
            "benchmark_export_started",
            format="csv",
            compress=compress,
            filter=filter.to_dict() if filter else None,
        )

        logger.info(f"Starting CSV export to {output_path}")

        try:
            conn = self._create_connection()
            tables = self._get_export_tables(filter)
            total_rows = 0
            exported_tables = []

            # Create output directory if exporting multiple files
            if not compress:
                output_path.mkdir(parents=True, exist_ok=True)

            for table in tables:
                rows = self._export_table_to_csv(
                    conn, table, output_path, filter, compress, progress_callback
                )
                total_rows += rows
                if rows > 0:
                    exported_tables.append(table)

            conn.close()

            # Calculate file size
            if compress:
                file_size = output_path.stat().st_size if output_path.exists() else 0
            else:
                file_size = sum(
                    f.stat().st_size
                    for f in output_path.glob("*.csv")
                    if f.is_file()
                )

            duration = (datetime.now(UTC) - start_time).total_seconds()

            result = ExportResult(
                format="csv",
                output_path=str(output_path),
                rows_exported=total_rows,
                tables_exported=exported_tables,
                file_size_bytes=file_size,
                compressed=compress,
                duration_seconds=duration,
            )

            logger.info(
                f"CSV export completed: {total_rows} rows from {len(exported_tables)} tables "
                f"in {duration:.2f}s ({file_size:,} bytes)"
            )

            self._emit_telemetry(
                "benchmark_export_completed",
                format="csv",
                rows_exported=total_rows,
                tables_exported=len(exported_tables),
                file_size_bytes=file_size,
                duration_seconds=duration,
            )

            return result

        except Exception as e:
            logger.error(f"CSV export failed: {e}", exc_info=True)

            self._emit_telemetry(
                "benchmark_export_failed",
                format="csv",
                error=str(e),
            )

            return ExportResult(
                format="csv",
                output_path=str(output_path),
                rows_exported=0,
                tables_exported=[],
                file_size_bytes=0,
                compressed=compress,
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                error=str(e),
            )

    def _export_table_to_csv(
        self,
        conn: sqlite3.Connection,
        table: str,
        output_path: Path,
        filter: ExportFilter | None,
        compress: bool,
        progress_callback: Callable[[ExportProgress], None] | None,
    ) -> int:
        """Export a single table to CSV.

        Args:
            conn: Database connection
            table: Table name
            output_path: Output path
            filter: Export filter
            compress: Whether to compress
            progress_callback: Progress callback

        Returns:
            Number of rows exported
        """
        # Get filtered query
        query, params = self._build_export_query(table, filter)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return 0

        # Get column names
        columns = [desc[0] for desc in cursor.description]

        # Determine output file
        if compress:
            csv_file = output_path.with_suffix(f".{table}.csv.gz")
            file_handle = gzip.open(csv_file, "wt", encoding="utf-8")
        else:
            csv_file = output_path / f"{table}.csv"
            file_handle = open(csv_file, "w", newline="", encoding="utf-8")

        try:
            writer = csv.writer(file_handle)
            writer.writerow(columns)

            total_rows = len(rows)
            for i, row in enumerate(rows):
                writer.writerow(row)

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(ExportProgress(
                        table=table,
                        rows_exported=i + 1,
                        total_rows=total_rows,
                        percent_complete=(i + 1) / total_rows * 100,
                    ))

            return len(rows)

        finally:
            file_handle.close()

    def export_json(
        self,
        output_path: str | Path,
        filter: ExportFilter | None = None,
        compress: bool = False,
        progress_callback: Callable[[ExportProgress], None] | None = None,
        pretty_print: bool = False,
    ) -> ExportResult:
        """Export benchmark data to JSON format.

        Creates a single JSON file with all exported data.

        Args:
            output_path: Output file path
            filter: Optional export filter
            compress: Whether to compress output with gzip
            progress_callback: Optional callback for progress updates
            pretty_print: Whether to format JSON with indentation

        Returns:
            ExportResult object
        """
        start_time = datetime.now(UTC)
        output_path = Path(output_path)

        self._emit_telemetry(
            "benchmark_export_started",
            format="json",
            compress=compress,
            filter=filter.to_dict() if filter else None,
        )

        logger.info(f"Starting JSON export to {output_path}")

        try:
            conn = self._create_connection()
            tables = self._get_export_tables(filter)

            export_data = {
                "export_metadata": {
                    "exported_at": datetime.now(UTC).isoformat(),
                    "source_database": str(self.db_path),
                    "filter": filter.to_dict() if filter else None,
                },
                "tables": {},
            }

            total_rows = 0
            exported_tables = []

            for table in tables:
                rows = self._export_table_to_json(
                    conn, table, filter, progress_callback
                )
                if rows:
                    export_data["tables"][table] = rows
                    total_rows += len(rows)
                    exported_tables.append(table)

            conn.close()

            # Write output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            indent = 2 if pretty_print else None

            if compress:
                with gzip.open(output_path, "wt", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=indent, default=str)
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=indent, default=str)

            file_size = output_path.stat().st_size
            duration = (datetime.now(UTC) - start_time).total_seconds()

            result = ExportResult(
                format="json",
                output_path=str(output_path),
                rows_exported=total_rows,
                tables_exported=exported_tables,
                file_size_bytes=file_size,
                compressed=compress,
                duration_seconds=duration,
            )

            logger.info(
                f"JSON export completed: {total_rows} rows from {len(exported_tables)} tables "
                f"in {duration:.2f}s ({file_size:,} bytes)"
            )

            self._emit_telemetry(
                "benchmark_export_completed",
                format="json",
                rows_exported=total_rows,
                tables_exported=len(exported_tables),
                file_size_bytes=file_size,
                duration_seconds=duration,
            )

            return result

        except Exception as e:
            logger.error(f"JSON export failed: {e}", exc_info=True)

            self._emit_telemetry(
                "benchmark_export_failed",
                format="json",
                error=str(e),
            )

            return ExportResult(
                format="json",
                output_path=str(output_path),
                rows_exported=0,
                tables_exported=[],
                file_size_bytes=0,
                compressed=compress,
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                error=str(e),
            )

    def _export_table_to_json(
        self,
        conn: sqlite3.Connection,
        table: str,
        filter: ExportFilter | None,
        progress_callback: Callable[[ExportProgress], None] | None,
    ) -> list[dict]:
        """Export a single table to JSON format.

        Args:
            conn: Database connection
            table: Table name
            filter: Export filter
            progress_callback: Progress callback

        Returns:
            List of row dictionaries
        """
        query, params = self._build_export_query(table, filter)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return []

        columns = [desc[0] for desc in cursor.description]
        result = []

        total_rows = len(rows)
        for i, row in enumerate(rows):
            result.append(dict(zip(columns, row, strict=False)))

            if progress_callback and (i + 1) % 1000 == 0:
                progress_callback(ExportProgress(
                    table=table,
                    rows_exported=i + 1,
                    total_rows=total_rows,
                    percent_complete=(i + 1) / total_rows * 100,
                ))

        return result

    def export_sqlite(
        self,
        output_path: str | Path,
        filter: ExportFilter | None = None,
        progress_callback: Callable[[ExportProgress], None] | None = None,
    ) -> ExportResult:
        """Export benchmark database to SQLite backup.

        Creates a full or filtered copy of the database.

        Args:
            output_path: Output file path
            filter: Optional export filter (if None, does full backup)
            progress_callback: Optional callback for progress updates

        Returns:
            ExportResult object
        """
        start_time = datetime.now(UTC)
        output_path = Path(output_path)

        self._emit_telemetry(
            "benchmark_export_started",
            format="sqlite",
            filter=filter.to_dict() if filter else None,
        )

        logger.info(f"Starting SQLite export to {output_path}")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if filter is None:
                # Full backup using SQLite's backup API
                return self._full_sqlite_backup(output_path, start_time, progress_callback)
            else:
                # Filtered export
                return self._filtered_sqlite_export(
                    output_path, filter, start_time, progress_callback
                )

        except Exception as e:
            logger.error(f"SQLite export failed: {e}", exc_info=True)

            self._emit_telemetry(
                "benchmark_export_failed",
                format="sqlite",
                error=str(e),
            )

            return ExportResult(
                format="sqlite",
                output_path=str(output_path),
                rows_exported=0,
                tables_exported=[],
                file_size_bytes=0,
                compressed=False,
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                error=str(e),
            )

    def _full_sqlite_backup(
        self,
        output_path: Path,
        start_time: datetime,
        progress_callback: Callable[[ExportProgress], None] | None,
    ) -> ExportResult:
        """Perform full database backup.

        Args:
            output_path: Output file path
            start_time: Export start time
            progress_callback: Progress callback

        Returns:
            ExportResult object
        """
        if self.db_path == ":memory:":
            raise ValueError("Cannot backup in-memory database")

        # Use shutil for simple file copy (fastest method)
        shutil.copy2(str(self.db_path), str(output_path))

        # Get row counts
        source_conn = self._create_connection()
        total_rows = 0
        tables = []

        for table in self.EXPORTABLE_TABLES:
            try:
                cursor = source_conn.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                total_rows += count
                if count > 0:
                    tables.append(table)
            except sqlite3.Error:
                pass

        source_conn.close()

        file_size = output_path.stat().st_size
        duration = (datetime.now(UTC) - start_time).total_seconds()

        result = ExportResult(
            format="sqlite",
            output_path=str(output_path),
            rows_exported=total_rows,
            tables_exported=tables,
            file_size_bytes=file_size,
            compressed=False,
            duration_seconds=duration,
        )

        logger.info(
            f"SQLite full backup completed: {total_rows} rows from {len(tables)} tables "
            f"in {duration:.2f}s ({file_size:,} bytes)"
        )

        self._emit_telemetry(
            "benchmark_export_completed",
            format="sqlite",
            rows_exported=total_rows,
            tables_exported=len(tables),
            file_size_bytes=file_size,
            duration_seconds=duration,
        )

        return result

    def _filtered_sqlite_export(
        self,
        output_path: Path,
        filter: ExportFilter,
        start_time: datetime,
        progress_callback: Callable[[ExportProgress], None] | None,
    ) -> ExportResult:
        """Perform filtered database export.

        Args:
            output_path: Output file path
            filter: Export filter
            start_time: Export start time
            progress_callback: Progress callback

        Returns:
            ExportResult object
        """
        source_conn = self._create_connection()

        # Create new database with same schema
        dest_conn = sqlite3.connect(str(output_path))
        dest_conn.row_factory = sqlite3.Row

        try:
            # Copy schema
            cursor = source_conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
            )
            for row in cursor.fetchall():
                try:
                    dest_conn.execute(row[0])
                except sqlite3.Error:
                    pass  # Table might already exist

            # Copy indices
            cursor = source_conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
            for row in cursor.fetchall():
                try:
                    dest_conn.execute(row[0])
                except sqlite3.Error:
                    pass

            dest_conn.commit()

            # Export filtered data
            tables = self._get_export_tables(filter)
            total_rows = 0
            exported_tables = []

            for table in tables:
                rows = self._copy_table_data(
                    source_conn, dest_conn, table, filter, progress_callback
                )
                if rows > 0:
                    total_rows += rows
                    exported_tables.append(table)

            dest_conn.commit()

            file_size = output_path.stat().st_size
            duration = (datetime.now(UTC) - start_time).total_seconds()

            result = ExportResult(
                format="sqlite",
                output_path=str(output_path),
                rows_exported=total_rows,
                tables_exported=exported_tables,
                file_size_bytes=file_size,
                compressed=False,
                duration_seconds=duration,
            )

            logger.info(
                f"SQLite filtered export completed: {total_rows} rows from {len(exported_tables)} tables "
                f"in {duration:.2f}s ({file_size:,} bytes)"
            )

            self._emit_telemetry(
                "benchmark_export_completed",
                format="sqlite",
                rows_exported=total_rows,
                tables_exported=len(exported_tables),
                file_size_bytes=file_size,
                duration_seconds=duration,
            )

            return result

        finally:
            source_conn.close()
            dest_conn.close()

    def _copy_table_data(
        self,
        source_conn: sqlite3.Connection,
        dest_conn: sqlite3.Connection,
        table: str,
        filter: ExportFilter,
        progress_callback: Callable[[ExportProgress], None] | None,
    ) -> int:
        """Copy filtered data from source to destination.

        Args:
            source_conn: Source database connection
            dest_conn: Destination database connection
            table: Table name
            filter: Export filter
            progress_callback: Progress callback

        Returns:
            Number of rows copied
        """
        query, params = self._build_export_query(table, filter)

        cursor = source_conn.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return 0

        columns = [desc[0] for desc in cursor.description]
        placeholders = ",".join("?" * len(columns))

        total_rows = len(rows)
        for i, row in enumerate(rows):
            try:
                dest_conn.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    tuple(row),
                )
            except sqlite3.Error as e:
                logger.warning(f"Failed to insert row into {table}: {e}")

            if progress_callback and (i + 1) % 1000 == 0:
                progress_callback(ExportProgress(
                    table=table,
                    rows_exported=i + 1,
                    total_rows=total_rows,
                    percent_complete=(i + 1) / total_rows * 100,
                ))

        return len(rows)

    def _get_export_tables(self, filter: ExportFilter | None) -> list[str]:
        """Get list of tables to export.

        Args:
            filter: Export filter

        Returns:
            List of table names
        """
        if filter and filter.tables:
            return [t for t in filter.tables if t in self.EXPORTABLE_TABLES]
        return self.EXPORTABLE_TABLES

    def _build_export_query(
        self, table: str, filter: ExportFilter | None
    ) -> tuple[str, list]:
        """Build SQL query with filters.

        Args:
            table: Table name
            filter: Export filter

        Returns:
            Tuple of (query string, parameters list)
        """
        query = f"SELECT * FROM {table}"
        params = []
        conditions = []

        if filter:
            # Date range filter
            if filter.start_date:
                if table == "benchmark_runs":
                    conditions.append("timestamp_utc >= ?")
                    params.append(filter.start_date)
                elif table == "benchmark_results":
                    conditions.append(
                        "run_id IN (SELECT run_id FROM benchmark_runs WHERE timestamp_utc >= ?)"
                    )
                    params.append(filter.start_date)
                elif table in ["benchmark_trends", "performance_baselines"]:
                    conditions.append("created_at >= ?")
                    params.append(filter.start_date)
                elif table == "system_info":
                    conditions.append(
                        "run_id IN (SELECT run_id FROM benchmark_runs WHERE timestamp_utc >= ?)"
                    )
                    params.append(filter.start_date)

            if filter.end_date:
                if table == "benchmark_runs":
                    conditions.append("timestamp_utc <= ?")
                    params.append(filter.end_date)
                elif table == "benchmark_results":
                    conditions.append(
                        "run_id IN (SELECT run_id FROM benchmark_runs WHERE timestamp_utc <= ?)"
                    )
                    params.append(filter.end_date)
                elif table in ["benchmark_trends", "performance_baselines"]:
                    conditions.append("created_at <= ?")
                    params.append(filter.end_date)
                elif table == "system_info":
                    conditions.append(
                        "run_id IN (SELECT run_id FROM benchmark_runs WHERE timestamp_utc <= ?)"
                    )
                    params.append(filter.end_date)

            # Model filter
            if filter.model_ids:
                placeholders = ",".join("?" * len(filter.model_ids))
                if table in ["benchmark_runs", "benchmark_results", "benchmark_trends", "performance_baselines"]:
                    conditions.append(f"model_id IN ({placeholders})")
                    params.extend(filter.model_ids)
                elif table == "system_info":
                    conditions.append(
                        f"run_id IN (SELECT run_id FROM benchmark_runs WHERE model_id IN ({placeholders}))"
                    )
                    params.extend(filter.model_ids)

            # Device filter
            if filter.devices:
                placeholders = ",".join("?" * len(filter.devices))
                if table in ["benchmark_runs", "benchmark_results", "benchmark_trends", "performance_baselines"]:
                    conditions.append(f"device IN ({placeholders})")
                    params.extend(filter.devices)
                elif table == "system_info":
                    conditions.append(
                        f"run_id IN (SELECT run_id FROM benchmark_runs WHERE device IN ({placeholders}))"
                    )
                    params.extend(filter.devices)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        return query, params

    def get_export_estimate(self, filter: ExportFilter | None = None) -> dict:
        """Estimate export size and row counts.

        Args:
            filter: Optional export filter

        Returns:
            Dictionary with estimates
        """
        conn = self._create_connection()
        try:
            tables = self._get_export_tables(filter)
            estimates = {
                "tables": {},
                "total_rows": 0,
                "estimated_csv_size_bytes": 0,
                "estimated_json_size_bytes": 0,
            }

            for table in tables:
                query, params = self._build_export_query(table, filter)
                count_query = query.replace("SELECT *", "SELECT COUNT(*)")

                try:
                    cursor = conn.execute(count_query, params)
                    count = cursor.fetchone()[0]
                except sqlite3.Error:
                    count = 0

                estimates["tables"][table] = {
                    "row_count": count,
                }
                estimates["total_rows"] += count

                # Rough size estimates (assuming ~200 bytes per row for CSV, ~300 for JSON)
                estimates["estimated_csv_size_bytes"] += count * 200
                estimates["estimated_json_size_bytes"] += count * 300

            return estimates
        finally:
            conn.close()
