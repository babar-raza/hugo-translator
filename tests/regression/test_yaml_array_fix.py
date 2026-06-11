"""Quick test to verify array-aware YAML formatter."""

from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

# Test 1: Simple nested key
print("Test 1: Simple nested key")
data1 = {}
YAMLFormatter.set_nested_value(data1, "banner.title", "Hello")
print(f"Result: {data1}")
assert data1 == {"banner": {"title": "Hello"}}, "Test 1 failed"
print("[PASS] Test 1 passed\n")

# Test 2: Array index
print("Test 2: Array index")
data2 = {}
YAMLFormatter.set_nested_value(data2, "body.block[0].title", "First Title")
print(f"Result: {data2}")
expected = {"body": {"block": [{"title": "First Title"}]}}
assert data2 == expected, f"Test 2 failed: expected {expected}, got {data2}"
print("[PASS] Test 2 passed\n")

# Test 3: Multiple array elements
print("Test 3: Multiple array elements")
data3 = {}
YAMLFormatter.set_nested_value(data3, "body.block[0].title_left", "First Left")
YAMLFormatter.set_nested_value(data3, "body.block[0].title_right", "First Right")
YAMLFormatter.set_nested_value(data3, "body.block[1].title_left", "Second Left")
print(f"Result: {data3}")
expected3 = {
    "body": {
        "block": [
            {"title_left": "First Left", "title_right": "First Right"},
            {"title_left": "Second Left"},
        ]
    }
}
assert data3 == expected3, f"Test 3 failed: expected {expected3}, got {data3}"
print("[PASS] Test 3 passed\n")

# Test 4: Get nested value with array
print("Test 4: Get nested value with array")
result = YAMLFormatter.get_nested_value(data3, "body.block[0].title_left")
print(f"Result: {result}")
assert result == "First Left", f"Test 4 failed: expected 'First Left', got {result}"
print("[PASS] Test 4 passed\n")

# Test 5: FAQ list pattern
print("Test 5: FAQ list pattern")
data5 = {}
YAMLFormatter.set_nested_value(data5, "faq.list[0].question", "What is this?")
YAMLFormatter.set_nested_value(data5, "faq.list[0].answer", "This is an answer")
YAMLFormatter.set_nested_value(data5, "faq.list[1].question", "Second question?")
print(f"Result: {data5}")
expected5 = {
    "faq": {
        "list": [
            {"question": "What is this?", "answer": "This is an answer"},
            {"question": "Second question?"},
        ]
    }
}
assert data5 == expected5, "Test 5 failed"
print("[PASS] Test 5 passed\n")

print("=" * 50)
print("All tests passed!")
print("=" * 50)
