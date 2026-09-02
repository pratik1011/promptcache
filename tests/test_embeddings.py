"""Embedding provider factory tests: env-driven selection and schema-safe dimensions."""
import os
import unittest
from unittest.mock import patch

from promptcache.providers import embeddings


class EmbeddingProviderTests(unittest.TestCase):
    def test_none_disables_semantic_cache(self):
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "none"}, clear=False):
            self.assertIsNone(embeddings.build_embedding_provider())

    def test_deterministic_matches_schema_dimensions(self):
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "deterministic"}, clear=False):
            provider = embeddings.build_embedding_provider()
        self.assertIsNotNone(provider)
        self.assertEqual(len(provider.embed("promptcache semantic lookup")), 384)

    def test_openai_compatible_requires_endpoint_and_key(self):
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai-compatible",
                                     "EMBEDDING_ENDPOINT": "", "EMBEDDING_API_KEY": ""}, clear=False):
            self.assertIsNone(embeddings.build_embedding_provider())

    def test_openai_compatible_emits_384_dimensions(self):
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai-compatible",
                                     "EMBEDDING_ENDPOINT": "https://embeddings.local",
                                     "EMBEDDING_API_KEY": "secret",
                                     "EMBEDDING_MODEL": "text-embedding-3-small"}, clear=False):
            provider = embeddings.build_embedding_provider()
        self.assertIsNotNone(provider)
        self.assertIsInstance(provider, embeddings.OpenAICompatibleEmbedding)
        self.assertEqual(provider.dimensions, 384)

    def test_fastembed_failure_degrades_to_disabled(self):
        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "fastembed"}, clear=False):
            with patch.object(embeddings, "FastEmbedEmbedding", side_effect=ImportError("fastembed not installed")):
                self.assertIsNone(embeddings.build_embedding_provider())


if __name__ == "__main__":
    unittest.main()
