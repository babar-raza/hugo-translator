"""
Simple acceptance test for TC-02 AST addressing (no external dependencies).
"""
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Direct import
import importlib.util
ast_nodes_spec = importlib.util.spec_from_file_location(
    "ast_nodes",
    src_path / "translation_engine" / "parser" / "ast_nodes.py"
)
ast_nodes = importlib.util.module_from_spec(ast_nodes_spec)
ast_nodes_spec.loader.exec_module(ast_nodes)

ASTNode = ast_nodes.ASTNode
NodeType = ast_nodes.NodeType
text_node = ast_nodes.text_node
paragraph_node = ast_nodes.paragraph_node

print("=== TC-02 Core Functionality Tests ===\n")

# Test 1: Basic assignment
para = paragraph_node([text_node("Hello")])
para.assign_addresses("body.para[0]")
assert para.node_addr == "body.para[0]"
assert para.children[0].node_addr == "body.para[0].text[0]"
print("OK Test 1: Basic address assignment")

# Test 2: Multiple children
para2 = paragraph_node([
    text_node("First"),
    text_node("Second"),
    text_node("Third")
])
para2.assign_addresses("body.para[0]")
assert para2.children[0].node_addr == "body.para[0].text[0]"
assert para2.children[1].node_addr == "body.para[0].text[1]"
assert para2.children[2].node_addr == "body.para[0].text[2]"
print("OK Test 2: Type counters increment correctly")

# Test 3: Nested structure
strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
para3 = paragraph_node([text_node("Before "), strong, text_node(" after")])
para3.assign_addresses("body.para[0]")
assert para3.children[1].node_addr == "body.para[0].strong[0]"
assert para3.children[1].children[0].node_addr == "body.para[0].strong[0].text[0]"
print("OK Test 3: Nested structure addressing")

# Test 4: get_node_by_addr - self
found_self = para3.get_node_by_addr("body.para[0]")
assert found_self is para3
print("OK Test 4: get_node_by_addr retrieves self")

# Test 5: get_node_by_addr - child
found_text = para3.get_node_by_addr("body.para[0].text[0]")
assert found_text is not None
assert found_text.raw == "Before "
print("OK Test 5: get_node_by_addr retrieves direct child")

# Test 6: get_node_by_addr - nested
found_nested = para3.get_node_by_addr("body.para[0].strong[0].text[0]")
assert found_nested is not None
assert found_nested.raw == "bold"
print("OK Test 6: get_node_by_addr retrieves nested child")

# Test 7: get_node_by_addr - invalid returns None
invalid = para3.get_node_by_addr("body.para[99].text[0]")
assert invalid is None
print("OK Test 7: get_node_by_addr returns None for invalid address")

# Test 8: Determinism
para4a = paragraph_node([text_node("Hello"), text_node("World")])
para4b = paragraph_node([text_node("Hello"), text_node("World")])
para4a.assign_addresses("body.para[0]")
para4b.assign_addresses("body.para[0]")
assert para4a.node_addr == para4b.node_addr
assert para4a.children[0].node_addr == para4b.children[0].node_addr
assert para4a.children[1].node_addr == para4b.children[1].node_addr
print("OK Test 8: Address assignment is deterministic")

# Test 9: Idempotency
para5 = paragraph_node([text_node("Test")])
para5.assign_addresses("body.para[0]")
addr1 = para5.children[0].node_addr
para5.assign_addresses("body.para[0]")
addr2 = para5.children[0].node_addr
assert addr1 == addr2
print("OK Test 9: assign_addresses is idempotent")

# Test 10: Mixed types
strong1 = ASTNode(type=NodeType.STRONG, children=[text_node("bold1")])
strong2 = ASTNode(type=NodeType.STRONG, children=[text_node("bold2")])
para6 = paragraph_node([
    text_node("T1 "),
    strong1,
    text_node(" T2 "),
    strong2,
    text_node(" T3")
])
para6.assign_addresses("body.para[0]")
assert para6.children[0].node_addr == "body.para[0].text[0]"
assert para6.children[1].node_addr == "body.para[0].strong[0]"
assert para6.children[2].node_addr == "body.para[0].text[1]"
assert para6.children[3].node_addr == "body.para[0].strong[1]"
assert para6.children[4].node_addr == "body.para[0].text[2]"
print("OK Test 10: Mixed types have separate counters")

print("\n=== ALL TC-02 CORE TESTS PASSED ===\n")
print("TC-02 Deliverables Complete:")
print("OK node_addr field added to ASTNode")
print("OK assign_addresses() method implemented")
print("OK get_node_by_addr() method implemented")
print("OK Address format: dot notation with type[index]")
print("OK Deterministic addressing")
print("OK Idempotent assignment")
print("OK Handles nested structures")
print("OK Type-specific counters")
print("\nReady to proceed to TC-03!")
