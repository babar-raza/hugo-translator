# Model Download Plan for 36 Language Coverage

**Version:** 1.0
**Last Updated:** 2025-12-28

## Objective

Download minimal set of models to cover all 36 target languages while optimizing for:
- Minimal total download size
- Maximum language coverage
- Support for both CPU and GPU deployment
- Production-ready performance

## Strategy

### 1. Prioritize Multilingual Models

Large multilingual models provide the best coverage-to-size ratio:

- **NLLB-200** (1.3B params, 5.2GB): Covers all 200 languages including our 36 targets
- **M2M100** (1.2B params, 4.8GB): Covers 100 languages including most of our targets

### 2. Use Specialized Models for Gaps

For languages not covered by multilingual models, use Helsinki-NLP opus-mt models:
- Smaller size (~300MB each)
- High quality for specific language pairs
- CPU-friendly

### 3. Add Production-Optimized Versions

For CPU production deployments:
- CTranslate2 INT8 quantized models
- 50% smaller size
- 2-4x faster inference
- Minimal quality loss (<1% BLEU drop)

### 4. Balance Quality vs Size

**Minimum Profile** (1 model):
- NLLB-200 1.3B: Covers all 36 languages (5.2GB)

**Recommended Profile** (2 models):
- NLLB-200 1.3B: Full coverage (5.2GB)
- NLLB-200 1.3B CT2 INT8: CPU optimization (2.6GB)
- **Total: 7.8GB**

**Full Profile** (10+ models):
- Multilingual: NLLB-200, M2M100
- Specialized: opus-mt for high-value languages
- Optimized: CT2 INT8 variants
- **Total: ~30-50GB**

## Gap Analysis Process

Run the gap analysis script to identify missing models:

```bash
python scripts/models/find_missing_models.py
```

This script:
1. Loads current model registry (`config/model_registry.yaml`)
2. Loads target languages (`config/target_languages.yaml`)
3. Identifies languages without model coverage
4. Recommends optimal models to download
5. Outputs prioritized download plan to `data/model_download_plan.json`

## Download Execution

Execute the download plan:

```bash
# Download all recommended models
python scripts/models/download_models.py --all

# Download specific model
python scripts/models/download_models.py --model nllb_200_1.3b

# Force re-download
python scripts/models/download_models.py --model nllb_200_1.3b --force
```

## Verification

After downloading, verify all models:

```bash
# Verify specific model
python scripts/verify_models.py --model nllb_200_1.3b

# Verify all models
python scripts/verify_models.py --all
```

## Disk Space Requirements

| Profile | Models | Total Size | Languages Covered |
|---------|--------|------------|-------------------|
| Minimal | 1 (NLLB) | 5.2 GB | 36/36 (100%) |
| Recommended | 2 (NLLB + CT2) | 7.8 GB | 36/36 (100%) |
| Extended | 5-10 | 15-25 GB | 36/36 (100%) |
| Full | 20+ | 40-60 GB | 36/36 (100%) |

## License Compliance

All recommended models use permissive licenses:
- **MIT**: M2M100 models
- **CC-BY-4.0**: Helsinki-NLP opus-mt models
- **CC-BY-NC-4.0**: NLLB-200 models (non-commercial use)

Note: NLLB-200 license restricts commercial use. For commercial deployments, use M2M100 or opus-mt models instead.

## Troubleshooting

### Insufficient Disk Space

If disk space is limited:
1. Download only NLLB-200 1.3B CT2 INT8 (2.6GB) for CPU deployment
2. Stream models from HuggingFace Hub without local storage (slower)
3. Use smaller opus-mt models for high-priority languages only

### Download Interrupted

The download system supports resume:
```bash
# Resume interrupted download
python scripts/models/download_models.py --model nllb_200_1.3b
```

### Model Verification Fails

Re-download with force flag:
```bash
python scripts/models/download_models.py --model nllb_200_1.3b --force
```

## Next Steps

After successful download and verification:
1. Update model registry with local paths
2. Run benchmarks on all models (CPU and GPU)
3. Compare quality metrics (BLEU, chrF)
4. Select optimal model for each deployment scenario
5. Document performance characteristics

## References

- **NLLB Paper**: https://arxiv.org/abs/2207.04672
- **M2M100 Paper**: https://arxiv.org/abs/2010.11125
- **Opus-MT Models**: https://github.com/Helsinki-NLP/Opus-MT
- **CTranslate2**: https://opennmt.net/CTranslate2/
- **HuggingFace Hub**: https://huggingface.co/models

---

**Auto-generated recommendations**: Run `python scripts/models/find_missing_models.py` for current recommendations based on actual model registry state.
