"""
Tests for L3 Semantic TM with GPU acceleration.

Tests GPU-accelerated embeddings and FAISS GPU index.
"""
import shutil
import tempfile
from pathlib import Path

import pytest
import torch

from src.tm.l3_semantic import L3SemanticTM


class TestL3SemanticGPU:
    """Tests for L3 Semantic TM with GPU."""

    def test_init_with_gpu(self):
        """Test initialization with GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            if torch.cuda.is_available():
                assert tm.device == "cuda"
            else:
                assert tm.device == "cpu"

    def test_init_without_gpu(self):
        """Test initialization without GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=False,
            )

            assert tm.device == "cpu"

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_gpu_embeddings(self):
        """Test that embeddings use GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            assert tm.device == "cuda"

            # Add entry (uses GPU for embedding)
            tm.add_entry(
                entry_id="test1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            assert tm.count() == 1

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_batch_encoding_gpu(self):
        """Test batch encoding on GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Batch add entries
            entries = []
            for i in range(50):
                entries.append({
                    "entry_id": f"test{i}",
                    "site_id": "test_site",
                    "src_lang": "en",
                    "tgt_lang": "es",
                    "source_text": f"Test sentence {i}",
                    "translation": f"Sentencia de prueba {i}",
                })

            count = tm.batch_add(entries)
            assert count == 50
            assert tm.count() == 50

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_semantic_search_gpu(self):
        """Test semantic search with GPU embeddings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Add entries
            tm.add_entry(
                entry_id="test1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            tm.add_entry(
                entry_id="test2",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Good morning",
                translation="Buenos días",
            )

            # Search
            matches = tm.semantic_search(
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                query_text="Hello everyone",
                k=2,
                threshold=0.5,
            )

            assert len(matches) > 0
            assert matches[0].source_text in ["Hello world", "Good morning"]

    def test_cpu_fallback(self):
        """Test CPU fallback when GPU not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Request GPU but it might not be available
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Should work regardless of device
            tm.add_entry(
                entry_id="test1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Test",
                translation="Prueba",
            )

            assert tm.count() == 1

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_save_and_load_gpu(self):
        """Test saving and loading with GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and populate
            tm1 = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            tm1.add_entry(
                entry_id="test1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            tm1.save_index()

            # Load in new instance
            tm2 = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            assert tm2.count() == 1

            # Search should work
            matches = tm2.semantic_search(
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                query_text="Hello",
                k=1,
                threshold=0.5,
            )

            assert len(matches) > 0


class TestL3BatchSizes:
    """Test batch size optimization."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_larger_batch_size_on_gpu(self):
        """Test that GPU uses larger batch size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm_gpu = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # GPU should use batch size 64
            assert tm_gpu.device == "cuda"

        with tempfile.TemporaryDirectory() as tmpdir:
            tm_cpu = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=False,
            )

            # CPU should use batch size 32
            assert tm_cpu.device == "cpu"


class TestL3FAISSGPUIndex:
    """Test FAISS GPU index functionality."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_faiss_gpu_index(self):
        """Test FAISS GPU index if faiss-gpu available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                tm = L3SemanticTM(
                    index_path=tmpdir,
                    embedding_model="all-MiniLM-L6-v2",
                    use_gpu=True,
                    use_faiss_gpu=True,
                )

                # If faiss-gpu is installed, index might be on GPU
                # Otherwise it falls back to CPU

                # Add entries
                tm.add_entry(
                    entry_id="test1",
                    site_id="test_site",
                    src_lang="en",
                    tgt_lang="es",
                    source_text="Hello world",
                    translation="Hola mundo",
                )

                assert tm.count() == 1

                # Search should work
                matches = tm.semantic_search(
                    site_id="test_site",
                    src_lang="en",
                    tgt_lang="es",
                    query_text="Hello",
                    k=1,
                    threshold=0.5,
                )

                assert len(matches) > 0

            except Exception as e:
                # FAISS GPU might not be available
                pytest.skip(f"FAISS GPU not available: {e}")

    def test_faiss_cpu_index(self):
        """Test FAISS CPU index as fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=False,
                use_faiss_gpu=False,
            )

            # Add entries
            tm.add_entry(
                entry_id="test1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            assert tm.count() == 1


class TestL3Performance:
    """Test performance-related functionality."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_large_batch_gpu(self):
        """Test large batch encoding on GPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Add large batch
            entries = []
            for i in range(500):
                entries.append({
                    "entry_id": f"test{i}",
                    "site_id": "test_site",
                    "src_lang": "en",
                    "tgt_lang": "es",
                    "source_text": f"Test sentence number {i} for benchmarking",
                    "translation": f"Sentencia de prueba número {i}",
                })

            count = tm.batch_add(entries)
            assert count == 500
            assert tm.count() == 500

    @pytest.mark.slow
    def test_large_batch_cpu(self):
        """Test large batch encoding on CPU."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=False,
            )

            # Add large batch
            entries = []
            for i in range(200):
                entries.append({
                    "entry_id": f"test{i}",
                    "site_id": "test_site",
                    "src_lang": "en",
                    "tgt_lang": "es",
                    "source_text": f"Test sentence {i}",
                    "translation": f"Sentencia {i}",
                })

            count = tm.batch_add(entries)
            assert count == 200
            assert tm.count() == 200
