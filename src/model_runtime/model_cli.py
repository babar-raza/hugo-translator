"""
Model Management CLI Commands.

Provides CLI interface for model acquisition, organization, and verification:
- models sync-registry: Generate Opus registry and discover cache models
- models download: Download models with various filters
- models verify: Validate downloaded models against manifest
- models discover: Discover local models across drives and folders
- models discover-report: View discovery run reports
- models show: Show detailed model info
- models select: Select best model for a language pair
- models doctor: Check registry health
"""
import argparse
import logging
import sys
from pathlib import Path

from .ct2_manager import CT2ConversionManager
from .model_store import ModelStore
from .registry import ModelRegistry

logger = logging.getLogger(__name__)


def cmd_sync_registry(args: argparse.Namespace) -> int:
    """
    Synchronize model registry by generating Opus entries and discovering cache models.

    Steps:
    1. Generate Opus registry from target languages
    2. Discover models from HuggingFace cache
    3. Merge registries (main + opus + cache)

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    import subprocess

    logger.info("=== Synchronizing Model Registry ===")

    # Step 1: Generate Opus registry
    logger.info("\n[1/2] Generating Opus model registry...")
    opus_cmd = [
        sys.executable,
        "-m",
        "scripts.generate_opus_registry",
        "--output",
        args.opus_output
    ]
    if args.check_online:
        opus_cmd.append("--check-online")

    try:
        subprocess.run(opus_cmd, check=True)
        logger.info(f"✓ Opus registry generated: {args.opus_output}")
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Opus registry generation failed: {e}")
        return 1

    # Step 2: Discover cache models
    logger.info("\n[2/2] Discovering models from HuggingFace cache...")
    cache_cmd = [
        sys.executable,
        "-m",
        "scripts.discover_hf_cache_models",
        "--output",
        args.cache_output
    ]

    try:
        subprocess.run(cache_cmd, check=True)
        logger.info(f"✓ Cache discovery complete: {args.cache_output}")
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Cache discovery failed: {e}")
        return 1

    # Step 3: Display registry summary
    logger.info("\n=== Registry Summary ===")
    logger.info("Main registry: config/model_registry.yaml")
    logger.info(f"Opus registry: {args.opus_output}")
    logger.info(f"Cache registry: {args.cache_output}")
    logger.info("\nTo use all registries, update your config to load:")
    logger.info(f"  registry_path: config/model_registry.yaml,{args.opus_output},{args.cache_output}"
                )

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """
    Download models with various filters.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model Download ===")

    # Load registry (support multiple paths)
    registry_paths = args.registry.split(",") if "," in args.registry else [args.registry]
    logger.info(f"Loading registry from: {registry_paths}")

    try:
        registry = ModelRegistry(registry_paths)
        logger.info(f"Loaded {len(registry.models)} models from registry")
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store with download permission
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=True  # Explicitly enabled for download command
    )

    # Determine what to download
    if args.all:
        # Download all models
        logger.info("Downloading ALL models...")
        language_filter = None
    elif args.languages:
        # Download models for specific languages
        language_filter = args.languages.split(",")
        logger.info(f"Downloading models for languages: {language_filter}")
    elif args.model_id:
        # Download specific model
        logger.info(f"Downloading model: {args.model_id}")
        try:
            path = store.ensure_model_downloaded(args.model_id)
            logger.info(f"✓ Model downloaded successfully: {path}")
            return 0
        except Exception as e:
            logger.error(f"✗ Download failed: {e}")
            return 1
    else:
        logger.error("Must specify --all, --model-id, or --languages")
        return 1

    # Download multiple models
    results = store.download_all_models(
        language_filter=language_filter,
        max_workers=args.parallel
    )

    # Report results
    success_count = sum(1 for success in results.values() if success)
    failure_count = len(results) - success_count

    logger.info("\n=== Download Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {failure_count}")

    if failure_count > 0:
        logger.warning("Some downloads failed. Check logs above for details.")

    return 0 if failure_count == 0 else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """
    Verify downloaded models against manifest.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model Verification ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get models to verify
    if args.all:
        models_to_verify = store.manifest.list_models()
        logger.info(f"Verifying {len(models_to_verify)} models from manifest...")
    elif args.model_id:
        models_to_verify = [args.model_id]
        logger.info(f"Verifying model: {args.model_id}")
    else:
        logger.error("Must specify --all or --model-id")
        return 1

    # Verify each model
    results = {}
    for model_id in models_to_verify:
        try:
            if model_id not in registry:
                logger.warning(f"? {model_id}: not in registry")
                results[model_id] = False
                continue

            verified = store.verify_model(model_id)
            results[model_id] = verified

            if verified:
                logger.info(f"✓ {model_id}: verified")
            else:
                logger.error(f"✗ {model_id}: verification failed")

        except Exception as e:
            logger.error(f"✗ {model_id}: {e}")
            results[model_id] = False

    # Summary
    verified_count = sum(1 for v in results.values() if v)
    failed_count = len(results) - verified_count

    logger.info("\n=== Verification Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Verified: {verified_count}")
    logger.info(f"Failed: {failed_count}")

    return 0 if failed_count == 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    """
    List models and their status.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model List ===")

    # Load registry including discovered models
    registry_paths = args.registry
    discovered = Path("config/model_registry.discovered.yaml")
    if discovered.exists():
        registry_paths = f"{registry_paths},{discovered}"

    try:
        registry = ModelRegistry(registry_paths)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Track which model_ids are discovered (start with disc_ prefix)
    discovered_ids: set[str] = set()
    if discovered.exists():
        try:
            disc_reg = ModelRegistry(str(discovered))
            discovered_ids = set(disc_reg.models.keys())
        except Exception:
            pass

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get download plan
    plan = store.get_download_plan()

    # Display status
    _safe_print(f"\n{'Model ID':<40} {'Source':<12} {'Status':<15} {'Size (MB)':<10} {'Backend':<12}")
    print("-" * 95)

    for model_info in sorted(registry.models.values(), key=lambda m: m.model_id):
        if model_info.model_id in plan["already_present"]:
            status = "Downloaded"
        elif model_info.local_path and model_info.local_path.exists():
            status = "Available"
        else:
            status = "Need Download"
        source = "discovered" if model_info.model_id in discovered_ids else "curated"
        size = model_info.model_size_mb
        backend = model_info.backend

        _safe_print(f"{model_info.model_id:<40} {source:<12} {status:<15} {size:<10} {backend:<12}")

    # Summary
    curated_count = len(registry.models) - len(discovered_ids & set(registry.models.keys()))
    disc_count = len(discovered_ids & set(registry.models.keys()))
    print("\n" + "=" * 95)
    _safe_print(f"Total Models: {len(registry.models)} (curated: {curated_count}, discovered: {disc_count})")
    _safe_print(f"Downloaded: {plan['already_present_count']}")
    _safe_print(f"Need Download: {plan['needs_download_count']} ({plan['total_size_mb']:.1f} MB)")

    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """
    Show download plan for models.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Download Plan ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get download plan
    plan = store.get_download_plan()

    # Display plan
    print("\nAlready Downloaded:")
    for model_id in sorted(plan["already_present"]):
        print(f"  ✓ {model_id}")

    print("\nNeed to Download:")
    for model_id in sorted(plan["needs_download"]):
        model_info = registry.get_model(model_id)
        print(f"  ⬇ {model_id} ({model_info.model_size_mb} MB)")

    print(f"\nTotal download size: {plan['total_size_mb']:.1f} MB")
    print("\nTo download all: python -m src.model_runtime.model_cli download --all")

    return 0


def cmd_convert_ct2(args: argparse.Namespace) -> int:
    """
    Convert models to CTranslate2 format.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== CT2 Conversion ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create CT2 manager
    manager = CT2ConversionManager(
        registry=registry,
        models_dir=Path(args.models_dir),
    )

    # Determine models to convert
    model_ids = []

    if args.model:
        model_ids = [args.model]
    elif args.all_multilingual:
        # Convert core multilingual models
        model_ids = ["m2m100_418m", "m2m100_1.2b", "nllb_distilled_600m", "small100"]
        logger.info(f"Converting multilingual models: {', '.join(model_ids)}")
    elif args.all_opus:
        # Convert Opus models
        opus_models = [m.model_id for m in registry.list_models() if m.backend == "opus"]
        model_ids = opus_models
        logger.info(f"Converting {len(opus_models)} Opus models")
    else:
        logger.error("Must specify --model, --all-multilingual, or --all-opus")
        return 1

    # Convert each model
    results = []
    for model_id in model_ids:
        logger.info(f"\nConverting {model_id}...")

        result = manager.ensure_ct2(
            model_id=model_id,
            quantization=args.quant,
            device_target="cpu" if args.quant == "int8" else "cuda",
            force=args.force,
        )

        results.append(result)

        if result.success:
            logger.info(f"✓ {model_id} -> {result.model_id} ({result.size_mb:.1f}MB)")
        else:
            logger.error(f"✗ {model_id}: {result.error}")

    # Summary
    success_count = sum(1 for r in results if r.success)
    failure_count = len(results) - success_count
    total_size_mb = sum(r.size_mb for r in results if r.success)

    logger.info("\n=== Conversion Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"Total size: {total_size_mb:.1f} MB")

    if failure_count > 0:
        logger.warning("Some conversions failed. Check logs above for details.")

    return 0 if failure_count == 0 else 1


def cmd_list_ct2(args: argparse.Namespace) -> int:
    """
    List CT2 models (existing and potential).

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== CT2 Models ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create CT2 manager
    manager = CT2ConversionManager(
        registry=registry,
        models_dir=Path(args.models_dir),
    )

    # Get CT2 models
    ct2_models = manager.list_ct2_models()

    # Group by status
    existing = [(m, p) for m, exists, p in ct2_models if exists]
    potential = [(m, p) for m, exists, p in ct2_models if not exists]

    # Display existing
    print(f"\n{'CT2 Model ID':<40} {'Status':<15} {'Path':<50}")
    print("-" * 110)

    if existing:
        print("\nExisting CT2 Models:")
        for model_id, path in sorted(existing):
            print(f"  ✓ {model_id:<38} {'Ready':<15} {path}")

    if args.show_potential and potential:
        print("\nPotential CT2 Conversions:")
        for model_id, path in sorted(potential):
            print(f"  ⬇ {model_id:<38} {'Not converted':<15} {path}")

    # Summary
    print("\n" + "=" * 110)
    print(f"Existing CT2 models: {len(existing)}")
    if args.show_potential:
        print(f"Potential conversions: {len(potential)}")

    if not existing and not potential:
        print("\nNo CT2 models found. Run 'convert-ct2' to create them.")
    elif not existing:
        print("\nNo CT2 models exist yet. Run 'convert-ct2 --all-multilingual' to get started.")

    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Discover local models across configured roots."""
    import os as _os
    from .discovery_report import DiscoveryReportManager
    from .local_discovery import LocalModelDiscovery, ScanRoot, get_default_scan_roots

    logger.info("=== Local Model Discovery ===")

    # Apply environment variable overrides
    env_registry = _os.environ.get("HUGO_TRANSLATOR_MODEL_REGISTRY_PATH", "")
    if env_registry.strip():
        args.output_registry = env_registry.strip()

    env_report_dir = _os.environ.get("HUGO_TRANSLATOR_MODEL_DISCOVERY_REPORT_DIR", "")
    if env_report_dir.strip():
        args.report_dir = env_report_dir.strip()

    env_full_drive = _os.environ.get("HUGO_TRANSLATOR_ENABLE_FULL_DRIVE_SCAN", "")
    enable_full_drive = env_full_drive.strip().lower() in ("true", "1", "yes")

    # Build scan roots
    scan_roots = get_default_scan_roots()

    # Add custom dirs from CLI
    if args.custom_dirs:
        for i, raw in enumerate(args.custom_dirs.split(";")):
            raw = raw.strip()
            if raw:
                scan_roots.append(ScanRoot(
                    path=Path(raw), label=f"custom_{i}", max_depth=args.max_depth,
                ))

    # Add drive scan roots from CLI or env
    drive_spec = args.include_drives or ""
    if enable_full_drive and not drive_spec:
        import string
        drive_spec = ",".join(
            f"{d}:" for d in string.ascii_uppercase if Path(f"{d}:/").exists()
        )
        logger.info(f"Full drive scan enabled via env: {drive_spec}")

    if drive_spec:
        for drive_letter in drive_spec.split(","):
            drive_letter = drive_letter.strip().rstrip(":/\\")
            if drive_letter:
                drive_root = Path(f"{drive_letter}:/")
                if drive_root.exists():
                    scan_roots.append(ScanRoot(
                        path=drive_root, label=f"drive_{drive_letter}",
                        max_depth=args.max_depth, scan_type="directory",
                    ))

    # Toggle HF cache / Ollama
    if args.no_hf_cache:
        scan_roots = [r for r in scan_roots if r.label != "hf_cache"]
    if args.no_ollama:
        scan_roots = [r for r in scan_roots if r.label != "ollama"]

    # Run discovery
    discovery = LocalModelDiscovery(scan_roots=scan_roots)
    report_mgr = DiscoveryReportManager(reports_dir=Path(args.report_dir))
    run_id = report_mgr.start_run(scan_roots)

    all_models = discovery.discover_all()

    # Record models
    for m in all_models:
        m.discovery_run_id = run_id
        report_mgr.record_model(run_id, m.to_dict())

    # Load existing registry IDs for new-model detection
    existing_ids: set[str] = set()
    try:
        reg = ModelRegistry(args.registry)
        existing_ids = set(reg.models.keys())
    except Exception:
        pass

    report = report_mgr.finish_run(
        run_id,
        skipped_roots=discovery.skipped_roots,
        errors=discovery.errors,
        existing_model_ids=existing_ids,
        total_before_dedup=len(all_models),
    )

    # Print summary
    _safe_print(f"\n{'='*60}")
    _safe_print(f"Discovery Run: {run_id}")
    _safe_print(f"{'='*60}")
    _safe_print(f"Models found:     {report.models_found}")
    _safe_print(f"New models:       {report.models_new}")
    _safe_print(f"Errors:           {len(report.errors)}")
    _safe_print(f"Skipped roots:    {len(report.skipped_roots)}")
    _safe_print(f"Duration:         {report.duration_seconds:.1f}s")

    if report.models_by_format:
        _safe_print(f"\nBy format:")
        for fmt, count in sorted(report.models_by_format.items()):
            _safe_print(f"  {fmt}: {count}")

    if report.models_by_backend:
        _safe_print(f"\nBy backend:")
        for bk, count in sorted(report.models_by_backend.items()):
            _safe_print(f"  {bk}: {count}")

    if report.errors:
        _safe_print(f"\nErrors:")
        for err in report.errors[:10]:
            _safe_print(f"  {err.get('path', '?')}: {err.get('message', err.get('error', '?'))}")

    # Print models table
    if all_models:
        _safe_print(f"\n{'Model ID':<40} {'Family':<12} {'Format':<14} {'Size':<10} {'Path'}")
        _safe_print("-" * 120)
        for m in sorted(all_models, key=lambda x: x.model_id):
            size = f"{m.size_bytes / (1024**2):.0f}MB" if m.size_bytes else "?"
            path_str = str(m.absolute_path)
            if len(path_str) > 50:
                path_str = "..." + path_str[-47:]
            _safe_print(f"  {m.model_id:<38} {m.model_family:<12} {m.model_format:<14} {size:<10} {path_str}")

    if args.dry_run:
        _safe_print(f"\n[DRY RUN] No report or registry files written.")
        return 0

    # Save report
    report_path = report_mgr.save_report(report)
    _safe_print(f"\nReport saved: {report_path}")

    # Export registry YAML
    output = Path(args.output_registry)
    count = report_mgr.export_as_registry_yaml(report, output, exclude_existing=existing_ids)
    _safe_print(f"Registry exported: {output} ({count} models)")

    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show detailed info for a specific model."""
    # Load registry including discovered
    registry_paths = args.registry
    discovered = Path("config/model_registry.discovered.yaml")
    if discovered.exists():
        registry_paths = f"{registry_paths},{discovered}"

    try:
        registry = ModelRegistry(registry_paths)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    if args.model_id not in registry:
        _safe_print(f"Model not found: {args.model_id}")
        _safe_print(f"\nAvailable models ({len(registry)} total):")
        for mid in sorted(registry.models.keys()):
            _safe_print(f"  {mid}")
        return 1

    model = registry.get_model(args.model_id)
    _safe_print(f"\n{'='*60}")
    _safe_print(f"Model: {model.model_id}")
    _safe_print(f"{'='*60}")
    for key, value in model.to_dict().items():
        if value is not None:
            _safe_print(f"  {key}: {value}")

    return 0


def _safe_print(text: str) -> None:
    """Print text with Unicode chars replaced for Windows console safety."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def cmd_select(args: argparse.Namespace) -> int:
    """Select best model for a language pair."""
    from .hardware import HardwareDetector
    from .selector import LanguageAwareModelSelector

    # Load registry including discovered
    registry_paths = args.registry
    discovered = Path("config/model_registry.discovered.yaml")
    if discovered.exists():
        registry_paths = f"{registry_paths},{discovered}"

    try:
        registry = ModelRegistry(registry_paths)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Detect hardware
    try:
        hardware = HardwareDetector().detect()
    except Exception:
        # Minimal fallback hardware info
        from .hardware import HardwareInfo
        hardware = HardwareInfo(
            cpu_count=4, total_ram_gb=16.0, has_cuda=False,
            recommended_device="cpu", platform="unknown",
        )

    selector = LanguageAwareModelSelector(
        registry=registry,
        hardware_info=hardware,
        fallback_model=None,
    )

    try:
        selection = selector.select_for_language_pair(
            args.source, args.target,
            prefer_quality=args.prefer_quality,
        )
    except ValueError as e:
        print(f"\nNo suitable model found for {args.source} -> {args.target}")
        _safe_print(f"  Reason: {e}")
        return 1

    _safe_print(f"\nSelected model for {args.source} -> {args.target}:")
    _safe_print(f"  Model ID:    {selection.model_info.model_id}")
    _safe_print(f"  Name:        {selection.model_info.name}")
    _safe_print(f"  Backend:     {selection.model_info.backend}")
    _safe_print(f"  Strategy:    {selection.selection_strategy}")
    _safe_print(f"  Rationale:   {selection.rationale}")
    _safe_print(f"  HW fit:      {selection.hardware_fit}")
    if selection.model_info.local_path:
        _safe_print(f"  Local path:  {selection.model_info.local_path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check registry health and report issues."""
    # Load registry including discovered
    registry_paths = args.registry
    discovered = Path("config/model_registry.discovered.yaml")
    if discovered.exists():
        registry_paths = f"{registry_paths},{discovered}"

    try:
        registry = ModelRegistry(registry_paths)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    _safe_print(f"\n{'='*60}")
    _safe_print(f"Model Registry Doctor")
    _safe_print(f"{'='*60}")
    _safe_print(f"Total models: {len(registry)}")

    issues = 0
    warnings = 0

    # Check each model
    for model in sorted(registry.models.values(), key=lambda m: m.model_id):
        model_issues: list[str] = []

        # Check local_path exists
        if model.local_path:
            if not model.local_path.exists():
                model_issues.append(f"path missing: {model.local_path}")
                issues += 1

        # Check backend requirements
        if model.backend == "ctranslate2":
            try:
                import ctranslate2  # noqa: F401
            except ImportError:
                model_issues.append("ctranslate2 package not installed")
                warnings += 1

        if model_issues:
            _safe_print(f"\n  {model.model_id}:")
            for issue in model_issues:
                _safe_print(f"    - {issue}")

    # Summary
    _safe_print(f"\n{'='*60}")
    if issues == 0 and warnings == 0:
        _safe_print("All models OK.")
    else:
        _safe_print(f"Issues: {issues}, Warnings: {warnings}")

    return 0 if issues == 0 else 1


def cmd_discover_report(args: argparse.Namespace) -> int:
    """View or export discovery run reports."""
    from .discovery_report import DiscoveryReportManager

    report_mgr = DiscoveryReportManager(reports_dir=Path(args.report_dir))

    if args.list_reports:
        reports = report_mgr.list_reports()
        if not reports:
            _safe_print("No discovery reports found.")
            return 0
        _safe_print(f"\n{'Run ID':<15} {'Timestamp':<28} {'Models':<10} {'Errors':<10}")
        _safe_print("-" * 70)
        for r in reports:
            _safe_print(f"  {r['run_id']:<13} {r['timestamp']:<28} {r['models_found']:<10} {r['errors']:<10}")
        return 0

    # Load specific or latest report
    report = None
    if args.run_id:
        report = report_mgr.load_report(args.run_id)
        if not report:
            _safe_print(f"Report not found: {args.run_id}")
            return 1
    elif args.latest:
        report = report_mgr.get_latest_report()
        if not report:
            _safe_print("No discovery reports found.")
            return 1
    else:
        _safe_print("Specify --list, --run-id, or --latest")
        return 1

    # Display report
    _safe_print(f"\n{'='*60}")
    _safe_print(f"Discovery Report: {report.run_id}")
    _safe_print(f"{'='*60}")
    _safe_print(f"Timestamp:   {report.timestamp}")
    _safe_print(f"Duration:    {report.duration_seconds:.1f}s")
    _safe_print(f"Models:      {report.models_found}")
    _safe_print(f"New models:  {report.models_new}")
    _safe_print(f"Errors:      {len(report.errors)}")

    if report.models_by_format:
        _safe_print(f"\nBy format: {report.models_by_format}")
    if report.models_by_backend:
        _safe_print(f"By backend: {report.models_by_backend}")

    if report.selection_recommendations:
        _safe_print(f"\nRecommendations:")
        for rec in report.selection_recommendations:
            _safe_print(f"  - {rec}")

    # Export if requested
    if args.export_yaml:
        output = Path(args.export_yaml)
        count = report_mgr.export_as_registry_yaml(report, output)
        _safe_print(f"\nExported {count} models to {output}")

    return 0


def main() -> int:
    """Main entry point for model CLI."""
    parser = argparse.ArgumentParser(
        description="Model Management CLI",
        prog="python -m src.model_runtime.model_cli"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # sync-registry command
    sync_parser = subparsers.add_parser(
        "sync-registry",
        help="Synchronize model registry (generate Opus + discover cache)"
    )
    sync_parser.add_argument(
        "--opus-output",
        default="config/model_registry.opus_autogen.yaml",
        help="Output path for Opus registry"
    )
    sync_parser.add_argument(
        "--cache-output",
        default="config/model_registry.local.yaml",
        help="Output path for cache discovery registry"
    )
    sync_parser.add_argument(
        "--check-online",
        action="store_true",
        help="Check HuggingFace Hub for Opus model availability"
    )

    # download command
    download_parser = subparsers.add_parser(
        "download",
        help="Download models"
    )
    download_parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models in registry"
    )
    download_parser.add_argument(
        "--model-id",
        help="Download specific model by ID"
    )
    download_parser.add_argument(
        "--languages",
        help="Download models for specific languages (comma-separated)"
    )
    download_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path (supports comma-separated list)"
    )
    download_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )
    download_parser.add_argument(
        "--parallel",
        type=int,
        default=3,
        help="Maximum parallel downloads"
    )

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify downloaded models against manifest"
    )
    verify_parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all downloaded models"
    )
    verify_parser.add_argument(
        "--model-id",
        help="Verify specific model by ID"
    )
    verify_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    verify_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List all models and their download status"
    )
    list_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    list_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # plan command
    plan_parser = subparsers.add_parser(
        "plan",
        help="Show download plan"
    )
    plan_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    plan_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # convert-ct2 command
    convert_ct2_parser = subparsers.add_parser(
        "convert-ct2",
        help="Convert models to CTranslate2 format"
    )
    convert_ct2_parser.add_argument(
        "--model",
        help="Model ID to convert (e.g., m2m100_418m)"
    )
    convert_ct2_parser.add_argument(
        "--all-multilingual",
        action="store_true",
        help="Convert all multilingual models (m2m100, nllb, small100)"
    )
    convert_ct2_parser.add_argument(
        "--all-opus",
        action="store_true",
        help="Convert all Opus models"
    )
    convert_ct2_parser.add_argument(
        "--quant",
        choices=["int8", "int16", "float16", "float32"],
        default="int8",
        help="Quantization type (default: int8 for CPU)"
    )
    convert_ct2_parser.add_argument(
        "--force",
        action="store_true",
        help="Force reconversion even if CT2 model exists"
    )
    convert_ct2_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    convert_ct2_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # list-ct2 command
    list_ct2_parser = subparsers.add_parser(
        "list-ct2",
        help="List CT2 models (existing and potential)"
    )
    list_ct2_parser.add_argument(
        "--show-potential",
        action="store_true",
        help="Show potential CT2 conversions (not yet converted)"
    )
    list_ct2_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    list_ct2_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # discover command
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover local models across drives and folders"
    )
    discover_parser.add_argument(
        "--custom-dirs",
        help="Additional directories to scan (semicolon-separated)"
    )
    discover_parser.add_argument(
        "--include-drives",
        help="Scan model directories on specified drives (e.g., D:,E:)"
    )
    discover_parser.add_argument(
        "--no-hf-cache",
        action="store_true",
        help="Exclude HuggingFace cache from scan"
    )
    discover_parser.add_argument(
        "--no-ollama",
        action="store_true",
        help="Exclude Ollama models from scan"
    )
    discover_parser.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="Max directory depth for scanning (default: 4)"
    )
    discover_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover but don't write report or registry files"
    )
    discover_parser.add_argument(
        "--output-registry",
        default="config/model_registry.discovered.yaml",
        help="Path for discovered models registry YAML"
    )
    discover_parser.add_argument(
        "--report-dir",
        default="data/discovery",
        help="Directory for discovery reports"
    )
    discover_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Existing registry path (for detecting new models)"
    )

    # discover-report command
    dr_parser = subparsers.add_parser(
        "discover-report",
        help="View or export discovery run reports"
    )
    dr_parser.add_argument(
        "--list",
        dest="list_reports",
        action="store_true",
        help="List all discovery reports"
    )
    dr_parser.add_argument(
        "--run-id",
        help="Show specific report by run ID"
    )
    dr_parser.add_argument(
        "--latest",
        action="store_true",
        help="Show latest discovery report"
    )
    dr_parser.add_argument(
        "--export-yaml",
        help="Export report to registry YAML at given path"
    )
    dr_parser.add_argument(
        "--report-dir",
        default="data/discovery",
        help="Directory for discovery reports"
    )

    # show command
    show_parser = subparsers.add_parser(
        "show",
        help="Show detailed info for a specific model"
    )
    show_parser.add_argument(
        "model_id",
        help="Model ID to show"
    )
    show_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )

    # select command
    select_parser = subparsers.add_parser(
        "select",
        help="Select best model for a language pair"
    )
    select_parser.add_argument(
        "--source",
        required=True,
        help="Source language code (e.g., en)"
    )
    select_parser.add_argument(
        "--target",
        required=True,
        help="Target language code (e.g., fr)"
    )
    select_parser.add_argument(
        "--prefer-quality",
        action="store_true",
        help="Prefer quality over speed"
    )
    select_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )

    # doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check registry health and report issues"
    )
    doctor_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    # Execute command
    commands = {
        "sync-registry": cmd_sync_registry,
        "download": cmd_download,
        "verify": cmd_verify,
        "list": cmd_list,
        "plan": cmd_plan,
        "convert-ct2": cmd_convert_ct2,
        "list-ct2": cmd_list_ct2,
        "discover": cmd_discover,
        "discover-report": cmd_discover_report,
        "show": cmd_show,
        "select": cmd_select,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
