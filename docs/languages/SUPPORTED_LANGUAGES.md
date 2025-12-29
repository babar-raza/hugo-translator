# Supported Languages

**Version:** 1.0
**Last Updated:** 2025-12-28
**Total Languages:** 36

## Overview

The Hugo Translation System supports translation from English to 36 target languages, carefully selected to cover Aspose.net's global user base with emphasis on:

- **Geographic diversity**: Europe, Asia, Middle East, Americas
- **Script diversity**: Latin, Cyrillic, Arabic, CJK, Indic, Greek, Hebrew, Thai
- **Market coverage**: Top languages by developer population and technical documentation demand
- **Resource balance**: Mix of high-resource (fr, de, es) and low-resource (fa, th, vi) languages

## Language List

| ISO | Language | Native Name | Script | Direction | Family |
|-----|----------|-------------|--------|-----------|--------|
| ar | Arabic | العربية | Arab | RTL | Afro-Asiatic |
| bg | Bulgarian | Български | Cyrl | LTR | Indo-European |
| ca | Catalan | Català | Latn | LTR | Indo-European |
| cs | Czech | Čeština | Latn | LTR | Indo-European |
| da | Danish | Dansk | Latn | LTR | Indo-European |
| de | German | Deutsch | Latn | LTR | Indo-European |
| el | Greek | Ελληνικά | Grek | LTR | Indo-European |
| es | Spanish | Español | Latn | LTR | Indo-European |
| fa | Persian | فارسی | Arab | RTL | Indo-European |
| fi | Finnish | Suomi | Latn | LTR | Uralic |
| fr | French | Français | Latn | LTR | Indo-European |
| he | Hebrew | עברית | Hebr | RTL | Afro-Asiatic |
| hi | Hindi | हिन्दी | Deva | LTR | Indo-European |
| hr | Croatian | Hrvatski | Latn | LTR | Indo-European |
| hu | Hungarian | Magyar | Latn | LTR | Uralic |
| id | Indonesian | Bahasa Indonesia | Latn | LTR | Austronesian |
| it | Italian | Italiano | Latn | LTR | Indo-European |
| ja | Japanese | 日本語 | Jpan | LTR | Japonic |
| ko | Korean | 한국어 | Kore | LTR | Koreanic |
| lt | Lithuanian | Lietuvių | Latn | LTR | Indo-European |
| lv | Latvian | Latviešu | Latn | LTR | Indo-European |
| ms | Malay | Bahasa Melayu | Latn | LTR | Austronesian |
| nl | Dutch | Nederlands | Latn | LTR | Indo-European |
| no | Norwegian | Norsk | Latn | LTR | Indo-European |
| pl | Polish | Polski | Latn | LTR | Indo-European |
| pt | Portuguese | Português | Latn | LTR | Indo-European |
| ro | Romanian | Română | Latn | LTR | Indo-European |
| ru | Russian | Русский | Cyrl | LTR | Indo-European |
| sk | Slovak | Slovenčina | Latn | LTR | Indo-European |
| sr | Serbian | Српски | Cyrl | LTR | Indo-European |
| sv | Swedish | Svenska | Latn | LTR | Indo-European |
| th | Thai | ไทย | Thai | LTR | Tai-Kadai |
| tr | Turkish | Türkçe | Latn | LTR | Turkic |
| uk | Ukrainian | Українська | Cyrl | LTR | Indo-European |
| vi | Vietnamese | Tiếng Việt | Latn | LTR | Austroasiatic |
| zh | Chinese | 中文 | Hans | LTR | Sino-Tibetan |

## Script Distribution

| Script Family | Count | Languages |
|---------------|-------|-----------|
| Latin (Latn) | 24 | ca, cs, da, de, es, fi, fr, hr, hu, id, it, lt, lv, ms, nl, no, pl, pt, ro, sk, sv, tr, vi |
| Cyrillic (Cyrl) | 4 | bg, ru, sr, uk |
| Arabic (Arab) | 2 | ar, fa |
| CJK | 3 | zh (Hans), ja (Jpan), ko (Kore) |
| Indic (Deva) | 1 | hi |
| Greek (Grek) | 1 | el |
| Hebrew (Hebr) | 1 | he |
| Thai | 1 | th |

## Text Direction

- **Left-to-Right (LTR):** 33 languages
- **Right-to-Left (RTL):** 3 languages (ar, fa, he)

## Language Family Distribution

- **Indo-European:** 26 languages (majority of European + Persian, Hindi)
- **Uralic:** 2 languages (fi, hu)
- **Sino-Tibetan:** 1 language (zh)
- **Japonic:** 1 language (ja)
- **Koreanic:** 1 language (ko)
- **Afro-Asiatic:** 2 languages (ar, he)
- **Austronesian:** 2 languages (id, ms)
- **Austroasiatic:** 1 language (vi)
- **Tai-Kadai:** 1 language (th)
- **Turkic:** 1 language (tr)

## Selection Rationale

### High-Priority Languages (P0)
Major markets with large developer populations:
- **Western Europe:** de, fr, es, it, nl
- **Eastern Europe:** pl, ru, uk, cs
- **Asia-Pacific:** zh, ja, ko
- **Romance:** pt (Brazil), es (Latin America)

### Medium-Priority Languages (P1)
Strategic markets and emerging economies:
- **Middle East:** ar, fa, he, tr
- **South Asia:** hi
- **Southeast Asia:** id, ms, th, vi
- **Nordics:** sv, da, no, fi
- **Balkans:** bg, hr, sr, ro, el

### Low-Resource Coverage
Languages with limited MT resources but strategic value:
- **Baltics:** lt, lv
- **Isolates:** ca, hu
- **Regional:** sk

## Technical Considerations

### Character Encoding
All languages use **UTF-8** encoding with full Unicode support.

### Tokenization Challenges
- **Agglutinative:** fi, hu, tr (long compound words)
- **No word boundaries:** zh, ja, th (require subword tokenization)
- **Diacritics:** cs, pl, ro, vi (must preserve accents)
- **Bidirectional text:** ar, fa, he (RTL within LTR context)

### Translation Model Support
See [config/model_registry.yaml](../../config/model_registry.yaml) for model coverage per language.

**Multilingual Models:**
- M2M100 (418M, 1.2B): All 36 languages
- NLLB-200 (600M, 1.3B): All 36 languages

**Specialized Models:**
- Opus-MT: High-quality for specific pairs (en-fr, en-de, en-es, etc.)
- Marian: Romance language group (fr, es, it, pt, ro)

## Data Sources

Benchmark corpus extracted from real Aspose.net content (read-only):
- **Source:** `D:\onedrive\Documents\GitHub\aspose.net\content`
- **Content types:** Technical documentation, API references, tutorials, blog posts
- **Sampling strategy:** Stratified by content type and complexity

## Quality Assurance

All 36 languages undergo:
- **Automated testing:** Bidirectional encoding checks, tokenization validation
- **Benchmark coverage:** CPU and GPU performance testing
- **Quality metrics:** BLEU scores against reference translations (where available)
- **Human evaluation:** Periodic spot-checks on technical terminology

## Usage

### CLI Query
```bash
# List all supported languages
python -c "import yaml; langs = yaml.safe_load(open('config/target_languages.yaml'))['languages']; print('\\n'.join(f\"{l['iso_code']}: {l['name']}\" for l in langs))"

# Count languages
python -c "import yaml; print(len(yaml.safe_load(open('config/target_languages.yaml'))['languages']))"
```

### Programmatic Access
```python
import yaml

with open('config/target_languages.yaml') as f:
    config = yaml.safe_load(f)

# Get all language codes
lang_codes = [lang['iso_code'] for lang in config['languages']]

# Filter RTL languages
rtl_languages = [lang for lang in config['languages'] if lang['direction'] == 'rtl']

# Group by script
from collections import defaultdict
by_script = defaultdict(list)
for lang in config['languages']:
    by_script[lang['script']].append(lang['iso_code'])
```

## Maintenance

### Adding a Language
1. Update `config/target_languages.yaml`
2. Ensure model coverage exists (update `config/model_registry.yaml` if needed)
3. Validate schema: `jsonschema -i config/target_languages.yaml config/schemas/language.schema.json`
4. Update this documentation
5. Run language coverage validation: `python scripts/validate_language_coverage.py`

### Removing a Language
1. Check for existing translated content (will be orphaned)
2. Remove from `config/target_languages.yaml`
3. Update benchmarks database to exclude removed language
4. Update documentation

## References

- **ISO 639-1:** https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
- **ISO 15924:** https://en.wikipedia.org/wiki/ISO_15924
- **Aspose Locales:** Internal Aspose.net locale mapping
- **NLLB-200 Coverage:** https://github.com/facebookresearch/fairseq/tree/nllb
- **M2M100 Coverage:** https://github.com/facebookresearch/fairseq/tree/main/examples/m2m_100

---

**Revision History:**
- v1.0 (2025-12-28): Initial 36-language specification
