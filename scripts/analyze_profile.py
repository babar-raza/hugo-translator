"""Analyze cProfile stats and generate comparison report."""
import pstats
from pathlib import Path

# Analyze parallel mode profile
print("=" * 80)
print("PARALLEL MODE PROFILE")
print("=" * 80)
p_parallel = pstats.Stats('artifacts/runs/SR-03/parallel_profile.stats')
p_parallel.strip_dirs()
p_parallel.sort_stats('cumulative')
print("\nTop 20 functions by cumulative time:")
p_parallel.print_stats(20)

print("\n" + "=" * 80)
print("ROUND-ROBIN MODE PROFILE")
print("=" * 80)
p_roundrobin = pstats.Stats('artifacts/runs/SR-03/roundrobin_profile.stats')
p_roundrobin.strip_dirs()
p_roundrobin.sort_stats('cumulative')
print("\nTop 20 functions by cumulative time:")
p_roundrobin.print_stats(20)

print("\n" + "=" * 80)
print("CALL COUNT COMPARISON")
print("=" * 80)

# Get stats for comparison
parallel_stats = p_parallel.stats
roundrobin_stats = p_roundrobin.stats

# Find model loading calls
print("\nSearching for model loading patterns...")
for key in parallel_stats:
    func_name = key[2]
    if 'model' in func_name.lower() or 'load' in func_name.lower():
        if 'HuggingFace' in str(key) or 'Backend' in str(key):
            p_count = parallel_stats[key][0]
            r_count = roundrobin_stats.get(key, (0,))[0]
            print(f"{func_name}: Parallel={p_count}, RoundRobin={r_count}")
