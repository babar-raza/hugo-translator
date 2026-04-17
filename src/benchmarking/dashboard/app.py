"""Benchmark dashboard web application.

Provides web interface for visualizing benchmark results from SQLite database.

Phase 5.3 Migration:
    Supports optional SharedEngines for telemetry tracking.
    Falls back to standalone mode if engines not available.

    Note: Security hardening (authentication, HTTPS) is future work.
"""
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from flask import Flask, jsonify, render_template, request

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Database path
DB_PATH = Path("data/benchmarks/benchmarks.db")

# PHASE 5.3: Global reference to SharedEngines (if initialized)
_shared_engines: Optional["SharedEngines"] = None


def get_db():
    """Get database connection.

    Returns:
        SQLite connection with row_factory set to Row
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Benchmark database not found at {DB_PATH}. "
            "Run benchmarks first to create database."
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def dict_from_row(row: sqlite3.Row) -> dict:
    """Convert SQLite Row to dictionary.

    Args:
        row: SQLite Row object

    Returns:
        Dictionary representation
    """
    return {key: row[key] for key in row.keys()}


@app.route('/')
def index():
    """Dashboard home page with summary statistics."""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Summary statistics
        cursor.execute("SELECT COUNT(*) as total FROM benchmark_runs")
        total_runs = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(DISTINCT model_id) as count FROM benchmark_runs")
        total_models = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(DISTINCT device) as count FROM benchmark_runs")
        devices = cursor.fetchone()['count']

        # Latest run timestamp
        cursor.execute("SELECT MAX(timestamp) as latest FROM benchmark_runs")
        latest_run = cursor.fetchone()['latest']

        conn.close()

        return render_template('index.html',
            total_runs=total_runs,
            total_models=total_models,
            devices=devices,
            latest_run=latest_run
        )

    except FileNotFoundError as e:
        return render_template('error.html',
            error="Database not found",
            message=str(e)
        ), 404
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return render_template('error.html',
            error="Internal error",
            message="Failed to load dashboard"
        ), 500


@app.route('/api/summary')
def api_summary():
    """Get summary statistics.

    Returns:
        JSON with total runs, models, devices, coverage
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Basic counts
        cursor.execute("SELECT COUNT(*) as total FROM benchmark_runs")
        total_runs = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(DISTINCT model_id) as count FROM benchmark_runs")
        total_models = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(DISTINCT device) as count FROM benchmark_runs")
        total_devices = cursor.fetchone()['count']

        # Average throughput
        cursor.execute("""
            SELECT AVG(throughput_tokens_per_sec) as avg_throughput
            FROM benchmark_results
            WHERE throughput_tokens_per_sec IS NOT NULL
        """)
        avg_throughput = cursor.fetchone()['avg_throughput'] or 0

        conn.close()

        return jsonify({
            "total_runs": total_runs,
            "total_models": total_models,
            "total_devices": total_devices,
            "avg_throughput": round(avg_throughput, 2)
        })

    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/models')
def api_models():
    """Get all models with statistics.

    Returns:
        JSON array of models with run counts and performance metrics
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                r.model_id,
                r.device,
                COUNT(DISTINCT r.run_id) as run_count,
                AVG(br.throughput_tokens_per_sec) as avg_throughput,
                MAX(br.throughput_tokens_per_sec) as max_throughput,
                AVG(br.peak_memory_mb) as avg_memory,
                MAX(br.peak_memory_mb) as max_memory,
                AVG(br.total_time_seconds) as avg_time
            FROM benchmark_runs r
            LEFT JOIN benchmark_results br ON r.run_id = br.run_id
            GROUP BY r.model_id, r.device
            ORDER BY avg_throughput DESC
        """)

        results = [dict_from_row(row) for row in cursor.fetchall()]

        # Round floats
        for result in results:
            if result.get('avg_throughput'):
                result['avg_throughput'] = round(result['avg_throughput'], 2)
            if result.get('max_throughput'):
                result['max_throughput'] = round(result['max_throughput'], 2)
            if result.get('avg_memory'):
                result['avg_memory'] = round(result['avg_memory'], 1)
            if result.get('max_memory'):
                result['max_memory'] = round(result['max_memory'], 1)
            if result.get('avg_time'):
                result['avg_time'] = round(result['avg_time'], 3)

        conn.close()

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error getting models: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/recent_runs')
def api_recent_runs():
    """Get recent benchmark runs.

    Query params:
        limit: Number of runs to return (default: 10, max: 100)

    Returns:
        JSON array of recent runs
    """
    try:
        limit = min(int(request.args.get('limit', 10)), 100)

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT
                r.run_id,
                r.model_id,
                r.device,
                r.timestamp,
                r.batch_size,
                COUNT(br.sample_id) as sample_count,
                AVG(br.throughput_tokens_per_sec) as avg_throughput
            FROM benchmark_runs r
            LEFT JOIN benchmark_results br ON r.run_id = br.run_id
            GROUP BY r.run_id
            ORDER BY r.timestamp DESC
            LIMIT {limit}
        """)

        results = [dict_from_row(row) for row in cursor.fetchall()]

        # Round floats and format timestamps
        for result in results:
            if result.get('avg_throughput'):
                result['avg_throughput'] = round(result['avg_throughput'], 2)
            if result.get('timestamp'):
                # Format timestamp for display
                result['timestamp_display'] = result['timestamp'][:19]  # Remove microseconds

        conn.close()

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error getting recent runs: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/models')
def models():
    """Model comparison page."""
    return render_template('models.html')


@app.route('/languages')
def languages():
    """Language coverage page."""
    return render_template('languages.html')


@app.route('/comparison')
def comparison():
    """GPU vs CPU comparison page."""
    return render_template('comparison.html')


@app.route('/cache')
def cache():
    """Cache effectiveness dashboard page."""
    return render_template('cache.html')


@app.route('/runs')
def runs():
    """Benchmark runs explorer page."""
    return render_template('runs.html')


@app.route('/runs/<run_id>')
def run_detail(run_id):
    """Benchmark run detail page."""
    return render_template('run_detail.html', run_id=run_id)


@app.route('/api/coverage_matrix')
def api_coverage_matrix():
    """Get language-model coverage matrix.

    Returns:
        JSON object with coverage data:
        {
            "languages": ["ar", "bg", "ca", ...],
            "models": ["model1", "model2", ...],
            "matrix": [[run_count, avg_throughput], ...],
            "metadata": {
                "total_languages": 36,
                "languages_covered": N,
                "total_models": M
            }
        }
    """
    try:
        # Define all 36 target languages
        all_languages = [
            "ar", "bg", "ca", "cs", "da", "de", "el", "es",
            "fa", "fi", "fr", "he", "hi", "hr", "hu", "id",
            "it", "ja", "ko", "lt", "lv", "ms", "nl", "no",
            "pl", "pt", "ro", "ru", "sk", "sr", "sv", "th",
            "tr", "uk", "vi", "zh"
        ]

        conn = get_db()
        cursor = conn.cursor()

        # Get all distinct models
        cursor.execute("""
            SELECT DISTINCT model_id
            FROM benchmark_runs
            ORDER BY model_id
        """)
        models = [row[0] for row in cursor.fetchall()]

        # For each model, get run statistics
        # Note: Current schema doesn't track target language explicitly
        # This will be enhanced when language tracking is added
        matrix = []
        for lang in all_languages:
            row = []
            for model in models:
                # Query for runs matching this model
                # In future: add WHERE target_lang = ?
                cursor.execute("""
                    SELECT
                        COUNT(DISTINCT r.run_id) as run_count,
                        AVG(br.throughput_tokens_per_sec) as avg_throughput
                    FROM benchmark_runs r
                    LEFT JOIN benchmark_results br ON r.run_id = br.run_id
                    WHERE r.model_id = ?
                    GROUP BY r.model_id
                """, (model,))

                result = cursor.fetchone()
                if result:
                    run_count = result[0] or 0
                    avg_throughput = result[1] or 0
                    row.append({
                        "run_count": run_count,
                        "avg_throughput": round(avg_throughput, 2) if avg_throughput else 0
                    })
                else:
                    row.append({"run_count": 0, "avg_throughput": 0})

            matrix.append(row)

        # Calculate coverage metadata
        languages_covered = sum(1 for row in matrix if any(cell["run_count"] > 0 for cell in row))
        total_cells = len(all_languages) * len(models)
        covered_cells = sum(1 for row in matrix for cell in row if cell["run_count"] > 0)
        coverage_percentage = (covered_cells / total_cells * 100) if total_cells > 0 else 0

        conn.close()

        return jsonify({
            "languages": all_languages,
            "models": models,
            "matrix": matrix,
            "metadata": {
                "total_languages": len(all_languages),
                "languages_covered": languages_covered,
                "total_models": len(models),
                "total_cells": total_cells,
                "covered_cells": covered_cells,
                "coverage_percentage": round(coverage_percentage, 1)
            }
        })

    except Exception as e:
        logger.error(f"Error getting coverage matrix: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/gpu_cpu_comparison')
def api_gpu_cpu_comparison():
    """Get GPU vs CPU comparison data.

    Returns:
        JSON object with comparison data for models tested on both devices:
        {
            "models": [
                {
                    "model_id": "...",
                    "cpu": {"throughput": ..., "memory": ..., "time": ...},
                    "gpu": {"throughput": ..., "memory": ..., "time": ...},
                    "speedup": GPU_TPS / CPU_TPS,
                    "memory_ratio": GPU_MEM / CPU_MEM
                }
            ],
            "summary": {
                "total_models": N,
                "avg_speedup": X.XX,
                "max_speedup": Y.YY
            }
        }
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get models tested on both CPU and GPU
        cursor.execute("""
            SELECT DISTINCT model_id
            FROM benchmark_runs
            WHERE model_id IN (
                SELECT model_id FROM benchmark_runs WHERE device = 'cpu'
            )
            AND model_id IN (
                SELECT model_id FROM benchmark_runs WHERE device = 'cuda'
                UNION
                SELECT model_id FROM benchmark_runs WHERE device = 'gpu'
            )
            ORDER BY model_id
        """)

        models = []
        speedups = []

        for row in cursor.fetchall():
            model_id = row[0]

            # Get CPU stats
            cursor.execute("""
                SELECT
                    AVG(br.throughput_tokens_per_sec) as avg_throughput,
                    AVG(br.peak_memory_mb) as avg_memory,
                    AVG(br.translation_time_sec) as avg_time,
                    COUNT(DISTINCT r.run_id) as run_count
                FROM benchmark_runs r
                LEFT JOIN benchmark_results br ON r.run_id = br.run_id
                WHERE r.model_id = ? AND r.device = 'cpu'
            """, (model_id,))

            cpu_result = cursor.fetchone()
            cpu_throughput = cpu_result[0] or 0
            cpu_memory = cpu_result[1] or 0
            cpu_time = cpu_result[2] or 0
            cpu_runs = cpu_result[3] or 0

            # Get GPU stats (try both 'cuda' and 'gpu')
            cursor.execute("""
                SELECT
                    AVG(br.throughput_tokens_per_sec) as avg_throughput,
                    AVG(br.peak_memory_mb) as avg_memory,
                    AVG(br.translation_time_sec) as avg_time,
                    COUNT(DISTINCT r.run_id) as run_count
                FROM benchmark_runs r
                LEFT JOIN benchmark_results br ON r.run_id = br.run_id
                WHERE r.model_id = ? AND r.device IN ('cuda', 'gpu')
            """, (model_id,))

            gpu_result = cursor.fetchone()
            gpu_throughput = gpu_result[0] or 0
            gpu_memory = gpu_result[1] or 0
            gpu_time = gpu_result[2] or 0
            gpu_runs = gpu_result[3] or 0

            # Calculate speedup
            speedup = (gpu_throughput / cpu_throughput) if cpu_throughput > 0 else 0
            memory_ratio = (gpu_memory / cpu_memory) if cpu_memory > 0 else 0

            if speedup > 0:
                speedups.append(speedup)

            models.append({
                "model_id": model_id,
                "cpu": {
                    "throughput": round(cpu_throughput, 2),
                    "memory": round(cpu_memory, 2),
                    "time": round(cpu_time, 2),
                    "runs": cpu_runs
                },
                "gpu": {
                    "throughput": round(gpu_throughput, 2),
                    "memory": round(gpu_memory, 2),
                    "time": round(gpu_time, 2),
                    "runs": gpu_runs
                },
                "speedup": round(speedup, 2),
                "memory_ratio": round(memory_ratio, 2)
            })

        # Calculate summary statistics
        avg_speedup = sum(speedups) / len(speedups) if speedups else 0
        max_speedup = max(speedups) if speedups else 0

        conn.close()

        return jsonify({
            "models": models,
            "summary": {
                "total_models": len(models),
                "avg_speedup": round(avg_speedup, 2),
                "max_speedup": round(max_speedup, 2),
                "models_with_5x_speedup": sum(1 for s in speedups if s >= 5.0)
            }
        })

    except Exception as e:
        logger.error(f"Error getting GPU/CPU comparison: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/cache_stats')
def api_cache_stats():
    """Get cache effectiveness statistics.

    Returns:
        JSON object with cache statistics (placeholder for now):
        {
            "overall": {"hit_rate": ..., "speedup": ...},
            "by_level": {"L1": {...}, "L2": {...}, "L3": {...}},
            "time_series": [...],
            "recommendations": [...]
        }
    """
    # This is a placeholder implementation
    # Real cache stats will be available once cache tracking is implemented
    return jsonify({
        "status": "not_implemented",
        "message": "Cache tracking infrastructure not yet implemented. This will be available after BM-CACHE-01 is complete.",
        "placeholder_data": {
            "overall": {
                "hit_rate": 0,
                "total_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0
            },
            "by_level": {
                "L1": {"hit_rate": 0, "memory_mb": 0},
                "L2": {"hit_rate": 0, "memory_mb": 0},
                "L3": {"hit_rate": 0, "memory_mb": 0}
            }
        }
    })


@app.route('/api/runs')
def api_runs():
    """Get list of benchmark runs with pagination and filtering.

    Query params:
        limit: Number of runs per page (default: 50, max: 100)
        offset: Number of runs to skip (default: 0)
        model: Filter by model_id (optional)
        device: Filter by device (optional)
        date_from: Filter by start date YYYY-MM-DD (optional)
        date_to: Filter by end date YYYY-MM-DD (optional)

    Returns:
        JSON object with runs list and pagination info
    """
    try:
        # Parse query parameters
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = int(request.args.get('offset', 0))
        model_filter = request.args.get('model')
        device_filter = request.args.get('device')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')

        conn = get_db()
        cursor = conn.cursor()

        # Build query with filters
        where_clauses = []
        params = []

        if model_filter:
            where_clauses.append("r.model_id LIKE ?")
            params.append(f"%{model_filter}%")

        if device_filter:
            where_clauses.append("r.device = ?")
            params.append(device_filter)

        if date_from:
            where_clauses.append("r.timestamp >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("r.timestamp <= ?")
            params.append(date_to)

        where_sql = " AND " + " AND ".join(where_clauses) if where_clauses else ""

        # Get total count
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM benchmark_runs r
            WHERE 1=1{where_sql}
        """, params)
        total_count = cursor.fetchone()[0]

        # Get paginated results
        cursor.execute(f"""
            SELECT
                r.run_id,
                r.model_id,
                r.device,
                r.timestamp,
                r.batch_size,
                COUNT(br.sample_id) as sample_count,
                AVG(br.throughput_tokens_per_sec) as avg_throughput,
                AVG(br.peak_memory_mb) as avg_memory,
                SUM(br.translation_time_sec) as total_time
            FROM benchmark_runs r
            LEFT JOIN benchmark_results br ON r.run_id = br.run_id
            WHERE 1=1{where_sql}
            GROUP BY r.run_id
            ORDER BY r.timestamp DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset])

        runs = []
        for row in cursor.fetchall():
            run_dict = dict_from_row(row)
            # Round floats
            if run_dict.get('avg_throughput'):
                run_dict['avg_throughput'] = round(run_dict['avg_throughput'], 2)
            if run_dict.get('avg_memory'):
                run_dict['avg_memory'] = round(run_dict['avg_memory'], 2)
            if run_dict.get('total_time'):
                run_dict['total_time'] = round(run_dict['total_time'], 2)

            runs.append(run_dict)

        conn.close()

        return jsonify({
            "runs": runs,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        })

    except Exception as e:
        logger.error(f"Error getting runs list: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/runs/<run_id>')
def api_run_detail(run_id):
    """Get detailed information about a specific run.

    Args:
        run_id: The run ID

    Returns:
        JSON object with run details and all sample results
    """
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get run metadata
        cursor.execute("""
            SELECT *
            FROM benchmark_runs
            WHERE run_id = ?
        """, (run_id,))

        run = cursor.fetchone()
        if not run:
            conn.close()
            return jsonify({"error": "Run not found"}), 404

        run_dict = dict_from_row(run)

        # Get all sample results
        cursor.execute("""
            SELECT *
            FROM benchmark_results
            WHERE run_id = ?
            ORDER BY sample_id
        """, (run_id,))

        results = [dict_from_row(row) for row in cursor.fetchall()]

        # Calculate statistics
        if results:
            throughputs = [r.get('throughput_tokens_per_sec', 0) for r in results if r.get('throughput_tokens_per_sec')]
            memories = [r.get('peak_memory_mb', 0) for r in results if r.get('peak_memory_mb')]

            stats = {
                "sample_count": len(results),
                "avg_throughput": round(sum(throughputs) / len(throughputs), 2) if throughputs else 0,
                "min_throughput": round(min(throughputs), 2) if throughputs else 0,
                "max_throughput": round(max(throughputs), 2) if throughputs else 0,
                "avg_memory": round(sum(memories) / len(memories), 2) if memories else 0,
                "max_memory": round(max(memories), 2) if memories else 0
            }
        else:
            stats = {}

        conn.close()

        return jsonify({
            "run": run_dict,
            "results": results,
            "statistics": stats
        })

    except Exception as e:
        logger.error(f"Error getting run detail: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint.

    Returns:
        JSON with status and database connectivity
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM benchmark_runs")
        count = cursor.fetchone()[0]
        conn.close()

        return jsonify({
            "status": "healthy",
            "database": "connected",
            "total_runs": count
        })

    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        }), 500


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return render_template('error.html',
        error="Page not found",
        message="The requested page does not exist"
    ), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal error: {error}")
    return render_template('error.html',
        error="Internal server error",
        message="An unexpected error occurred"
    ), 500


def init_dashboard(engines: Optional["SharedEngines"] = None):
    """Initialize dashboard with optional SharedEngines support.

    Args:
        engines: Optional SharedEngines for telemetry (Phase 5.3)
    """
    global _shared_engines
    _shared_engines = engines

    # PHASE 5.3: Emit dashboard startup event if using SharedEngines
    if _shared_engines:
        try:
            _shared_engines.telemetry.track_event(
                event_type="benchmark_dashboard_started",
                mode="shared_engines",
                db_path=str(DB_PATH)
            )
            logger.info("Dashboard initialized with SharedEngines telemetry support")
        except Exception as e:
            logger.debug(f"Telemetry event failed (non-fatal): {e}")
    else:
        logger.info("Dashboard initialized in standalone mode (no telemetry)")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # PHASE 5.3: Optionally initialize SharedEngines
    use_shared_engines = os.getenv("USE_SHARED_ENGINES", "false").lower() in ("true", "1", "yes")
    shared_engines = None

    if use_shared_engines:
        logger.info("SharedEngines enabled via USE_SHARED_ENGINES environment variable")
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from src.shared_engines.composition_root import CompositionRoot

            # Create minimal engines configuration for telemetry
            engines_config = {
                "config_root": "./config",
                "log_level": "INFO",
                "telemetry_enabled": True,
            }

            shared_engines = CompositionRoot.create_from_config(engines_config)
            logger.info("SharedEngines created successfully for telemetry tracking")

        except Exception as e:
            logger.warning(f"Failed to create SharedEngines: {e}")
            logger.info("Continuing in standalone mode (no telemetry)")
            shared_engines = None

    # Initialize dashboard
    init_dashboard(engines=shared_engines)

    # TODO: Future security hardening (authentication, HTTPS, rate limiting)
    # See Phase 5.3 migration notes for details
    print("Starting benchmark dashboard...")
    print("Open http://localhost:8080 in your browser")
    print("Press Ctrl+C to stop")
    if shared_engines:
        print("Telemetry: ENABLED")
    print("")
    print("⚠️  WARNING: This dashboard is NOT production-ready.")
    print("   Security hardening (auth, HTTPS) is planned for future work.")

    # Use environment variable to control debug mode (disabled in production)
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=8080, debug=debug_mode)
