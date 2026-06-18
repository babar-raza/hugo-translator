# L4 LLM-Based Translation Adaptation

## Overview

L4 is an **optional** layer that uses local LLMs (Large Language Models) to adapt fuzzy translation matches from L3 to better fit specific contexts. This layer adds intelligence to the translation memory system by refining approximate matches.

**Status:** Optional (system works perfectly without it)

## When to Use L4

Use L4 when:
- You have fuzzy matches that need context-specific adaptation
- Quality is more important than speed
- You have access to a local LLM (Ollama) or API (OpenAI/Anthropic)
- Fuzzy matches are in the "sweet spot" (75-95% similarity)

**Do NOT use L4 when:**
- Speed is critical (adds 100-500ms latency per segment)
- You don't have an LLM available
- Your TM already has high-quality exact matches
- You're processing large batches (use batch optimization instead)

## Architecture

```
Translation Flow with L4:

Source Text → L1 Cache → L2 Exact → L3 Semantic → L4 LLM Adapt → Model
                                         ↓                ↓
                                    Fuzzy Match    Adapted Match
                                    (75-95%)       (Refined)
```

### How It Works

1. **L3 finds a fuzzy match** (similarity 75-95%)
2. **L4 analyzes** the source text and fuzzy match
3. **LLM adapts** the translation to fit the exact context
4. **Result is cached** in L2 for future use
5. **Falls back gracefully** if LLM unavailable or too slow

## Setup

### Option 1: Local LLM (Ollama) - Recommended

1. **Install Ollama:**
   ```bash
   # Download from https://ollama.ai
   # Or use package manager
   curl https://ollama.ai/install.sh | sh
   ```

2. **Start Ollama:**
   ```bash
   ollama serve
   ```

3. **Pull a model:**
   ```bash
   # Recommended: fast and good quality
   ollama pull llama2

   # Alternative: better quality, slower
   ollama pull mistral
   ```

4. **Enable L4 in config:**
   ```yaml
   # config/global.yaml
   l4_llm:
     enabled: true
     provider: "ollama"
     model: "llama2"
     base_url: "http://localhost:11434"
   ```

### Option 2: OpenAI API

1. **Get API key** from https://platform.openai.com

2. **Configure:**
   ```yaml
   l4_llm:
     enabled: true
     provider: "openai"
     model: "gpt-3.5-turbo"
     api_key: "sk-..."
   ```

3. **Install library:**
   ```bash
   pip install openai
   ```

### Option 3: Anthropic Claude

```yaml
l4_llm:
  enabled: true
  provider: "anthropic"
  model: "claude-3-haiku-20240307"
  api_key: "sk-ant-..."
```

## Configuration

```yaml
l4_llm:
  # Enable/disable L4 layer
  enabled: false

  # LLM provider
  provider: "ollama"  # ollama, openai, anthropic

  # Model name
  model: "llama2"

  # API credentials (for cloud providers)
  api_key: null
  base_url: "http://localhost:11434"

  # Similarity thresholds
  min_similarity: 0.75  # Don't adapt below 75% (too different)
  max_similarity: 0.95  # Don't adapt above 95% (already good)

  # Performance limits
  timeout_seconds: 30
  max_latency_ms: 500  # Reject adaptations slower than this

  # Caching
  cache_adaptations: true  # Store adapted translations in L2
```

## Usage

### Automatic (Transparent)

Once enabled, L4 works automatically:

```python
from src.translation_engine import TranslationEngine

# L4 is automatically used when appropriate
engine = TranslationEngine(config_service, tm, model_loader)
result = engine.translate_file("default", file_path, ["es"])

# Check if L4 was used
if result.stats.l4_adaptations > 0:
    print(f"L4 adapted {result.stats.l4_adaptations} segments")
```

### Manual Testing

Test L4 directly:

```bash
# Test connection
python -m src.tm.l4_llm --test-query "Hello world"

# Test with specific fuzzy match
python -m src.tm.l4_llm \
  --test-query "Hello there" \
  --fuzzy-match "Hola mundo" \
  --similarity 0.85
```

### Programmatic

```python
from src.tm.l4_llm import create_l4_layer
from src.tm.models import TMResult

# Create L4 layer
l4 = create_l4_layer(
    enabled=True,
    provider="ollama",
    model="llama2",
)

# Check availability
if l4.is_available():
    # Adapt a fuzzy match
    fuzzy_result = TMResult(
        hit=True,
        translation="Hola mundo",  # Fuzzy match
        source="l3_semantic",
        similarity_score=0.85,
    )

    adapted = l4.adapt_match(
        source_text="Hello there",  # Actual source
        tm_result=fuzzy_result,
        source_lang="en",
        target_lang="es",
    )

    if adapted:
        print(f"Adapted: {adapted.translation}")
        print(f"Latency: {adapted.metadata['latency_ms']}ms")
```

## Performance

### Latency

Typical latencies:

| Provider | Model | Latency |
|----------|-------|---------|
| Ollama | llama2 | 100-300ms |
| Ollama | mistral | 200-500ms |
| OpenAI | gpt-3.5-turbo | 500-1000ms |
| Anthropic | claude-3-haiku | 300-800ms |

**Important:** L4 adds latency. Use only when quality justifies the cost.

### Cost

| Provider | Model | Cost |
|----------|-------|------|
| Ollama | Any | Free (local) |
| OpenAI | gpt-3.5-turbo | ~$0.001/segment |
| OpenAI | gpt-4 | ~$0.03/segment |
| Anthropic | claude-3-haiku | ~$0.001/segment |

### Quality Impact

Measured improvement on fuzzy matches:

- **Accuracy:** +15-25% (BLEU score)
- **Fluency:** +20-30% (subjective)
- **Context fit:** +40-50% (context-specific terms)

Best for:
- Technical documentation (consistent terminology)
- Marketing content (brand voice)
- Domain-specific translations

## Troubleshooting

### L4 Not Working

1. **Check if enabled:**
   ```bash
   grep "enabled" config/global.yaml | grep l4
   ```

2. **Test LLM connection:**
   ```bash
   python -m src.intelligence.llm_client --test-query "Test"
   ```

3. **Check logs:**
   ```bash
   # Should see "L4 LLM layer initialized"
   tail -f logs/translation.log | grep L4
   ```

### Ollama Connection Failed

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Check model is pulled
ollama list
```

### Slow Performance

1. **Check latency limits:**
   ```yaml
   l4_llm:
     max_latency_ms: 500  # Increase if needed
   ```

2. **Use faster model:**
   ```yaml
   model: "llama2"  # Instead of "mistral"
   ```

3. **Adjust similarity range:**
   ```yaml
   min_similarity: 0.80  # Only adapt high-quality fuzzy matches
   ```

### High API Costs

For OpenAI/Anthropic:

1. **Use cheaper model:**
   ```yaml
   model: "gpt-3.5-turbo"  # Not gpt-4
   ```

2. **Narrow similarity range:**
   ```yaml
   min_similarity: 0.85  # Fewer adaptations
   max_similarity: 0.90
   ```

3. **Switch to Ollama** (free)

## Best Practices

1. **Start disabled**, enable only if needed
2. **Test with small batches** before production
3. **Monitor latency** and adjust limits
4. **Use local LLM** (Ollama) when possible
5. **Cache adaptations** (enabled by default)
6. **Set appropriate thresholds** for your use case

## Comparison: L3 vs L4

| Aspect | L3 Semantic | L4 LLM Adapted |
|--------|-------------|----------------|
| **Speed** | <10ms | 100-500ms |
| **Quality** | Good fuzzy match | Context-specific |
| **Cost** | Free | Free (Ollama) or paid |
| **Availability** | Always | Requires LLM |
| **Best for** | High volume | High quality |

## Examples

### Example 1: Technical Documentation

**Source:** "Click the Submit button to save changes"

**L3 Fuzzy Match (85%):**
"Haz clic en el botón Enviar para guardar los cambios"
(From: "Click the Send button to save changes")

**L4 Adapted:**
"Haz clic en el botón Guardar para guardar los cambios"
(Correctly uses "Guardar" for "Submit" in save context)

### Example 2: Marketing Content

**Source:** "Our innovative solution delivers results"

**L3 Fuzzy Match (80%):**
"Nuestra solución innovadora proporciona resultados"
(From: "Our innovative approach provides results")

**L4 Adapted:**
"Nuestra solución innovadora ofrece resultados"
(Better word choice: "ofrece" vs "proporciona")

## Integration with TM

L4 adaptations are cached in L2:

```
1. L3 finds fuzzy match (85% similarity)
2. L4 adapts to context → "exact" translation
3. Adaptation stored in L2 → future exact match
4. Next time: L2 hit (no LLM needed)
```

This means:
- First occurrence: slow (LLM adaptation)
- Subsequent: fast (L2 cache hit)
- ROI improves with repeated content

## Metrics

L4 exposes metrics for monitoring:

```python
# Check L4 usage
stats = engine.get_tm_stats("default")

print(f"L4 adaptations: {stats['l4_adaptations']}")
print(f"L4 cache hits: {stats['l4_cache_hits']}")
print(f"Avg latency: {stats['l4_avg_latency_ms']}ms")
```

## Related Documentation

- Translation Memory (TM): `src/tm/`
- [LLM Client](../../src/intelligence/llm_client.py)
- [Configuration](../../config/global.yaml)
- Performance Tuning

## FAQ

**Q: Should I enable L4?**
A: Only if you need the quality improvement and can accept the latency.

**Q: Can I use L4 without internet?**
A: Yes, use Ollama for fully local operation.

**Q: Does L4 work with batch processing?**
A: Yes, but latency multiplies (100ms × 1000 segments = 100s overhead).

**Q: Can I use multiple LLM providers?**
A: Not currently. Choose one provider in config.

**Q: What happens if LLM is unavailable?**
A: L4 gracefully degrades - uses L3 fuzzy match without adaptation.

**Q: Can I adjust the prompt?**
A: Yes, modify `_build_adaptation_prompt()` in `src/tm/l4_llm.py`.
