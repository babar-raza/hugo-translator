"""Test NLLB translation of API reference heading words after SSA artifact fix."""
import sys
sys.path.insert(0, '.')
from src.model_runtime.loader import HuggingFaceBackend
from src.model_runtime.registry import ModelRegistry

reg = ModelRegistry()
info = reg.get_model('nllb_200_1.3b')
backend = HuggingFaceBackend(info, device='cuda')
backend.load()

test_phrases = [
    'Methods',
    'Overview',
    'Properties',
    'Signature',
    'Description',
    'EntityRendererKey.EntityRendererKey creates a key with given rendering features and a name.',
]
results = backend.translate(test_phrases, 'en', 'ar')
for src, tgt in zip(test_phrases, results):
    sys.stdout.buffer.write(f'{src!r}\n  -> {tgt!r}\n'.encode('utf-8'))
sys.stdout.buffer.flush()
