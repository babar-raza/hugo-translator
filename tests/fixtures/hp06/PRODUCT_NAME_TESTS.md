# HP-06 TC-00: Product Name Detection Testing

**Purpose**: Test NER (Named Entity Recognition) or simple heuristics for detecting and protecting product names, API references, and technical terms during translation.

**Goal**: Ensure terminology dictionary reduces product name corruption from ~5% (current) to <1% (target).

## Test Categories

### 1. Aspose Product Names

#### Primary Products (CRITICAL - Must Detect)

| Product Name | Expected Behavior | Priority |
|--------------|-------------------|----------|
| Aspose.Slides | Do not translate | P0 |
| Aspose.Cells | Do not translate | P0 |
| Aspose.PDF | Do not translate | P0 |
| Aspose.Words | Do not translate | P0 |
| Aspose.Email | Do not translate | P0 |
| Aspose.Imaging | Do not translate | P0 |
| Aspose.BarCode | Do not translate | P0 |

#### Product Variations (CRITICAL - Must Detect)

| Product Variation | Expected Behavior | Priority |
|-------------------|-------------------|----------|
| Aspose.Slides for .NET | Do not translate | P0 |
| Aspose.Slides for Java | Do not translate | P0 |
| Aspose.Slides for Python | Do not translate | P0 |
| Aspose.Slides for C++ | Do not translate | P0 |
| Aspose.Slides.LowCode | Do not translate | P0 |
| Aspose.Cells.LowCode | Do not translate | P0 |
| Aspose.PDF.LowCode | Do not translate | P0 |

#### Edge Cases (MEDIUM - Should Detect)

| Edge Case | Expected Behavior | Notes |
|-----------|-------------------|-------|
| Aspose.Slides | Do not translate | Exact match |
| aspose.slides | Do not translate | Case variation |
| ASPOSE.SLIDES | Do not translate | All caps |
| Aspose. Slides | Do not translate | With space (rare) |
| Aspose-Slides | Do not translate | With hyphen (rare) |

### 2. API References

#### Namespaces (CRITICAL - Must Detect)

| Namespace | Expected Behavior | Priority |
|-----------|-------------------|----------|
| Aspose.Slides | Do not translate | P0 |
| Aspose.Slides.Export | Do not translate | P0 |
| Aspose.Slides.Charts | Do not translate | P0 |
| Aspose.Slides.SmartArt | Do not translate | P0 |

#### Class Names (HIGH - Must Detect)

| Class Name | Expected Behavior | Priority |
|------------|-------------------|----------|
| Presentation | Do not translate | P0 |
| Slide | Do not translate | P0 |
| Shape | Do not translate | P0 |
| TextFrame | Do not translate | P0 |

#### Method Names (HIGH - Must Detect)

| Method Name | Expected Behavior | Priority |
|-------------|-------------------|----------|
| Presentation.Save() | Do not translate | P0 |
| Presentation.Load() | Do not translate | P0 |
| Slide.AddClone() | Do not translate | P0 |
| Shape.RemoveAt() | Do not translate | P0 |

#### Enum Values (HIGH - Must Detect)

| Enum Value | Expected Behavior | Priority |
|------------|-------------------|----------|
| SaveFormat.Pptx | Do not translate | P0 |
| SaveFormat.Pdf | Do not translate | P0 |
| SaveFormat.Odp | Do not translate | P0 |
| SaveFormat.Ppt | Do not translate | P0 |

### 3. Development Tools

#### IDEs (MEDIUM - Should Detect)

| Tool Name | Expected Behavior | Notes |
|-----------|-------------------|-------|
| Visual Studio | Do not translate | Common IDE |
| Visual Studio Code | Do not translate | Editor |
| IntelliJ IDEA | Do not translate | Java IDE |
| Eclipse | Do not translate | Java IDE |
| PyCharm | Do not translate | Python IDE |

#### Frameworks (HIGH - Should Detect)

| Framework | Expected Behavior | Notes |
|-----------|-------------------|-------|
| .NET | Do not translate | Microsoft framework |
| .NET Core | Do not translate | Cross-platform |
| .NET Framework | Do not translate | Windows framework |
| .NET 6.0 | Do not translate | Version number |
| .NET Standard | Do not translate | Library standard |

### 4. File Formats

#### Presentation Formats (HIGH - Should Detect)

| Format | Expected Behavior | Notes |
|--------|-------------------|-------|
| PPTX | Do not translate | PowerPoint 2007+ |
| PPT | Do not translate | PowerPoint 97-2003 |
| ODP | Do not translate | OpenDocument |
| PPTM | Do not translate | Macro-enabled |
| POTX | Do not translate | Template |

#### Other Formats (MEDIUM - Should Detect)

| Format | Expected Behavior | Notes |
|--------|-------------------|-------|
| PDF | Do not translate | Portable Document Format |
| HTML | Do not translate | Web format |
| SVG | Do not translate | Vector graphics |
| PNG | Do not translate | Image format |
| JPEG | Do not translate | Image format |

### 5. Negative Cases (Should Translate)

#### Common Words (CRITICAL - Must NOT Detect as Product Names)

| Word | Expected Behavior | Notes |
|------|-------------------|-------|
| presentation | TRANSLATE | Common word |
| slide | TRANSLATE | Common word |
| document | TRANSLATE | Common word |
| visual | TRANSLATE | Part of "Visual Studio" but alone should translate |
| studio | TRANSLATE | Part of "Visual Studio" but alone should translate |
| code | TRANSLATE | Part of "Visual Studio Code" but alone should translate |

#### Context-Dependent (HIGH - Complex Cases)

| Phrase | Expected Behavior | Notes |
|--------|-------------------|-------|
| a presentation | TRANSLATE | Article + common word |
| the slide | TRANSLATE | Article + common word |
| Visual Studio | Do not translate | Complete product name |
| visual interface | TRANSLATE | Not a product name |
| code example | TRANSLATE | Not referring to VS Code |

## Detection Strategies

### Strategy 1: Regex Patterns (Simple, Fast)

```python
# Aspose products
r'Aspose\.\w+'
r'Aspose\.\w+\.\w+'

# API references (code blocks/spans)
r'\w+\.\w+\(\)'  # Method calls
r'\w+\.\w+'      # Properties/classes

# Frameworks
r'\.NET( (Core|Framework|Standard|[\d.]+))?'

# Product names with "for"
r'Aspose\.\w+ for (\.NET|Java|Python|C\+\+)'
```

### Strategy 2: Dictionary Lookup (Comprehensive)

**Terminology Dictionary** (`config/terminology/aspose_products.yaml`):

```yaml
products:
  - term: "Aspose.Slides"
    category: "product"
    do_not_translate: true
    case_sensitive: false

  - term: "Aspose.Cells"
    category: "product"
    do_not_translate: true
    case_sensitive: false

  - term: "Visual Studio"
    category: "tool"
    do_not_translate: true
    case_sensitive: false
    requires_full_phrase: true  # Only detect when words are together

  - term: "Presentation"
    category: "class"
    do_not_translate: true
    context: "code"  # Only in code blocks/spans

  - term: "SaveFormat.Pptx"
    category: "enum"
    do_not_translate: true
    case_sensitive: true
```

### Strategy 3: Context-Aware Detection (Most Accurate)

**Rules**:
1. **In code blocks/spans**: Do not translate any capitalized identifiers
2. **In regular text**: Use dictionary + pattern matching
3. **Multi-word products**: Require exact phrase match (e.g., "Visual Studio" not just "Visual")
4. **Case sensitivity**: Product names are case-insensitive, API references are case-sensitive

## Test Cases

### Test Suite 1: Basic Detection

```markdown
# Input
This project uses Aspose.Slides for .NET.

# Expected Output
This project uses Aspose.Slides for .NET.
# Product name preserved

# Failure Condition
This project uses Asposa for .NET.
# Product name corrupted - TEST FAILED
```

### Test Suite 2: In-Context Detection

```markdown
# Input
Install Visual Studio and create a new Presentation.

# Expected Output
Install Visual Studio and create a new Presentation.
# Both product name and class name preserved

# Acceptable Alternative
Install Visual Studio and create a new presentation.
# Product name preserved, "Presentation" translated (acceptable if not in code context)
```

### Test Suite 3: Code Context

```markdown
# Input
Use the `SaveFormat.Pptx` option to export presentations.

# Expected Output
Use the `SaveFormat.Pptx` option to export presentations.
# Enum value in code span preserved, "presentations" translated

# Failure Condition
Use the `SaveFormat.Pptx` option to export Präsentationen.
# Corruption not expected here but shows good translation of common word
```

### Test Suite 4: Complex Nesting

```markdown
# Input
The **Aspose.Slides.LowCode** API provides simplified methods.

# Expected Output
The **Aspose.Slides.LowCode** API provides simplified methods.
# Product name preserved even inside bold formatting

# Failure Condition
The **Asposa.LowCode** API provides simplified methods.
# Product name corrupted inside formatting - TEST FAILED
```

## Expected Results

### Success Metrics

| Metric | Target | Priority |
|--------|--------|----------|
| Product name preservation | >99% | P0 |
| API reference preservation | >99% | P0 |
| False positive rate (over-protection) | <5% | P1 |
| False negative rate (missed terms) | <1% | P0 |

### Performance Metrics

| Metric | Target | Priority |
|--------|--------|----------|
| Detection latency | <1ms per term | P2 |
| Dictionary load time | <100ms | P2 |
| Memory footprint | <10MB | P2 |

## Implementation Notes

### Phase 1: Simple Regex (TC-01)

- Implement basic pattern matching for Aspose products
- Detect terms in code blocks/spans automatically
- Expected accuracy: ~80-90%

### Phase 2: Dictionary (TC-02)

- Load terminology dictionary from YAML
- Add context-aware rules
- Expected accuracy: ~95%

### Phase 3: NER (Post-HP-06)

- Use ML-based Named Entity Recognition
- Train on Aspose documentation corpus
- Expected accuracy: >99%

## Test Execution

### Manual Testing

1. Create test markdown files with all product name variations
2. Run translation pipeline
3. Compare output with expected results
4. Document any failures

### Automated Testing

```python
def test_product_name_detection():
    """Test that product names are preserved during translation."""
    test_cases = [
        ("Aspose.Slides for .NET", "Aspose.Slides for .NET"),
        ("Visual Studio 2019", "Visual Studio 2019"),
        ("SaveFormat.Pptx", "SaveFormat.Pptx"),
        # ... more test cases
    ]

    for input_text, expected_output in test_cases:
        result = detect_and_protect_terms(input_text)
        assert expected_output in result, f"Failed: {input_text}"
```

### Regression Testing

- Run test suite before and after each HP-06 test case
- Track preservation rate over time
- Alert on any degradation

## Conclusion

Product name detection is CRITICAL for HP-06 success. The combination of:
1. **Code context detection** (automatic)
2. **Terminology dictionary** (explicit)
3. **Pattern matching** (heuristic)

Should achieve >99% preservation rate for Aspose products and API references.

**Next Steps**:
1. Create `config/terminology/aspose_products.yaml` dictionary
2. Implement detection in `TextUnitExtractor` (TC-03)
3. Add unit tests for all test cases above
4. Monitor false positive/negative rates in production
