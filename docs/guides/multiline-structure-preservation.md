# Multiline Structure Preservation (MSP-02)

**Status**: Core feature - automatically enabled for multiline content

## Overview

Multiline structure preservation ensures that when translating content containing multiple lines (like lists, indented text, or structured content), the formatting and structure are maintained exactly in the translated output.

This prevents common issues where translation models:
- Lose indentation
- Break bullet point alignment
- Merge or split lines inappropriately
- Corrupt structured content

## How It Works

### Detection

The system automatically detects multiline content:

```python
# Automatic detection
if '\n' in text or '\\n' in text:
    # Use multiline handler
    result = multiline_handler.translate(text, translate_fn)
```

### Processing Pipeline

```
Multiline Content Detected
        ↓
Parse into LineInfo objects
        ↓
Translate each line individually
        ↓
Reassemble with preserved structure
        ↓
Return formatted result
```

### Line Parsing

Each line is analyzed for structure:

```python
@dataclass
class LineInfo:
    original: str      # Complete original line
    indent: str        # Leading whitespace
    prefix: str        # Bullet/numbering ("- ", "1. ", "> ")
    content: str       # Translatable text
    is_empty: bool     # Empty line flag
```

**Examples**:

| Original Line | Parsed Structure |
|---------------|------------------|
| `  - List item` | `indent="  "`, `prefix="- "`, `content="List item"` |
| `    1. Step one` | `indent="    "`, `prefix="1. "`, `content="Step one"` |
| `> Block quote` | `indent=""`, `prefix="> "`, `content="Block quote"` |
| `    Regular text` | `indent="    "`, `prefix=""`, `content="Regular text"` |

## Supported Structures

### Bullet Lists

**Input**:
```markdown
- First item
- Second item with longer text
  that wraps to multiple lines
- Third item
```

**Output** (preserved):
```markdown
- Premier élément
- Deuxième élément avec un texte plus long
  qui s'enroule sur plusieurs lignes
- Troisième élément
```

### Numbered Lists

**Input**:
```markdown
1. Install dependencies
2. Configure settings
   - Sub-item one
   - Sub-item two
3. Run the application
```

**Output** (preserved):
```markdown
1. Installer les dépendances
2. Configurer les paramètres
   - Sous-élément un
   - Sous-élément deux
3. Exécuter l'application
```

### Block Quotes

**Input**:
```markdown
> This is a block quote
> that spans multiple lines
> with proper formatting
```

**Output** (preserved):
```markdown
> Ceci est une citation en bloc
> qui s'étend sur plusieurs lignes
> avec un formatage approprié
```

### Mixed Indentation

**Input**:
```markdown
Top level text
    Indented content
        Deeply nested
    Back to medium indent
Regular text again
```

**Output** (preserved):
```markdown
Texte de niveau supérieur
    Contenu indenté
        Profondément imbriqué
    Retour à l'indentation moyenne
Texte régulier à nouveau
```

## Technical Details

### Structure Preservation Guarantees

1. **Line Count**: Input lines = output lines
2. **Indentation**: Exact whitespace preserved
3. **Prefixes**: Bullets, numbers, quotes maintained
4. **Empty Lines**: Preserved as-is (no translation)

### Error Handling

**Translation Failure on Single Line**:
- Logs warning
- Keeps original content
- Preserves structure

**Structure Drift Detection**:
```python
if source_line_count != translated_line_count:
    logger.warning(f"Structure drift: {source_line_count} -> {translated_line_count}")
```

### Performance Impact

- **Minimal overhead**: Only activated for multiline content
- **Per-line translation**: May increase API calls for long lists
- **Memory efficient**: Processes lines sequentially

## Configuration

### Automatic Activation

No configuration required - automatically enabled for content with newlines.

### Advanced Options

```python
from src.translation_engine.handlers import MultilineHandler

handler = MultilineHandler(
    normalize_escapes=True  # Convert \\n to actual newlines
)
```

### Integration Points

Used automatically in:
- **TranslationEngine**: For segments containing newlines
- **AST Translation**: For complex document structures
- **Batch Processing**: When multiline content detected

## Common Issues and Solutions

### Structure Drift

**Symptom**: Different number of lines in input vs output

**Cause**: Translation model adding/removing line breaks

**Solution**: Monitor logs, consider content preprocessing

### Indentation Loss

**Symptom**: Translated content loses indentation

**Cause**: Model not preserving whitespace

**Solution**: MSP-02 handles this automatically

### Bullet Point Corruption

**Symptom**: `- ` becomes `-` or other variations

**Cause**: Model treating bullet as part of content

**Solution**: MSP-02 preserves bullets separately

### Escaped Newlines

**Symptom**: `\\n` sequences not converted to actual newlines

**Configuration**:
```python
handler = MultilineHandler(normalize_escapes=True)  # Default: True
```

## Examples

### Complete Translation Workflow

```python
from src.translation_engine.handlers import MultilineHandler

def translate_line(text: str) -> str:
    # Your translation function
    return my_model.translate(text, "en", "fr")

handler = MultilineHandler()

# Multiline content
content = """- Install Python
- Configure environment
  - Set PYTHONPATH
  - Install dependencies
- Run application"""

# Translate with structure preservation
result = handler.translate(content, translate_line)

print(result.translated_text)
# - Installer Python
# - Configurer l'environnement
#   - Définir PYTHONPATH
#   - Installer les dépendances
# - Exécuter l'application

print(f"Structure preserved: {result.structure_preserved}")
# Structure preserved: True
```

### Integration with Translation Engine

The multiline handler is automatically used:

```python
# In TranslationEngine._translate_with_multiline_support()
if self.multiline_handler.is_multiline(segment.source_text):
    result = self.multiline_handler.translate(
        segment.source_text, translate_line
    )
    translated_texts.append(result.translated_text)
```

## Best Practices

### Content Preparation

**Avoid Mixed Structures**:
```markdown
<!-- Avoid -->
- Item 1
  Continued on next line
- Item 2

<!-- Prefer -->
- Item 1 continued on next line
- Item 2
```

**Use Consistent Formatting**:
```markdown
<!-- Good -->
- First item
- Second item

<!-- Avoid mixing -->
- First item
* Second item
```

### Monitoring

**Track Structure Preservation**:
```python
result = handler.translate(text, translate_fn)
if not result.structure_preserved:
    logger.warning(f"Structure drift in content: {result.line_count_source} -> {result.line_count_translated}")
```

**Log Line-by-Line**:
```python
# Enable debug logging to see per-line processing
import logging
logging.getLogger('src.translation_engine.handlers.multiline_handler').setLevel(logging.DEBUG)
```

### Performance Optimization

**Batch Similar Content**:
- Group similar multiline content
- Process in batches when possible
- Monitor translation API usage

## Troubleshooting

### Debug Mode

Enable detailed logging:

```python
import logging
logging.getLogger('src.translation_engine.handlers.multiline_handler').setLevel(logging.DEBUG)
```

**Sample Debug Output**:
```
DEBUG: Line 0: translated 'Install Python' -> 'Installer Python'
DEBUG: Line 1: translated 'Configure environment' -> 'Configurer l'environnement'
DEBUG: Line 2: no content, preserved structure
DEBUG: Line 3: translated 'Set PYTHONPATH' -> 'Définir PYTHONPATH'
```

### Manual Testing

Test multiline handling independently:

```python
from src.translation_engine.handlers import MultilineHandler

handler = MultilineHandler()

# Test content
test_text = "- Item 1\\n- Item 2\\n  Continued"

# Parse lines
lines = handler.parse_lines(test_text)
for line in lines:
    print(f"Line {line.line_index}: indent='{line.indent}', prefix='{line.prefix}', content='{line.content}'")

# Translate
result = handler.translate(test_text, lambda x: f"[{x}]")
print(f"Result: {repr(result.translated_text)}")
```

### Common Error Patterns

| Issue | Symptom | Solution |
|-------|---------|----------|
| **Line count mismatch** | Different input/output lines | Check translation function |
| **Indentation loss** | Structure not preserved | MSP-02 handles automatically |
| **Bullet corruption** | `- ` becomes `-` | MSP-02 preserves prefixes |
| **Empty line removal** | Missing blank lines | Handled automatically |

## Future Enhancements

- **Nested structure detection**: Handle complex nested lists
- **Markdown-aware parsing**: Better handling of code blocks in lists
- **Custom prefix patterns**: Configurable bullet/numbering patterns
- **Structure validation**: Post-translation structure checking

## Related Documentation

- [Translation Workflows](translation-workflows.md) - How multiline fits in overall process
- [Architecture: Translation Engine](../architecture/translation-engine.md) - Engine integration
- [Validation Guide](quality-improvement.md) - Quality checks that work with multiline
- [API Reference](../reference/api.md) - MultilineHandler class
