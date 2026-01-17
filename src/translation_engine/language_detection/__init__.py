"""
Language detection module for translation validation.

Provides FastText-based language detection with adaptive similarity learning
to minimize false positives for similar language groups (Romance, Cyrillic, etc.).
"""

from .fasttext_detector import FastTextDetector
from .similarity_tracker import SimilarityTracker

__all__ = ["FastTextDetector", "SimilarityTracker"]
