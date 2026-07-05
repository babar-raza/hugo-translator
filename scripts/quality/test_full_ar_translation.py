"""Test full Arabic translation pipeline with all fixes:
1. SSA artifact cleanup (no {\\pos} in output)
2. PascalCase preserve_patterns fix (no {PLACEHOLDER_N} for 'Methods', 'Values')
3. Pattern 4 in extractor (dotted identifier sentences not translated)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Test the NLLB SSA cleanup via loader
from src.model_runtime.loader import HuggingFaceBackend
from src.model_runtime.registry import ModelRegistry

reg = ModelRegistry()
info = reg.get_model('nllb_200_1.3b')
backend = HuggingFaceBackend(info, device='cuda')
backend.load()

test_cases = [
    ("Methods", "ar"),          # Was: Methods{\pos}(مُحملة مكان) → Fixed: الطرق
    ("Values", "ar"),           # Was: Values (مُحملة مكان) → Fixed: القيم
    ("Overview", "ar"),         # Was: Values (مُحملة مكان) → Fixed: نظرة عامة
    ("Properties", "ar"),       # Was corrupted → Fixed: خصائص
    ("Signature", "ar"),        # Column header
    ("Description", "ar"),      # Column header
]

sys.stdout.buffer.write(b"=== NLLB Arabic heading translation test ===\n")
results = backend.translate([t[0] for t in test_cases], 'en', 'ar')
for (src, _), tgt in zip(test_cases, results):
    line = f"  {src!r} -> {tgt!r}"
    has_artifact = '\\pos' in tgt or '\u0645\u0643\u0627\u0646' in tgt
    status = " [ARTIFACT!]" if has_artifact else " [OK]"
    sys.stdout.buffer.write((line + status + "\n").encode('utf-8'))

# Test Pattern 4: dotted identifier sentence should be marked non-translatable
sys.stdout.buffer.write(b"\n=== Pattern 4: dotted identifier detection ===\n")
import re
dotted_pascal_lead = r"^[A-Z][A-Za-z0-9_]+\.[A-Z][A-Za-z0-9_.]*(?:\s|$)"
test_sentences = [
    "EntityRendererKey.EntityRendererKey creates a key with given rendering features.",
    "FVector4.FVector4 initializes a new instance.",
    "Deformer.Deformer initializes a deformer with the specified name.",
    "Methods",    # Should NOT match
    "Overview",   # Should NOT match
]
for s in test_sentences:
    match = bool(re.match(dotted_pascal_lead, s))
    sys.stdout.buffer.write(f"  {s[:60]!r}: do_not_translate={match}\n".encode('utf-8'))

# Test PascalCase pattern fix
sys.stdout.buffer.write(b"\n=== Fixed PascalCase preserve_pattern ===\n")
pattern = r'^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$'
words = ['Methods', 'Values', 'Overview', 'Properties', 'BarCodeReader', 'EntityRendererKey', 'GltfImporter']
for w in words:
    match = bool(re.match(pattern, w))
    status = "PROTECTED (multi-component PascalCase)" if match else "not protected (common word)"
    sys.stdout.buffer.write(f"  {w!r}: {status}\n".encode('utf-8'))

sys.stdout.buffer.flush()
