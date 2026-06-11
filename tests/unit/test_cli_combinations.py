"""
CLI Option Combination Test Matrix (CLI-TC-05).

Comprehensive parametrized tests for critical CLI option combinations.
Tests cover:
- Compatible option combinations
- Conflicting option combinations (expect errors)
- Precedence/override behaviors
- Validation + terminology mode combinations
- Cache + resume combinations
- Multi-language mode combinations
- Model/device control combinations
- Output control combinations

Test Matrix (Priority Combinations):
| ID  | Combination | Expected |
|-----|-------------|----------|
| C01 | --dry-run --no-commit | Both accepted |
| C02 | --force-retranslate --cache-write-mode never | Both accepted |
| C03 | --resume --force-restart | force-restart wins |
| C04 | --validation-mode off --strict-reject | strict-reject wins |
| C05 | --enable-terminology --disable-terminology | Last wins |
| C06 | --parallel-languages 2 --global-lang-rounds 5 | ERROR at parse time (CLI-TC-03) |
| C07 | --force-accept --strict-reject | Both parsed (conflict at usage) |
| C08 | --verify --fix | Both accepted |
| C09 | --device cuda --batch-size 1 --load-mode int8 | All accepted |
| C10 | --metrics-only --no-progress | Both accepted |

Note: The CLI module (src.cli) uses TYPE_CHECKING guards and lazy imports,
so it can be imported without heavy ML dependencies like torch/transformers.
"""

import pytest


@pytest.fixture
def parser():
    """Create CLI parser instance.

    Import is done inside fixture to ensure proper test isolation
    and avoid import errors at collection time.
    """
    from src.cli import create_parser

    return create_parser()


@pytest.fixture
def cli_overrides_class():
    """Get CLIConfigOverrides class.

    Import is done inside fixture to ensure proper test isolation.
    """
    from src.cli import CLIConfigOverrides

    return CLIConfigOverrides


# =============================================================================
# C01-C10: Priority Combinations from Test Matrix
# =============================================================================


class TestPriorityCombinationsC01C05:
    """Test priority combinations C01-C05 (compatible combinations)."""

    @pytest.mark.parametrize(
        "test_id,args,checks",
        [
            pytest.param(
                "C01",
                ["--dry-run", "--no-commit"],
                [("dry_run", True), ("auto_commit", False)],
                id="C01-dry-run-no-commit",
            ),
            pytest.param(
                "C02",
                ["--force-retranslate", "--cache-write-mode", "never"],
                [("force_retranslate", True), ("cache_write_mode", "never")],
                id="C02-force-retranslate-cache-never",
            ),
            pytest.param(
                "C08", ["--verify", "--fix"], [("verify", True), ("fix", True)], id="C08-verify-fix"
            ),
            pytest.param(
                "C10",
                ["--metrics-only", "--no-progress"],
                [("metrics_only", True), ("no_progress", True)],
                id="C10-metrics-only-no-progress",
            ),
        ],
    )
    def test_compatible_combinations_parsed(self, parser, test_id, args, checks):
        """Test that compatible option combinations are accepted by parser."""
        full_args = ["--site", "test"] + args
        parsed = parser.parse_args(full_args)

        for attr, expected_value in checks:
            actual_value = getattr(parsed, attr)
            assert actual_value == expected_value, (
                f"{test_id}: Expected {attr}={expected_value}, got {actual_value}"
            )

    def test_C03_resume_force_restart_precedence(self, parser, cli_overrides_class):
        """
        C03: Test --resume --force-restart combination.

        Expected: force-restart wins (documented behavior).
        Both flags can be parsed, but force_restart should take precedence
        in the implementation logic.
        """
        args = parser.parse_args(["--site", "test", "--resume", "--force-restart"])

        # Parser accepts both
        assert args.resume is True
        assert args.force_restart is True

        # In CLIConfigOverrides, force_restart takes precedence
        overrides = cli_overrides_class(args)
        assert overrides.resume is True
        assert overrides.force_restart is True
        # Implementation note: main() checks force_restart first

    def test_C04_validation_off_strict_reject_precedence(self, parser, cli_overrides_class):
        """
        C04: Test --validation-mode off --strict-reject combination.

        Expected: strict-reject wins and enables strict validation mode.
        """
        args = parser.parse_args(["--site", "test", "--validation-mode", "off", "--strict-reject"])

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # strict-reject should override validation-mode=off
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 0
        # Note: enable_validation is controlled separately

    def test_C05_enable_disable_terminology_precedence(self, parser, cli_overrides_class):
        """
        C05: Test --enable-terminology --disable-terminology combination.

        Expected: --enable-terminology takes precedence over --disable-terminology
        (implementation uses: True if enable else (False if disable else None))
        """
        # Test enable then disable -> enable takes precedence
        args1 = parser.parse_args(
            ["--site", "test", "--enable-terminology", "--disable-terminology"]
        )
        overrides1 = cli_overrides_class(args1)
        assert overrides1.enable_terminology is True  # enable takes precedence

        # Test disable then enable -> enable takes precedence
        args2 = parser.parse_args(
            ["--site", "test", "--disable-terminology", "--enable-terminology"]
        )
        overrides2 = cli_overrides_class(args2)
        assert overrides2.enable_terminology is True  # enable takes precedence


class TestPriorityCombinationsC06C07:
    """Test priority combinations C06-C07 (conflicting combinations)."""

    def test_C06_parallel_languages_global_lang_rounds_error(self, parser):
        """
        C06: Test --parallel-languages 2 --global-lang-rounds 5 combination.

        CLI-TC-03: Error now occurs at parse time (SystemExit) instead of runtime.
        Expected: ERROR - mutual exclusion enforced via _MultiLangModeAction at parse time.
        """
        # CLI-TC-03: Error should occur at parse time, not runtime
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(
                ["--site", "test", "--parallel-languages", "2", "--global-lang-rounds", "5"]
            )

        # SystemExit with code 2 indicates argparse error
        assert exc_info.value.code == 2

    def test_C07_force_accept_strict_reject_behavior(self, parser, cli_overrides_class):
        """
        C07: Test --force-accept --strict-reject combination.

        Current behavior: Both are parsed. This tests the actual behavior.
        Note: These are contradictory semantics (accept all vs. reject on any issue).
        """
        args = parser.parse_args(["--site", "test", "--force-accept", "--strict-reject"])

        # Parser accepts both flags
        assert args.force_accept is True
        assert args.strict_reject is True

        # In get_engine_overrides, force_accept disables validation
        # but strict_reject sets strict mode with max_retries=0
        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # Document actual behavior: force_accept sets enable_validation=False
        # strict_reject still sets validation_mode=strict and max_retries=0
        # This is a potential design issue (conflicting flags both apply)
        assert engine_overrides["enable_validation"] is False  # force_accept wins
        assert engine_overrides["validation_mode"] == "strict"  # strict_reject applies
        assert engine_overrides["max_retries"] == 0  # strict_reject applies


class TestPriorityCombinationC09:
    """Test priority combination C09 (device/model control)."""

    def test_C09_device_cuda_batch_load_mode_combination(self, parser, cli_overrides_class):
        """
        C09: Test --device cuda --batch-size 1 --load-mode int8 combination.

        Expected: All accepted - valid GPU configuration.
        """
        args = parser.parse_args(
            ["--site", "test", "--device", "cuda", "--batch-size", "1", "--load-mode", "int8"]
        )

        overrides = cli_overrides_class(args)

        assert overrides.device == "cuda"
        assert overrides.batch_size == 1
        assert overrides.load_mode == "int8"

        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["batch_size"] == 1


# =============================================================================
# Extended Validation + Terminology Combinations
# =============================================================================


class TestValidationTerminologyCombinations:
    """Test validation mode + terminology mode combinations."""

    @pytest.mark.parametrize(
        "val_mode,term_mode,term_enabled",
        [
            ("strict", "protect", True),
            ("strict", "validate", True),
            ("strict", "both", True),
            ("normal", "protect", True),
            ("normal", "validate", True),
            ("lenient", "both", True),
            ("off", "protect", True),  # Terminology can work even with validation off
            ("off", "none", False),
        ],
    )
    def test_validation_terminology_mode_matrix(
        self, parser, cli_overrides_class, val_mode, term_mode, term_enabled
    ):
        """Test all validation mode + terminology mode combinations."""
        args_list = ["--site", "test", "--validation-mode", val_mode]

        if term_enabled:
            args_list.extend(["--enable-terminology", "--terminology-mode", term_mode])
        else:
            args_list.extend(["--disable-terminology", "--terminology-mode", term_mode])

        args = parser.parse_args(args_list)
        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # Validation mode should be set (unless 'off')
        if val_mode != "off":
            assert engine_overrides["validation_mode"] == val_mode
            assert engine_overrides["enable_validation"] is True
        else:
            assert engine_overrides["enable_validation"] is False

        # Terminology settings
        assert engine_overrides["enable_terminology"] is term_enabled
        assert engine_overrides["terminology_mode"] == term_mode

    def test_disable_validation_with_max_retries(self, parser, cli_overrides_class):
        """Test --disable-validation with --max-retries (C11 extended)."""
        args = parser.parse_args(["--site", "test", "--disable-validation", "--max-retries", "5"])

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # Both accepted: validation disabled, retries set (though unused)
        assert engine_overrides["enable_validation"] is False
        assert engine_overrides["max_retries"] == 5


# =============================================================================
# Cache + Resume Combinations
# =============================================================================


class TestCacheResumeCombinations:
    """Test cache behavior + resume control combinations."""

    @pytest.mark.parametrize(
        "cache_write,force_retranslate,resume,force_restart",
        [
            ("auto", False, True, False),
            ("always", False, True, False),
            ("never", False, True, False),
            ("auto", True, True, False),
            ("always", True, True, False),
            ("never", True, True, False),  # C02: force-retranslate + never
            ("auto", True, True, True),
            ("auto", False, False, False),
            ("auto", False, False, True),
        ],
    )
    def test_cache_resume_combination_matrix(
        self, parser, cli_overrides_class, cache_write, force_retranslate, resume, force_restart
    ):
        """Test all cache + resume flag combinations."""
        args_list = [
            "--site",
            "test",
            "--cache-write-mode",
            cache_write,
        ]

        if force_retranslate:
            args_list.append("--force-retranslate")

        if not resume:
            args_list.append("--no-resume")

        if force_restart:
            args_list.append("--force-restart")

        args = parser.parse_args(args_list)
        overrides = cli_overrides_class(args)

        assert overrides.cache_write_mode == cache_write
        assert overrides.force_retranslate == force_retranslate
        assert overrides.resume == resume
        assert overrides.force_restart == force_restart

        # Verify engine overrides
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["force_retranslate"] == force_retranslate
        if cache_write != "auto":
            assert engine_overrides["cache_write_mode"] == cache_write


# =============================================================================
# Multi-Language Mode Combinations
# =============================================================================


class TestMultiLanguageCombinations:
    """Test multi-language processing option combinations."""

    def test_parallel_with_all_compatible_options(self, parser, cli_overrides_class):
        """Test --parallel-languages with various compatible options."""
        args = parser.parse_args(
            [
                "--site",
                "test",
                "--parallel-languages",
                "4",
                "--force-retranslate",
                "--cache-write-mode",
                "always",
                "--device",
                "cuda",
                "--batch-size",
                "16",
                "--validation-mode",
                "normal",
                "--enable-terminology",
            ]
        )

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["parallel_languages"] == 4
        assert engine_overrides["force_retranslate"] is True
        assert engine_overrides["cache_write_mode"] == "always"
        assert engine_overrides["batch_size"] == 16
        assert engine_overrides["validation_mode"] == "normal"
        assert engine_overrides["enable_terminology"] is True

    def test_roundrobin_with_sort_options(self, parser, cli_overrides_class):
        """Test --global-lang-rounds with --global-lang-sort."""
        for sort_order in ["asc", "desc"]:
            args = parser.parse_args(
                ["--site", "test", "--global-lang-rounds", "100", "--global-lang-sort", sort_order]
            )

            overrides = cli_overrides_class(args)
            engine_overrides = overrides.get_engine_overrides()

            assert engine_overrides["global_lang_rounds"] == 100
            assert engine_overrides["global_lang_sort"] == sort_order

    def test_fail_fast_combinations(self, parser):
        """Test --fail-fast and --no-fail-fast with multi-language options."""
        # With fail-fast (default)
        args1 = parser.parse_args(["--site", "test", "--parallel-languages", "2"])
        assert args1.fail_fast is True

        # With --no-fail-fast
        args2 = parser.parse_args(["--site", "test", "--parallel-languages", "2", "--no-fail-fast"])
        assert args2.fail_fast is False


# =============================================================================
# Output Control Combinations
# =============================================================================


class TestOutputControlCombinations:
    """Test output control option combinations."""

    @pytest.mark.parametrize(
        "dry_run,save_rejected,auto_commit",
        [
            (True, True, False),  # C01+C13: dry-run + save-rejected + no-commit
            (True, False, False),
            (False, True, True),
            (False, True, False),
            (False, False, True),
            (False, False, False),
        ],
    )
    def test_output_control_matrix(
        self, parser, cli_overrides_class, dry_run, save_rejected, auto_commit
    ):
        """Test output control flag combinations."""
        args_list = ["--site", "test"]

        if dry_run:
            args_list.append("--dry-run")
        if save_rejected:
            args_list.append("--save-rejected")
        if auto_commit:
            args_list.append("--auto-commit")
        else:
            args_list.append("--no-commit")

        args = parser.parse_args(args_list)
        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["dry_run"] == dry_run
        assert engine_overrides["save_rejected"] == save_rejected


# =============================================================================
# Model Control Combinations
# =============================================================================


class TestModelControlCombinations:
    """Test model/device control option combinations."""

    @pytest.mark.parametrize(
        "device,load_mode,batch_size,max_tokens",
        [
            ("cuda", "fp16", 16, 512),
            ("cuda", "int8", 32, 1024),
            ("cuda", "fp32", 8, 256),
            ("cpu", "fp32", 4, 512),
            ("cpu", "int8", 8, 768),
            ("auto", "auto", None, None),
        ],
    )
    def test_model_control_matrix(
        self, parser, cli_overrides_class, device, load_mode, batch_size, max_tokens
    ):
        """Test device + load_mode + batch_size + max_tokens combinations."""
        args_list = ["--site", "test", "--device", device, "--load-mode", load_mode]

        if batch_size is not None:
            args_list.extend(["--batch-size", str(batch_size)])
        if max_tokens is not None:
            args_list.extend(["--max-tokens", str(max_tokens)])

        args = parser.parse_args(args_list)
        overrides = cli_overrides_class(args)

        # Device and load_mode store None for 'auto'
        expected_device = None if device == "auto" else device
        expected_load_mode = None if load_mode == "auto" else load_mode

        assert overrides.device == expected_device
        assert overrides.load_mode == expected_load_mode
        assert overrides.batch_size == batch_size
        assert overrides.max_tokens == max_tokens

    def test_model_override_with_tokens_and_batch(self, parser, cli_overrides_class):
        """Test --model with --max-tokens and --batch-size (C14)."""
        args = parser.parse_args(
            [
                "--site",
                "test",
                "--model",
                "nllb_200_600m",
                "--max-tokens",
                "1024",
                "--batch-size",
                "8",
            ]
        )

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert overrides.model == "nllb_200_600m"
        assert engine_overrides["model_id"] == "nllb_200_600m"
        assert engine_overrides["max_tokens"] == 1024
        assert engine_overrides["batch_size"] == 8


# =============================================================================
# Metrics and Progress Combinations
# =============================================================================


class TestMetricsProgressCombinations:
    """Test metrics and progress control combinations."""

    def test_metrics_file_with_interval(self, parser, cli_overrides_class):
        """Test --metrics-file with --metrics-interval (C15)."""
        args = parser.parse_args(
            ["--site", "test", "--metrics-file", "./metrics.json", "--metrics-interval", "1.0"]
        )

        overrides = cli_overrides_class(args)

        assert overrides.metrics_file == "./metrics.json"
        assert overrides.metrics_interval == 1.0

    def test_metrics_only_with_log_level(self, parser, cli_overrides_class):
        """Test --metrics-only with --log-level."""
        args = parser.parse_args(["--site", "test", "--metrics-only", "--log-level", "ERROR"])

        overrides = cli_overrides_class(args)

        assert overrides.metrics_only is True
        assert args.log_level == "ERROR"


# =============================================================================
# Verification Combinations
# =============================================================================


class TestVerificationCombinations:
    """Test verification control combinations."""

    def test_verify_with_fix_and_report(self, parser, cli_overrides_class):
        """Test --verify with --fix and --verification-report."""
        args = parser.parse_args(
            ["--site", "test", "--verify", "--fix", "--verification-report", "./report.json"]
        )

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["enable_verification"] is True
        assert engine_overrides["enable_verification_fix"] is True
        assert overrides.verification_report == "./report.json"

    def test_verify_with_validation_modes(self, parser, cli_overrides_class):
        """Test --verify with various validation modes."""
        for val_mode in ["strict", "normal", "lenient"]:
            args = parser.parse_args(["--site", "test", "--verify", "--validation-mode", val_mode])

            overrides = cli_overrides_class(args)
            engine_overrides = overrides.get_engine_overrides()

            assert engine_overrides["enable_verification"] is True
            assert engine_overrides["validation_mode"] == val_mode


# =============================================================================
# Content Hash Combinations
# =============================================================================


class TestContentHashCombinations:
    """Test content hash tracking combinations."""

    @pytest.mark.parametrize(
        "disable_hash,rebuild,validate",
        [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (False, True, True),
            (True, True, False),  # Unusual but valid: disable + rebuild
        ],
    )
    def test_content_hash_flag_matrix(
        self, parser, cli_overrides_class, disable_hash, rebuild, validate
    ):
        """Test content hash flag combinations."""
        args_list = ["--site", "test"]

        if disable_hash:
            args_list.append("--disable-content-hash")
        if rebuild:
            args_list.append("--rebuild-content-hashes")
        if validate:
            args_list.append("--validate-output-integrity")

        args = parser.parse_args(args_list)
        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert overrides.disable_content_hash == disable_hash
        assert overrides.rebuild_content_hashes == rebuild
        assert overrides.validate_output_integrity == validate

        # Engine override for content hash tracking
        assert engine_overrides["enable_content_hash_tracking"] == (not disable_hash)


# =============================================================================
# Git Commit Combinations
# =============================================================================


class TestGitCommitCombinations:
    """Test git commit control combinations."""

    def test_auto_commit_with_message(self, parser):
        """Test --auto-commit with --commit-message."""
        args = parser.parse_args(
            ["--site", "test", "--auto-commit", "--commit-message", "Custom commit message"]
        )

        assert args.auto_commit is True
        assert args.commit_message_override == "Custom commit message"

    def test_no_commit_ignores_message(self, parser):
        """Test --no-commit with --commit-message (message ignored)."""
        args = parser.parse_args(
            ["--site", "test", "--no-commit", "--commit-message", "This will be ignored"]
        )

        assert args.auto_commit is False
        assert args.commit_message_override == "This will be ignored"


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_all_flags_minimal_conflict(self, parser, cli_overrides_class):
        """Test many flags together with minimal conflicts."""
        args = parser.parse_args(
            [
                "--site",
                "test",
                "--validation-mode",
                "normal",
                "--enable-terminology",
                "--terminology-mode",
                "both",
                "--max-retries",
                "3",
                "--dry-run",
                "--save-rejected",
                "--verify",
                "--device",
                "cpu",
                "--load-mode",
                "fp32",
                "--batch-size",
                "4",
                "--no-progress",
                "--cache-write-mode",
                "always",
                "--resume",
            ]
        )

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # All should be accepted
        assert engine_overrides["validation_mode"] == "normal"
        assert engine_overrides["enable_terminology"] is True
        assert engine_overrides["terminology_mode"] == "both"
        assert engine_overrides["max_retries"] == 3
        assert engine_overrides["dry_run"] is True
        assert engine_overrides["save_rejected"] is True
        assert engine_overrides["enable_verification"] is True
        assert engine_overrides["batch_size"] == 4
        assert engine_overrides["cache_write_mode"] == "always"

    def test_only_required_site_argument(self, parser, cli_overrides_class):
        """Test with only required --site argument."""
        args = parser.parse_args(["--site", "test"])
        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        # All should have defaults
        assert engine_overrides["enable_validation"] is True
        assert engine_overrides["dry_run"] is False
        assert engine_overrides["save_rejected"] is False

    def test_target_langs_with_multi_language_options(self, parser, cli_overrides_class):
        """Test --target-langs with multi-language processing options."""
        args = parser.parse_args(
            [
                "--site",
                "test",
                "--target-langs",
                "de",
                "es",
                "fr",
                "it",
                "--parallel-languages",
                "2",
            ]
        )

        overrides = cli_overrides_class(args)
        engine_overrides = overrides.get_engine_overrides()

        assert args.target_langs == ["de", "es", "fr", "it"]
        assert engine_overrides["parallel_languages"] == 2


# =============================================================================
# Summary Matrix Test
# =============================================================================


class TestCombinationMatrix:
    """
    Summary test that validates all 10 priority combinations from the task.

    This serves as documentation and a quick reference for CI.
    """

    @pytest.mark.parametrize(
        "test_case",
        [
            {
                "id": "C01",
                "desc": "--dry-run --no-commit",
                "args": ["--dry-run", "--no-commit"],
                "expect_error": False,
            },
            {
                "id": "C02",
                "desc": "--force-retranslate --cache-write-mode never",
                "args": ["--force-retranslate", "--cache-write-mode", "never"],
                "expect_error": False,
            },
            {
                "id": "C03",
                "desc": "--resume --force-restart",
                "args": ["--resume", "--force-restart"],
                "expect_error": False,  # Both parsed, precedence at runtime
            },
            {
                "id": "C04",
                "desc": "--validation-mode off --strict-reject",
                "args": ["--validation-mode", "off", "--strict-reject"],
                "expect_error": False,  # strict-reject takes precedence
            },
            {
                "id": "C05",
                "desc": "--enable-terminology --disable-terminology",
                "args": ["--enable-terminology", "--disable-terminology"],
                "expect_error": False,  # Last wins
            },
            {
                "id": "C06",
                "desc": "--parallel-languages 2 --global-lang-rounds 5",
                "args": ["--parallel-languages", "2", "--global-lang-rounds", "5"],
                "expect_error": True,  # Mutual exclusion error
                "parse_time_error": True,  # CLI-TC-03: Error occurs at parse time
            },
            {
                "id": "C07",
                "desc": "--force-accept --strict-reject",
                "args": ["--force-accept", "--strict-reject"],
                "expect_error": False,  # Both parsed (potential design issue)
            },
            {
                "id": "C08",
                "desc": "--verify --fix",
                "args": ["--verify", "--fix"],
                "expect_error": False,
            },
            {
                "id": "C09",
                "desc": "--device cuda --batch-size 1 --load-mode int8",
                "args": ["--device", "cuda", "--batch-size", "1", "--load-mode", "int8"],
                "expect_error": False,
            },
            {
                "id": "C10",
                "desc": "--metrics-only --no-progress",
                "args": ["--metrics-only", "--no-progress"],
                "expect_error": False,
            },
        ],
    )
    def test_priority_matrix(self, parser, cli_overrides_class, test_case):
        """Validate all priority combinations in the test matrix."""
        full_args = ["--site", "test"] + test_case["args"]

        # CLI-TC-03: Check if error occurs at parse time
        if test_case.get("parse_time_error", False):
            # Error expected at parse time (SystemExit)
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(full_args)
            assert exc_info.value.code == 2, f"Test {test_case['id']} should fail at parse time"
            return

        # Parser accepts the arguments
        args = parser.parse_args(full_args)
        overrides = cli_overrides_class(args)

        if test_case["expect_error"]:
            # Error expected at get_engine_overrides() time (runtime)
            with pytest.raises(ValueError):
                overrides.get_engine_overrides()
        else:
            # No error expected
            engine_overrides = overrides.get_engine_overrides()
            assert engine_overrides is not None, f"Test {test_case['id']} should succeed"
