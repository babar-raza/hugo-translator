#!/bin/bash
PYTHONPATH="C:/Users/prora/AppData/Roaming/Python/Python313/site-packages" \
python -m src.cli \
  --site kb.aspose.net.words \
  --target-langs el \
  --input "c:/Users/prora/OneDrive/Documents/GitHub/aspose.net/content/kb.aspose.net/words/en/how-to-remove-blank-word-pages-csharp.md" \
  --force-retranslate \
  --log-level DEBUG 2>&1 | head -300
