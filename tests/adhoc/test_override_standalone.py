"""
Standalone test for OverrideController without heavy dependencies.
Run this with the llm conda environment:
    conda activate llm && python test_override_standalone.py
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Test the override controller directly (doesn't need TM layers)
print("=" * 60)
print("Testing TM Cache Override System")
print("=" * 60)
print()

# Import override controller directly (bypassing __init__.py to avoid heavy deps)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "override_controller",
    Path(__file__).parent / "src" / "tm" / "override_controller.py"
)
override_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(override_module)

OverrideController = override_module.OverrideController
OverrideConfig = override_module.OverrideConfig
OverrideMode = override_module.OverrideMode
OverrideFilter = override_module.OverrideFilter

print("1. Testing OverrideMode enum...")
print(f"   Available modes: {[m.value for m in OverrideMode]}")
print("   [PASS]")
print()

print("2. Testing OverrideController with NORMAL mode...")
controller = OverrideController()
assert controller.mode == OverrideMode.NORMAL
assert not controller.should_bypass_lookup("test text", "bg")
print("   - NORMAL mode does not bypass lookup")
print("   [PASS]")
print()

print("3. Testing OverrideController with BYPASS mode...")
config = OverrideConfig(mode=OverrideMode.BYPASS)
controller = OverrideController(config)
assert controller.should_bypass_lookup("test text", "bg")
print("   - BYPASS mode skips all lookups")
print("   [PASS]")
print()

print("4. Testing OverrideController with REFRESH mode...")
config = OverrideConfig(mode=OverrideMode.REFRESH)
controller = OverrideController(config)
assert controller.should_bypass_lookup("test text", "bg")
assert controller.should_update_cache("test text", "bg")
print("   - REFRESH mode skips lookup AND updates cache")
print("   [PASS]")
print()

print("5. Testing filters with source_patterns...")
filter_config = OverrideFilter(
    source_patterns=[r".*\[.*\]\(.*\).*"]  # Markdown links pattern
)
config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filter_config)
controller = OverrideController(config)

# Text with link - should match filter and bypass
text_with_link = "Check [NuGet](https://nuget.org) for packages."
assert controller.should_bypass_lookup(text_with_link, "bg"), "Text with link should be bypassed"
print(f"   - '{text_with_link[:40]}...' -> BYPASSED")

# Text without link - should NOT match filter (use cache)
text_no_link = "This is plain text without any links."
assert not controller.should_bypass_lookup(text_no_link, "bg"), "Text without link should use cache"
print(f"   - '{text_no_link}' -> USE CACHE")
print("   [PASS]")
print()

print("6. Testing filters with target_langs...")
filter_config = OverrideFilter(target_langs=["bg", "ru"])
config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filter_config)
controller = OverrideController(config)

assert controller.should_bypass_lookup("any text", "bg"), "Bulgarian should be bypassed"
assert controller.should_bypass_lookup("any text", "ru"), "Russian should be bypassed"
assert not controller.should_bypass_lookup("any text", "de"), "German should use cache"
print("   - bg, ru -> BYPASSED")
print("   - de -> USE CACHE")
print("   [PASS]")
print()

print("7. Testing filters with frontmatter_keys...")
filter_config = OverrideFilter(frontmatter_keys=["body.block.content_left", "title"])
config = OverrideConfig(mode=OverrideMode.REFRESH, filters=filter_config)
controller = OverrideController(config)

ctx_match = {"frontmatter_key": "body.block.content_left"}
ctx_no_match = {"frontmatter_key": "description"}

assert controller.should_bypass_lookup("text", "bg", ctx_match), "Matching key should bypass"
assert not controller.should_bypass_lookup("text", "bg", ctx_no_match), "Non-matching key should use cache"
print("   - frontmatter_key='body.block.content_left' -> BYPASSED")
print("   - frontmatter_key='description' -> USE CACHE")
print("   [PASS]")
print()

print("8. Testing stats tracking...")
config = OverrideConfig(mode=OverrideMode.REFRESH)
controller = OverrideController(config)
controller.should_bypass_lookup("text1", "bg")
controller.should_bypass_lookup("text2", "bg")
controller.should_bypass_lookup("text3", "bg")
stats = controller.stats  # Use property, not method
print(f"   Stats: {stats}")
assert stats["total_checked"] == 3
assert stats["refreshed"] == 3  # REFRESH mode tracks as 'refreshed'
print("   [PASS]")
print()

print("=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)
print()
print("The TM Cache Override system is working correctly.")
print()
print("Usage example:")
print("  python scripts/batch_translate.py \\")
print("    --input ./content/slides/en \\")
print("    --output ./output/slides-bg \\")
print("    --langs bg \\")
print("    --override-mode refresh \\")
print("    --override-filter-langs bg")
