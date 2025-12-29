#!/usr/bin/env python3
"""Guide user through iterative improvement workflow."""
import argparse
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, UTC
from typing import Dict, List, Optional


class ImprovementTracker:
    """Track taskcard improvements across iterations."""

    MAX_ITERATIONS = 5

    def __init__(self, taskcard_id: str, history_dir: str = "plans/healing/.history"):
        """Initialize tracker.

        Args:
            taskcard_id: Taskcard ID (e.g., BM-LANG-01)
            history_dir: Directory for history files
        """
        self.taskcard_id = taskcard_id
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.history_dir / f"{taskcard_id}.json"

    def load_history(self) -> List[Dict]:
        """Load improvement history.

        Returns:
            List of iteration records
        """
        if not self.history_file.exists():
            return []

        with open(self.history_file) as f:
            return json.load(f)

    def save_history(self, history: List[Dict]):
        """Save improvement history.

        Args:
            history: List of iteration records
        """
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)

    def add_iteration(
        self,
        iteration: int,
        ratings: Dict[str, int],
        overall: float,
        changes_made: str,
        automated_checks_passed: int,
        automated_checks_total: int
    ):
        """Add an iteration to history.

        Args:
            iteration: Iteration number (1-based)
            ratings: Dictionary of dimension ratings
            overall: Overall weighted score
            changes_made: Description of changes
            automated_checks_passed: Number of automated checks passed
            automated_checks_total: Total number of automated checks
        """
        history = self.load_history()

        record = {
            "iteration": iteration,
            "timestamp": datetime.now(UTC).isoformat(),
            "ratings": ratings,
            "overall": overall,
            "changes_made": changes_made,
            "automated_checks": {
                "passed": automated_checks_passed,
                "total": automated_checks_total
            }
        }

        history.append(record)
        self.save_history(history)

    def get_current_iteration(self) -> int:
        """Get current iteration number.

        Returns:
            Current iteration (1-based), or 1 if no history
        """
        history = self.load_history()
        return len(history) + 1

    def show_progress(self):
        """Display improvement progress across iterations."""
        history = self.load_history()

        if not history:
            print("No improvement history found. This is iteration 1.")
            return

        print()
        print("=" * 70)
        print(f"IMPROVEMENT HISTORY: {self.taskcard_id}")
        print("=" * 70)
        print()

        for record in history:
            iteration = record["iteration"]
            overall = record["overall"]
            ratings = record["ratings"]
            timestamp = record["timestamp"][:10]  # Just date

            print(f"Iteration {iteration} ({timestamp}):")
            print(f"  Overall: {overall:.2f}/5")

            # Show individual dimensions
            for dim, rating in ratings.items():
                print(f"    {dim:20s}: {rating}/5")

            # Show automated checks
            auto_checks = record.get("automated_checks", {})
            if auto_checks:
                passed = auto_checks.get("passed", 0)
                total = auto_checks.get("total", 0)
                print(f"  Automated checks: {passed}/{total} passing")

            # Show changes
            changes = record.get("changes_made", "")
            if changes:
                print(f"  Changes: {changes}")

            print()

        # Show trend
        if len(history) > 1:
            first_overall = history[0]["overall"]
            last_overall = history[-1]["overall"]
            delta = last_overall - first_overall

            if delta > 0:
                print(f"📈 Progress: +{delta:.2f} points over {len(history)} iteration(s)")
            elif delta < 0:
                print(f"📉 Warning: {delta:.2f} points over {len(history)} iteration(s)")
            else:
                print(f"➡️  No change in overall score")

            print()


def run_automated_checks() -> tuple:
    """Run automated quality checks.

    Returns:
        Tuple of (passed: int, total: int)
    """
    try:
        result = subprocess.run(
            ["python", "scripts/check_quality.py", "--json"],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 or result.stdout:
            data = json.loads(result.stdout)
            passed = data.get("passed", 0)
            total = data.get("total_checks", 0)
            return passed, total
    except Exception as e:
        print(f"⚠️  Could not run automated checks: {e}")

    return 0, 0


def identify_lowest_dimension(ratings: Dict[str, int]) -> str:
    """Identify the lowest-rated dimension.

    Args:
        ratings: Dictionary of dimension ratings

    Returns:
        Name of lowest dimension
    """
    return min(ratings.items(), key=lambda x: x[1])[0]


def suggest_improvements(dimension: str, current_rating: int) -> str:
    """Suggest specific improvements for a dimension.

    Args:
        dimension: Dimension name
        current_rating: Current rating (1-5)

    Returns:
        Improvement suggestions
    """
    suggestions = {
        "correctness": {
            1: "Focus on making it work for basic cases. Fix syntax errors and implement core functionality.",
            2: "Reduce major bugs. Add input validation and handle common error cases.",
            3: "Handle edge cases. Add unit tests and fix all known bugs.",
            4: "Aim for perfection. Get 100% test coverage and test all edge cases.",
            5: "Already excellent! Maintain this level."
        },
        "completeness": {
            1: "Implement >50% of requirements. Focus on core features.",
            2: "Implement 80%+ of requirements. Add remaining features and fill gaps.",
            3: "Implement 95%+ of requirements. Complete all critical features and remove most TODOs.",
            4: "Aim for 100% completion. Remove ALL TODOs and meet all acceptance criteria.",
            5: "Already complete! Well done."
        },
        "production_ready": {
            1: "Remove obvious prototype code. Replace stubs with real implementations.",
            2: "Remove most hardcoded values. Add basic logging and remove debug code.",
            3: "Move all config to YAML files. Add comprehensive error handling and structured logging.",
            4: "Ensure production-grade quality. Pass security scans and optimize performance.",
            5: "Already production-ready! Great work."
        },
        "documentation": {
            1: "Add basic README with project description and installation steps.",
            2: "Document core APIs. Add docstrings for public functions and basic examples.",
            3: "Create comprehensive docs. Document all public APIs with multiple examples.",
            4: "Aim for excellent documentation. Add architecture diagrams and troubleshooting guide.",
            5: "Already well-documented! Nice job."
        },
        "testability": {
            1: "Add basic tests. Test core functionality and aim for 40%+ coverage.",
            2: "Expand test coverage. Test edge cases and aim for 70%+ coverage.",
            3: "Add comprehensive testing. Unit tests for all functions, aim for 90%+ coverage.",
            4: "Complete the test suite. Get 100% coverage with performance and regression tests.",
            5: "Already thoroughly tested! Excellent."
        }
    }

    return suggestions.get(dimension, {}).get(current_rating, "No suggestions available.")


def main():
    parser = argparse.ArgumentParser(description="Guide taskcard improvement")
    parser.add_argument("taskcard_id", help="Taskcard ID (e.g., BM-LANG-01)")
    parser.add_argument("--show-history", action="store_true", help="Show improvement history")
    parser.add_argument("--reset", action="store_true", help="Reset improvement history")
    args = parser.parse_args()

    tracker = ImprovementTracker(args.taskcard_id)

    # Handle special modes
    if args.reset:
        if tracker.history_file.exists():
            tracker.history_file.unlink()
            print(f"✓ Reset history for {args.taskcard_id}")
        return 0

    if args.show_history:
        tracker.show_progress()
        return 0

    # Main improvement workflow
    current_iteration = tracker.get_current_iteration()

    print()
    print("=" * 70)
    print(f"ITERATIVE IMPROVEMENT WORKFLOW")
    print("=" * 70)
    print(f"\nTaskcard: {args.taskcard_id}")
    print(f"Iteration: {current_iteration}/{tracker.MAX_ITERATIONS}")
    print()

    # Check iteration limit
    if current_iteration > tracker.MAX_ITERATIONS:
        print(f"⚠️  Maximum iterations ({tracker.MAX_ITERATIONS}) reached!")
        print()
        print("This taskcard may need:")
        print("  1. Requirements review (are they realistic?)")
        print("  2. Approach reassessment (is the strategy sound?)")
        print("  3. Peer review (get help from others)")
        print("  4. Taskcard split (may be too large)")
        print()
        return 1

    # Show progress from previous iterations
    if current_iteration > 1:
        tracker.show_progress()

    # Step 1: Run automated checks
    print("Step 1: Running automated quality checks...")
    print("-" * 70)
    passed, total = run_automated_checks()

    if total > 0:
        print(f"Automated checks: {passed}/{total} passing")
        if passed < total:
            print(f"⚠️  Fix {total - passed} failing check(s) before continuing")
            print("   Run: python scripts/check_quality.py")
            print()
            return 1
        else:
            print("✓ All automated checks passing!")
    else:
        print("⚠️  Could not run automated checks (continuing anyway)")

    print()

    # Step 2: Rate current state
    print("Step 2: Rate the current state")
    print("-" * 70)
    print("Run the rating script:")
    print(f"  python scripts/rate_taskcard.py {args.taskcard_id}")
    print()
    print("Enter ratings when prompted, then return here with the results.")
    print()

    # Get ratings from user
    ratings = {}
    dimensions = ["correctness", "completeness", "production_ready", "documentation", "testability"]
    weights = {"correctness": 0.30, "completeness": 0.25, "production_ready": 0.25,
               "documentation": 0.10, "testability": 0.10}

    for dim in dimensions:
        while True:
            try:
                rating = int(input(f"{dim.replace('_', ' ').title():<25s} (1-5): "))
                if 1 <= rating <= 5:
                    ratings[dim] = rating
                    break
            except ValueError:
                pass
            print("Invalid input. Enter 1-5.")

    # Calculate overall
    overall = sum(ratings[dim] * weights[dim] for dim in dimensions)

    print()
    print("-" * 70)
    print(f"Overall Score: {overall:.2f}/5")
    print()

    # Step 3: Identify lowest dimension
    lowest_dim = identify_lowest_dimension(ratings)
    lowest_rating = ratings[lowest_dim]

    print("Step 3: Focus area identified")
    print("-" * 70)
    print(f"Lowest dimension: {lowest_dim.replace('_', ' ').title()} ({lowest_rating}/5)")
    print()

    # Step 4: Suggest improvements
    print("Step 4: Recommended improvements")
    print("-" * 70)
    suggestion = suggest_improvements(lowest_dim, lowest_rating)
    print(f"{suggestion}")
    print()
    print("See docs/quality/IMPROVEMENT_WORKFLOW.md for detailed guidance.")
    print()

    # Step 5: Track changes
    print("Step 5: Document changes made")
    print("-" * 70)
    changes = input("Describe changes made in this iteration: ").strip()

    # Save iteration
    tracker.add_iteration(
        iteration=current_iteration,
        ratings=ratings,
        overall=overall,
        changes_made=changes,
        automated_checks_passed=passed,
        automated_checks_total=total
    )

    print()
    print("=" * 70)

    # Check if passing
    passing = (
        overall >= 4.0 and
        all(r >= 3.0 for r in ratings.values()) and
        ratings.get("correctness", 0) >= 4.0 and
        ratings.get("completeness", 0) >= 4.0
    )

    if passing:
        print("✅ CONGRATULATIONS! Taskcard meets all quality criteria.")
        print()
        print(f"   Overall: {overall:.2f}/5 (≥4.0 required)")
        print(f"   All dimensions ≥3.0: {'✓' if all(r >= 3.0 for r in ratings.values()) else '✗'}")
        print(f"   Critical dimensions ≥4.0: {'✓' if ratings.get('correctness', 0) >= 4.0 and ratings.get('completeness', 0) >= 4.0 else '✗'}")
        print()
        print(f"Completed in {current_iteration} iteration(s).")
    else:
        print("❌ Not yet passing. Continue improving.")
        print()
        print("Failing criteria:")
        if overall < 4.0:
            print(f"  - Overall score: {overall:.2f}/5 (need ≥4.0)")
        if any(r < 3.0 for r in ratings.values()):
            for dim, rating in ratings.items():
                if rating < 3.0:
                    print(f"  - {dim}: {rating}/5 (need ≥3.0)")
        if ratings.get("correctness", 0) < 4.0:
            print(f"  - correctness: {ratings.get('correctness', 0)}/5 (need ≥4.0)")
        if ratings.get("completeness", 0) < 4.0:
            print(f"  - completeness: {ratings.get('completeness', 0)}/5 (need ≥4.0)")
        print()
        print("Next steps:")
        print(f"  1. Focus on: {lowest_dim.replace('_', ' ').title()}")
        print("  2. Apply improvements")
        print(f"  3. Re-run: python scripts/improve_taskcard.py {args.taskcard_id}")

    print("=" * 70)
    print()

    return 0 if passing else 1


if __name__ == "__main__":
    sys.exit(main())
