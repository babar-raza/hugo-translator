#!/usr/bin/env python
"""
E2E Single File Verifier.

Performs strict structural fidelity and quality checks on translated files.
Exit code 0 = pass, 1 = fail.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.translation_engine.parser.hugo_parser import HugoParser, HugoDocument
    from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
    HUGO_PARSER_AVAILABLE = True
except ImportError:
    HUGO_PARSER_AVAILABLE = False
    print("WARNING: HugoParser not available. Advanced AST checks disabled.", file=sys.stderr)
    # Provide dummy types for type hints
    ASTNode = object
    NodeType = object

# ============================================================================
# STRUCTURAL FIDELITY CHECKS (STRICT)
# ============================================================================


def count_shortcodes(content: str) -> Dict[str, int]:
    """Count shortcode occurrences."""
    opening_tags = len(re.findall(r'\{\{<', content))
    percent_tags = len(re.findall(r'\{\{%', content))
    return {'opening': opening_tags, 'percent': percent_tags, 'total': opening_tags + percent_tags}


def count_code_fences(content: str) -> Dict[str, int]:
    """Count code fences and check for unclosed fences."""
    fences = re.findall(r'^```', content, re.MULTILINE)
    count = len(fences)
    is_balanced = (count % 2 == 0)
    return {'count': count, 'is_balanced': is_balanced}


def count_table_rows(content: str) -> int:
    """Count table rows (lines starting with |)."""
    rows = re.findall(r'^\|.*\|', content, re.MULTILINE)
    return len(rows)


def count_list_markers(content: str) -> Dict[str, int]:
    """Count list markers."""
    unordered = len(re.findall(r'^[-*+]\s', content, re.MULTILINE))
    ordered = len(re.findall(r'^\d+\.\s', content, re.MULTILINE))
    nested = len(re.findall(r'^\s{2,}[-*+]\s', content, re.MULTILINE))
    return {
        'unordered': unordered,
        'ordered': ordered,
        'nested': nested,
        'total': unordered + ordered
    }


def check_list_item_concatenation(content: str) -> List[str]:
    """
    Check for list item concatenation patterns.

    Example bad patterns:
        ✔ Item1✔ Item2...
        - Item1- Item2

    Returns list of issues found.
    """
    issues = []

    # Check for bullet/check marks followed by text and then another marker without newline
    patterns = [
        (r'[-*+✓✔]\s+\w+.*?[-*+✓✔]\s+\w+', 'List markers concatenated without newlines'),
        (r'\d+\.\s+\w+.*?\d+\.\s+\w+', 'Ordered list items concatenated without newlines'),
    ]

    for pattern, desc in patterns:
        # Look for patterns within a single line
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Skip lines that likely contain bold/italic markers (** or __)
            # These can cause false positives
            if '**' in line or '__' in line:
                continue

            matches = re.findall(pattern, line)
            if matches:
                issues.append(f"{desc} on line {i}: {line[:80]}...")

    return issues


def extract_frontmatter(content: str) -> Optional[str]:
    """Extract YAML frontmatter."""
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if match:
        return match.group(1)
    return None


def get_frontmatter_keys(frontmatter: str) -> set:
    """Extract keys from YAML frontmatter (simple parser)."""
    if not frontmatter:
        return set()

    keys = set()
    for line in frontmatter.split('\n'):
        # Simple key extraction (handles "key:" format)
        match = re.match(r'^(\w+):', line.strip())
        if match:
            keys.add(match.group(1))

    return keys


def check_token_leakage(content: str) -> List[str]:
    """Check for synthetic token leakage."""
    leaks = []

    # Case-insensitive xifp
    if re.search(r'xifp', content, re.IGNORECASE):
        leaks.append('xifp token found')

    # Special brackets
    if '⟦' in content or '⟧' in content:
        leaks.append('⟦ ⟧ brackets found')

    # Placeholder pattern
    if re.search(r'\{PLACEHOLDER_', content, re.IGNORECASE):
        leaks.append('{PLACEHOLDER_ pattern found')

    # XIFFX/XIFMX patterns
    if re.search(r'XIFFX|XIFMX', content, re.IGNORECASE):
        leaks.append('XIFFX/XIFMX pattern found')

    return leaks


def count_lines(content: str) -> int:
    """Count non-empty lines."""
    return len([line for line in content.split('\n') if line.strip()])


# ============================================================================
# ADVANCED AST-BASED MARKDOWN FIDELITY CHECKS (NEW)
# ============================================================================


def count_ast_elements(ast: List[ASTNode]) -> Dict[str, any]:
    """
    Count structural markdown elements from AST.

    Returns counts for:
    - Bold spans (STRONG nodes)
    - Italic spans (EMPHASIS nodes)
    - Headings by level
    - List items by depth
    - Links
    - Code spans
    """
    counts = {
        'bold': 0,
        'italic': 0,
        'headings': {},  # level -> count
        'list_items': 0,
        'nested_list_items': 0,
        'links': 0,
        'code_spans': 0,
    }

    def traverse(node: ASTNode, depth: int = 0, in_list: bool = False):
        """Recursively traverse AST and count elements."""
        # Count based on node type
        if node.type == NodeType.STRONG:
            counts['bold'] += 1
        elif node.type == NodeType.EMPHASIS:
            counts['italic'] += 1
        elif node.type == NodeType.HEADING:
            level = node.attrs.get('level', 1)
            counts['headings'][level] = counts['headings'].get(level, 0) + 1
        elif node.type == NodeType.LIST_ITEM:
            counts['list_items'] += 1
            if depth > 0:
                counts['nested_list_items'] += 1
        elif node.type == NodeType.LINK:
            counts['links'] += 1
        elif node.type == NodeType.CODE_SPAN:
            counts['code_spans'] += 1

        # Recurse into children
        new_depth = depth + 1 if node.type == NodeType.LIST else depth
        for child in node.children:
            traverse(child, new_depth, in_list or node.type == NodeType.LIST)

    for node in ast:
        traverse(node)

    return counts


def check_bold_to_list_corruption(source_ast: List[ASTNode], target_ast: List[ASTNode]) -> List[str]:
    """
    Check for specific corruption: bold-only paragraphs converted to list items.

    Example:
        Source: **Plateformes soutenues** (paragraph with single bold child)
        Target: * Des plateformes soutenues * (list item or italic)

    Returns list of corruption issues found.
    """
    issues = []

    def is_bold_only_paragraph(node: ASTNode) -> bool:
        """Check if node is paragraph containing only bold text."""
        if node.type != NodeType.PARAGRAPH:
            return False

        # Check if has exactly one child that is STRONG
        if len(node.children) == 1 and node.children[0].type == NodeType.STRONG:
            return True

        # Check if all non-whitespace children are STRONG
        non_ws_children = [c for c in node.children if not (c.type == NodeType.TEXT and not c.raw.strip())]
        return len(non_ws_children) == 1 and non_ws_children[0].type == NodeType.STRONG

    def get_bold_only_paragraphs(ast: List[ASTNode]) -> List[str]:
        """Extract text content from bold-only paragraphs."""
        bold_paras = []

        def traverse(node: ASTNode):
            if is_bold_only_paragraph(node):
                # Extract text content
                text_parts = []
                for child in node.children:
                    if child.type == NodeType.STRONG:
                        text_parts.extend(extract_text(child))
                bold_paras.append(' '.join(text_parts).strip())

            for child in node.children:
                traverse(child)

        for node in ast:
            traverse(node)

        return bold_paras

    def extract_text(node: ASTNode) -> List[str]:
        """Recursively extract all text from node."""
        texts = []
        if node.type == NodeType.TEXT and node.raw:
            texts.append(node.raw)
        for child in node.children:
            texts.extend(extract_text(child))
        return texts

    def has_list_items_near_text(ast: List[ASTNode], text: str) -> bool:
        """
        Check if target has list items that match the bold text (FIX-E).

        FIX-E: Only flag as corruption if the bold text closely matches
        a list item's START (not just any list item containing similar words).
        This prevents false positives where unrelated list items happen
        to contain similar text elsewhere in the document.
        """
        def traverse(node: ASTNode):
            if node.type == NodeType.LIST_ITEM:
                item_text = ' '.join(extract_text(node)).strip()

                # FIX-E: Check if the list item STARTS WITH the bold text
                # (accounting for translation and punctuation differences)

                text_lower = text.lower()
                item_lower = item_text.lower()

                # Clean punctuation for comparison
                text_clean = text_lower.strip(':. ').strip()
                item_clean = item_lower.strip(':. ').strip()

                if len(text_clean) >= 5 and len(item_clean) >= 5:
                    # Check if the list item starts with the bold text
                    # (this indicates the bold paragraph became a list item)
                    if item_clean.startswith(text_clean[:min(20, len(text_clean))]):
                        return True

            for child in node.children:
                if traverse(child):
                    return True
            return False

        for node in ast:
            if traverse(node):
                return True
        return False

    # Get bold-only paragraphs from source
    source_bold_paras = get_bold_only_paragraphs(source_ast)

    # Check if any converted to list items in target
    for bold_text in source_bold_paras:
        if has_list_items_near_text(target_ast, bold_text):
            issues.append(
                f"Bold-only paragraph appears to be converted to list item: "
                f"'{bold_text[:50]}...'"
            )

    return issues


def verify_ast_structural_fidelity(
    source_content: str,
    target_content: str
) -> Dict[str, any]:
    """
    Verify markdown structural fidelity using AST parsing.

    Returns:
        dict with:
        - passed: bool
        - source_counts: dict
        - target_counts: dict
        - errors: list of error messages
    """
    if not HUGO_PARSER_AVAILABLE:
        return {
            'passed': True,
            'note': 'HugoParser not available, skipping AST checks',
            'errors': []
        }

    result = {
        'passed': True,
        'errors': [],
        'source_counts': None,
        'target_counts': None,
    }

    try:
        # Parse both documents
        parser = HugoParser()
        source_doc = parser.parse_string(source_content)
        target_doc = parser.parse_string(target_content)

        # Count elements
        source_counts = count_ast_elements(source_doc.ast)
        target_counts = count_ast_elements(target_doc.ast)

        result['source_counts'] = source_counts
        result['target_counts'] = target_counts

        # Check bold count (STRICT - no conversion to italic or list allowed)
        if source_counts['bold'] != target_counts['bold']:
            result['passed'] = False
            result['errors'].append(
                f"Bold span count mismatch: source={source_counts['bold']}, "
                f"target={target_counts['bold']}. "
                f"Bold must not convert to italic or list items."
            )

        # Check italic count (STRICT - no conversion from bold allowed)
        if source_counts['italic'] != target_counts['italic']:
            result['passed'] = False
            result['errors'].append(
                f"Italic span count mismatch: source={source_counts['italic']}, "
                f"target={target_counts['italic']}. "
                f"Italic must not convert from bold or to other formats."
            )

        # Check headings by level (STRICT - exact counts per level)
        for level in set(list(source_counts['headings'].keys()) + list(target_counts['headings'].keys())):
            src_count = source_counts['headings'].get(level, 0)
            tgt_count = target_counts['headings'].get(level, 0)
            if src_count != tgt_count:
                result['passed'] = False
                result['errors'].append(
                    f"Heading level {level} count mismatch: source={src_count}, target={tgt_count}. "
                    f"Headings must not convert to lists or other formats."
                )

        # Check links count (STRICT - must match exactly)
        if source_counts['links'] != target_counts['links']:
            result['passed'] = False
            result['errors'].append(
                f"Link count mismatch: source={source_counts['links']}, "
                f"target={target_counts['links']}"
            )

        # Check code spans count (STRICT - must match exactly)
        if source_counts['code_spans'] != target_counts['code_spans']:
            result['passed'] = False
            result['errors'].append(
                f"Code span count mismatch: source={source_counts['code_spans']}, "
                f"target={target_counts['code_spans']}"
            )

        # Check for bold-to-list corruption
        bold_corruption = check_bold_to_list_corruption(source_doc.ast, target_doc.ast)
        if bold_corruption:
            result['passed'] = False
            result['errors'].extend(bold_corruption)

    except Exception as e:
        result['passed'] = False
        result['errors'].append(f"AST parsing failed: {e}")

    return result


# ============================================================================
# QUALITY CHECKS (MEDIUM-LEVEL)
# ============================================================================


def check_terminology_issues(source: str, target: str) -> List[str]:
    """Check for known terminology issues."""
    issues = []

    # Check for "merge" -> "métrage" issue
    if 'merge' in source.lower() and 'métrage' in target.lower():
        issues.append("Terminology error: 'merge' translated as 'métrage'")

    # Check for "textual" -> "textile" issue
    if 'textual' in source.lower() and 'textile' in target.lower():
        issues.append("Terminology error: 'textual' translated as 'textile'")

    return issues


def generate_untranslated_breakdown(
    source_content: str,
    target_content: str,
    lang: str,
    output_path: Optional[Path] = None
) -> Dict:
    """
    Generate detailed breakdown of untranslated content by node type.

    Args:
        source_content: Source markdown content
        target_content: Target markdown content
        lang: Target language
        output_path: Optional path to write breakdown JSON

    Returns:
        dict with detailed breakdown information
    """
    if not HUGO_PARSER_AVAILABLE:
        return {
            'available': False,
            'note': 'HugoParser not available, breakdown disabled'
        }

    try:
        parser = HugoParser()
        source_doc = parser.parse_string(source_content)
        target_doc = parser.parse_string(target_content)

        breakdown = {
            'available': True,
            'total_source_chars': 0,
            'total_untranslated_chars': 0,
            'untranslated_ratio': 0.0,
            'contributors': []
        }

        def normalize_text(text: str) -> str:
            """Normalize text for comparison."""
            return ' '.join(text.lower().split())

        def extract_text_from_node(node: ASTNode) -> str:
            """Extract all text content from a node."""
            if node.type == NodeType.TEXT:
                return node.raw or ''

            parts = []
            for child in node.children:
                parts.append(extract_text_from_node(child))
            return ''.join(parts)

        def get_node_type_label(node: ASTNode) -> str:
            """Get human-readable node type label."""
            if node.type == NodeType.CODE_BLOCK:
                return 'CODE_BLOCK'
            elif node.type == NodeType.CODE_SPAN:
                return 'INLINE_CODE'
            elif node.type == NodeType.PARAGRAPH:
                return 'PARAGRAPH'
            elif node.type == NodeType.HEADING:
                return 'HEADING'
            elif node.type == NodeType.LINK:
                return 'LINK_TEXT'
            elif node.type == NodeType.LIST_ITEM:
                return 'LIST_ITEM'
            elif node.type == NodeType.TABLE_CELL:
                return 'TABLE_CELL'
            else:
                return str(node.type.value)

        def is_translatable_node(node: ASTNode) -> bool:
            """Determine if node content should be translated."""
            # Code blocks and spans should NOT be translated
            if node.type in [NodeType.CODE_BLOCK, NodeType.CODE_SPAN]:
                return False
            # Link URLs should NOT be translated (but link text should)
            if node.type == NodeType.LINK:
                # For links, we check the text children, not the URL
                return True
            # Everything else (paragraphs, headings, list items, etc.) should be translated
            return True

        def match_nodes(src_nodes: List[ASTNode], tgt_nodes: List[ASTNode], path: str = ""):
            """Recursively match and compare source and target nodes."""
            for i, src_node in enumerate(src_nodes):
                node_path = f"{path}/{get_node_type_label(src_node)}[{i}]"

                # Get corresponding target node (same position)
                tgt_node = tgt_nodes[i] if i < len(tgt_nodes) else None

                # Extract text content
                src_text = extract_text_from_node(src_node)
                tgt_text = extract_text_from_node(tgt_node) if tgt_node else ""

                # Normalize for comparison
                src_norm = normalize_text(src_text)
                tgt_norm = normalize_text(tgt_text)

                # Check if translatable
                translatable = is_translatable_node(src_node)

                # Count chars
                src_chars = len(src_text)

                # Determine if untranslated (identity match)
                is_untranslated = (src_norm == tgt_norm and len(src_norm) > 0)

                # Add to totals
                breakdown['total_source_chars'] += src_chars

                if is_untranslated:
                    breakdown['total_untranslated_chars'] += src_chars

                    # Add to contributors list
                    excerpt = src_text[:120] if src_text else "(empty)"
                    reason = "identity match"

                    breakdown['contributors'].append({
                        'node_type': get_node_type_label(src_node),
                        'path': node_path,
                        'excerpt': excerpt,
                        'source_chars': src_chars,
                        'translatable': translatable,
                        'reason': reason
                    })

                # Recurse into children
                if src_node.children and tgt_node and tgt_node.children:
                    match_nodes(src_node.children, tgt_node.children, node_path)

        # Start matching from root
        match_nodes(source_doc.ast, target_doc.ast)

        # Calculate ratio
        if breakdown['total_source_chars'] > 0:
            breakdown['untranslated_ratio'] = (
                breakdown['total_untranslated_chars'] / breakdown['total_source_chars']
            )

        # Sort contributors by char count (descending)
        breakdown['contributors'].sort(key=lambda x: x['source_chars'], reverse=True)

        # Write to file if requested
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(breakdown, indent=2), encoding='utf-8')

        return breakdown

    except Exception as e:
        return {
            'available': False,
            'error': str(e)
        }


def check_excessive_untranslated(source: str, target: str, lang: str) -> Tuple[bool, float]:
    """
    Check if target contains excessive untranslated content using AST-based character analysis.

    Uses character-level identity matching on translatable content only.
    Code blocks, inline code, and other non-translatable spans are excluded.

    Args:
        source: Source text
        target: Target text
        lang: Target language

    Returns:
        (has_issue, untranslated_ratio)
    """
    # Use AST-based analysis if available
    if HUGO_PARSER_AVAILABLE:
        try:
            breakdown = generate_untranslated_breakdown(source, target, lang, output_path=None)
            if breakdown.get('available'):
                ratio = breakdown['untranslated_ratio']
                has_issue = ratio > 0.35
                return (has_issue, ratio)
        except Exception as e:
            # Fall back to simple word-based check if AST analysis fails
            print(f"WARNING: AST-based untranslated check failed: {e}", file=sys.stderr)
            print(f"Falling back to simple word-based check", file=sys.stderr)

    # Fallback: Simple word-based check (legacy)
    # This is less accurate but better than nothing
    def clean_text(text):
        # Remove code fences
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # Remove inline code
        text = re.sub(r'`[^`]+`', '', text)
        # Remove URLs
        text = re.sub(r'https?://\S+', '', text)
        # Extract words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return set(words)

    source_words = clean_text(source)
    target_words = clean_text(target)

    # Calculate overlap
    if not source_words:
        return (False, 0.0)

    overlap = source_words & target_words
    ratio = len(overlap) / len(source_words)

    # Threshold: >35% untranslated = fail
    has_issue = ratio > 0.35

    return (has_issue, ratio)


# ============================================================================
# MAIN VERIFICATION LOGIC
# ============================================================================


def verify_file(source_path: Path, target_path: Path, lang: str) -> Dict:
    """
    Verify a single translated file.

    Args:
        source_path: Path to source file
        target_path: Path to translated file
        lang: Target language (fr/de)

    Returns:
        dict with verification results
    """
    result = {
        'source': str(source_path),
        'target': str(target_path),
        'lang': lang,
        'passed': True,
        'checks': {},
        'errors': []
    }

    # Read files
    try:
        source_content = source_path.read_text(encoding='utf-8')
    except Exception as e:
        result['passed'] = False
        result['errors'].append(f"Failed to read source file: {e}")
        return result

    try:
        target_content = target_path.read_text(encoding='utf-8')
    except Exception as e:
        result['passed'] = False
        result['errors'].append(f"Failed to read target file: {e}")
        return result

    # A) Shortcodes check
    source_shortcodes = count_shortcodes(source_content)
    target_shortcodes = count_shortcodes(target_content)

    result['checks']['shortcodes'] = {
        'source': source_shortcodes,
        'target': target_shortcodes,
        'passed': source_shortcodes == target_shortcodes
    }

    if source_shortcodes != target_shortcodes:
        result['passed'] = False
        result['errors'].append(
            f"Shortcode count mismatch: source={source_shortcodes['total']}, "
            f"target={target_shortcodes['total']}"
        )

    # B) Code fences check
    source_fences = count_code_fences(source_content)
    target_fences = count_code_fences(target_content)

    result['checks']['code_fences'] = {
        'source': source_fences,
        'target': target_fences,
        'passed': (source_fences['count'] == target_fences['count'] and
                   target_fences['is_balanced'])
    }

    if source_fences['count'] != target_fences['count']:
        result['passed'] = False
        result['errors'].append(
            f"Code fence count mismatch: source={source_fences['count']}, "
            f"target={target_fences['count']}"
        )

    if not target_fences['is_balanced']:
        result['passed'] = False
        result['errors'].append("Code fences are not balanced (unclosed fence detected)")

    # C) Table rows check
    source_tables = count_table_rows(source_content)
    target_tables = count_table_rows(target_content)

    result['checks']['tables'] = {
        'source': source_tables,
        'target': target_tables,
        'passed': source_tables == target_tables
    }

    if source_tables != target_tables:
        result['passed'] = False
        result['errors'].append(
            f"Table row count mismatch: source={source_tables}, target={target_tables}"
        )

    # D) List structure check
    source_lists = count_list_markers(source_content)
    target_lists = count_list_markers(target_content)

    lists_passed = (
        source_lists['unordered'] == target_lists['unordered'] and
        source_lists['ordered'] == target_lists['ordered']
    )

    # Check nested lists preservation
    nested_preserved = True
    if source_lists['nested'] > 0 and target_lists['nested'] == 0:
        nested_preserved = False

    result['checks']['lists'] = {
        'source': source_lists,
        'target': target_lists,
        'passed': lists_passed and nested_preserved
    }

    if not lists_passed:
        result['passed'] = False
        result['errors'].append(
            f"List marker count mismatch: source={source_lists['total']}, "
            f"target={target_lists['total']}"
        )

    if not nested_preserved:
        result['passed'] = False
        result['errors'].append(
            f"Nested list structure collapsed: source had {source_lists['nested']} "
            f"nested markers, target has {target_lists['nested']}"
        )

    # Check for list item concatenation in target
    concat_issues = check_list_item_concatenation(target_content)
    if concat_issues:
        result['passed'] = False
        result['errors'].extend(concat_issues)

    # E) Line count check (>= 95%)
    source_lines = count_lines(source_content)
    target_lines = count_lines(target_content)
    line_threshold = source_lines * 0.95

    line_check_passed = target_lines >= line_threshold

    result['checks']['line_count'] = {
        'source': source_lines,
        'target': target_lines,
        'threshold': line_threshold,
        'passed': line_check_passed
    }

    if not line_check_passed:
        result['passed'] = False
        result['errors'].append(
            f"Line count too low: target={target_lines}, "
            f"threshold={line_threshold:.1f} (95% of {source_lines})"
        )

    # F) Frontmatter check
    source_fm = extract_frontmatter(source_content)
    target_fm = extract_frontmatter(target_content)

    if source_fm:
        source_keys = get_frontmatter_keys(source_fm)
        target_keys = get_frontmatter_keys(target_fm) if target_fm else set()

        keys_preserved = source_keys == target_keys

        result['checks']['frontmatter'] = {
            'source_keys': sorted(list(source_keys)),
            'target_keys': sorted(list(target_keys)),
            'passed': keys_preserved
        }

        if not keys_preserved:
            result['passed'] = False
            missing = source_keys - target_keys
            extra = target_keys - source_keys
            if missing:
                result['errors'].append(f"Frontmatter keys missing: {missing}")
            if extra:
                result['errors'].append(f"Frontmatter keys added: {extra}")
    else:
        result['checks']['frontmatter'] = {'passed': True, 'note': 'No frontmatter in source'}

    # G) Token leakage check
    leaks = check_token_leakage(target_content)

    result['checks']['token_leakage'] = {
        'leaks': leaks,
        'passed': len(leaks) == 0
    }

    if leaks:
        result['passed'] = False
        result['errors'].append(f"Token leakage detected: {', '.join(leaks)}")

    # H) AST-based markdown fidelity check (NEW - STRICT)
    ast_check = verify_ast_structural_fidelity(source_content, target_content)

    result['checks']['markdown_fidelity'] = ast_check

    if not ast_check['passed']:
        result['passed'] = False
        result['errors'].extend(ast_check['errors'])

    # Medium-level quality checks
    # Terminology guard
    term_issues = check_terminology_issues(source_content, target_content)

    result['checks']['terminology'] = {
        'issues': term_issues,
        'passed': len(term_issues) == 0
    }

    if term_issues:
        result['passed'] = False
        result['errors'].extend(term_issues)

    # Excessive untranslated check
    has_untranslated_issue, untranslated_ratio = check_excessive_untranslated(
        source_content, target_content, lang
    )

    result['checks']['untranslated'] = {
        'ratio': untranslated_ratio,
        'threshold': 0.35,
        'passed': not has_untranslated_issue
    }

    if has_untranslated_issue:
        result['passed'] = False
        result['errors'].append(
            f"Excessive untranslated content: {untranslated_ratio:.1%} of source "
            f"words remain in target (threshold: 35%)"
        )

    # Generate detailed breakdown if debug flag is set
    if os.environ.get('VERIFIER_DEBUG_UNTRANSLATED') == '1':
        breakdown_dir = Path('reports/translation_hardening/20260128-153000/phase_untranslated_ratio')
        breakdown_path = breakdown_dir / 'untranslated_breakdown.json'
        breakdown = generate_untranslated_breakdown(
            source_content, target_content, lang, breakdown_path
        )
        if breakdown.get('available'):
            print(f"\n[DEBUG] Untranslated breakdown written to: {breakdown_path}", file=sys.stderr)
            print(f"[DEBUG] Total source chars: {breakdown['total_source_chars']}", file=sys.stderr)
            print(f"[DEBUG] Untranslated chars: {breakdown['total_untranslated_chars']}", file=sys.stderr)
            print(f"[DEBUG] Untranslated ratio: {breakdown['untranslated_ratio']:.1%}", file=sys.stderr)
            print(f"[DEBUG] Top 5 contributors:", file=sys.stderr)
            for contrib in breakdown['contributors'][:5]:
                print(f"  - {contrib['node_type']}: {contrib['source_chars']} chars "
                      f"(translatable={contrib['translatable']})", file=sys.stderr)
                print(f"    Excerpt: {contrib['excerpt'][:80]}", file=sys.stderr)

    return result


def print_human_summary(result: Dict):
    """Print human-readable summary of verification."""
    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Source: {result['source']}")
    print(f"Target: {result['target']}")
    print(f"Language: {result['lang']}")
    print(f"Result: {'PASS' if result['passed'] else 'FAIL'}")
    print()

    if result['errors']:
        print("ERRORS:")
        for error in result['errors']:
            print(f"  - {error}")
        print()

    print("CHECK DETAILS:")
    for check_name, check_data in result['checks'].items():
        status = "[PASS]" if check_data.get('passed', True) else "[FAIL]"
        print(f"  {status} {check_name}")

    print("=" * 60)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='E2E single file verifier')
    parser.add_argument('--source', required=True, help='Source file path')
    parser.add_argument('--target', required=True, help='Target file path')
    parser.add_argument('--lang', required=True, choices=['fr', 'de'], help='Target language')
    parser.add_argument('--json-output', help='Write JSON report to file')
    parser.add_argument('--quiet', action='store_true', help='Suppress human summary')

    args = parser.parse_args()

    source_path = Path(args.source)
    target_path = Path(args.target)

    # Verify files exist
    if not source_path.exists():
        print(f"ERROR: Source file not found: {source_path}", file=sys.stderr)
        return 1

    if not target_path.exists():
        print(f"ERROR: Target file not found: {target_path}", file=sys.stderr)
        return 1

    # Run verification
    result = verify_file(source_path, target_path, args.lang)

    # Write JSON output
    if args.json_output:
        json_path = Path(args.json_output)
        json_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
        if not args.quiet:
            print(f"JSON report written to: {json_path}")

    # Print human summary
    if not args.quiet:
        print_human_summary(result)

    # Return exit code
    return 0 if result['passed'] else 1


if __name__ == "__main__":
    sys.exit(main())
