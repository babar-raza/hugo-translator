#!/usr/bin/env python3
"""Rate a taskcard on quality dimensions."""
import argparse
import sys

import yaml


def load_rubric() -> dict:
    """Load quality rubric from config."""
    with open("config/quality_rubric.yaml") as f:
        return yaml.safe_load(f)

def rate_dimension(dimension_name: str, criteria: dict) -> int:
    """Interactively rate a dimension."""
    print(f"\n{dimension_name}")
    print("=" * 60)
    for rating in [5, 4, 3, 2, 1]:
        print(f"  {rating}/5: {criteria[rating]}")

    while True:
        try:
            rating = int(input("\nRating (1-5): "))
            if 1 <= rating <= 5:
                evidence = input("Evidence (brief): ")
                return rating, evidence
        except ValueError:
            pass
        print("Invalid input. Please enter 1-5.")

def calculate_overall(ratings: dict[str, int], rubric: dict) -> float:
    """Calculate weighted overall score."""
    total = 0.0
    for dim_id, rating in ratings.items():
        weight = rubric['dimensions'][dim_id]['weight']
        total += rating * weight
    return total

def main():
    parser = argparse.ArgumentParser(description="Rate a taskcard")
    parser.add_argument("taskcard_id", help="Taskcard ID (e.g., BM-LANG-01)")
    parser.add_argument("--auto", action="store_true", help="Run automated checks only")
    args = parser.parse_args()

    rubric = load_rubric()
    ratings = {}
    evidence = {}

    print(f"Rating taskcard: {args.taskcard_id}")
    print("=" * 60)

    # Rate each dimension
    for dim_id, dim_info in rubric['dimensions'].items():
        rating, ev = rate_dimension(
            dim_info['name'],
            dim_info['criteria']
        )
        ratings[dim_id] = rating
        evidence[dim_id] = ev

    # Calculate overall
    overall = calculate_overall(ratings, rubric)

    # Display results
    print("\n" + "=" * 60)
    print("RATING SUMMARY")
    print("=" * 60)
    for dim_id, rating in ratings.items():
        name = rubric['dimensions'][dim_id]['name']
        print(f"{name:20s}: {rating}/5")
    print("-" * 60)
    print(f"{'Overall (weighted)':20s}: {overall:.2f}/5")

    # Check passing criteria
    passing = overall >= rubric['passing_criteria']['overall_minimum']
    for dim_id, rating in ratings.items():
        if rating < rubric['passing_criteria']['dimension_minimum']:
            passing = False
            print(f"✗ {dim_id} below minimum threshold")

    if passing:
        print("\n✅ PASS - Taskcard meets quality standards")
        return 0
    else:
        print("\n❌ FAIL - Taskcard needs improvement")
        return 1

if __name__ == "__main__":
    sys.exit(main())
