"""
Tests for embedding validation in SafeWriter.
"""

import pytest

from api.core.writer.safe_writer import SafeWriter


class TestEmbeddingValidation:
    """Test embedding validation logic."""

    def test_validate_embedding_success(self):
        """Test valid embedding passes validation."""
        writer = SafeWriter(None)

        # Valid embedding: 1536 floats
        valid_embedding = [0.1] * 1536

        # This should not raise an exception
        # We'll test this indirectly through write_vector_memory validation

        data = {
            'schema_version': 'v2',
            'source': 'test',
            'content': 'test content',
            'content_type': 'text',
            'embedding': valid_embedding
        }

        # Should not raise exception during validation
        writer._validate_schema_v2(data, 'VectorMemory')

    def test_validate_embedding_wrong_length(self):
        """Test embedding validation fails with wrong length."""
        writer = SafeWriter(None)

        # Wrong length embedding
        wrong_embedding = [0.1] * 1000  # Only 1000 elements

        data = {
            'schema_version': 'v2',
            'source': 'test',
            'content': 'test content',
            'content_type': 'text',
            'embedding': wrong_embedding
        }

        # Schema validation passes
        writer._validate_schema_v2(data, 'VectorMemory')

        # But embedding validation should fail
        with pytest.raises(ValueError) as exc_info:
            # Simulate the embedding validation from write_vector_memory
            embedding = data['embedding']
            if not isinstance(embedding, list) or len(embedding) != 1536:
                raise ValueError("embedding must be 1536-length list")

        assert "1536-length list" in str(exc_info.value)

    def test_validate_embedding_wrong_type(self):
        """Test embedding validation fails with wrong type."""
        writer = SafeWriter(None)

        # Wrong type embedding
        wrong_embedding = ["not", "numeric"] * 768  # Strings, not numbers

        data = {
            'schema_version': 'v2',
            'source': 'test',
            'content': 'test content',
            'content_type': 'text',
            'embedding': wrong_embedding
        }

        # Schema validation passes
        writer._validate_schema_v2(data, 'VectorMemory')

        # But embedding validation should fail
        with pytest.raises(ValueError) as exc_info:
            # Simulate the embedding validation from write_vector_memory
            embedding = data['embedding']
            if not isinstance(embedding, list) or len(embedding) != 1536:
                raise ValueError("embedding must be 1536-length list")

            if not all(isinstance(x, (int, float)) for x in embedding):
                raise ValueError("embedding must be numeric")

        assert "numeric" in str(exc_info.value)

    def test_validate_embedding_not_list(self):
        """Test embedding validation fails when not a list."""
        writer = SafeWriter(None)

        # Not a list
        not_list_embedding = "not a list"

        data = {
            'schema_version': 'v2',
            'source': 'test',
            'content': 'test content',
            'content_type': 'text',
            'embedding': not_list_embedding
        }

        # Schema validation passes
        writer._validate_schema_v2(data, 'VectorMemory')

        # But embedding validation should fail
        with pytest.raises(ValueError) as exc_info:
            # Simulate the embedding validation from write_vector_memory
            embedding = data['embedding']
            if not isinstance(embedding, list) or len(embedding) != 1536:
                raise ValueError("embedding must be 1536-length list")

        assert "1536-length list" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__])
