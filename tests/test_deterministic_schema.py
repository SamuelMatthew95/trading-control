"""
Tests to verify deterministic schema - no fallback logic exists.
These tests ensure VECTOR is used consistently across all models.
"""

import pytest
import inspect
import ast
from pathlib import Path


class TestDeterministicSchema:
    """Verify schema is deterministic - no conditional VECTOR/JSONB fallback."""
    
    def test_vector_memory_uses_vector_not_jsonb(self):
        """VectorMemory must use VECTOR column, not JSONB fallback."""
        from api.core.models.analytics import VectorMemory
        
        # Check embedding column is VECTOR
        embedding_column = VectorMemory.__table__.columns['embedding']
        assert 'VECTOR' in str(embedding_column.type), f"Embedding should be VECTOR type, got {embedding_column.type}"
        assert '1536' in str(embedding_column.type), "VECTOR should have 1536 dimensions"
        assert not embedding_column.nullable, "Embedding should be NOT NULL (required)"
    
    def test_vector_import_is_direct_not_conditional(self):
        """VECTOR import should be direct, not conditional."""
        # Read the analytics.py file
        analytics_file = Path(__file__).parent.parent / "api" / "core" / "models" / "analytics.py"
        content = analytics_file.read_text()
        
        # Should have direct import
        assert "from pgvector.sqlalchemy import VECTOR" in content
        
        # Should NOT have conditional import
        assert "try:" not in content or "from pgvector" not in content.split("try:")[1].split("except")[0]
        assert "VECTOR is not None" not in content
        assert "VECTOR = None" not in content
    
    def test_no_fallback_logic_in_any_model_files(self):
        """Scan all model files for fallback logic patterns."""
        models_dir = Path(__file__).parent.parent / "api" / "core" / "models"
        
        forbidden_patterns = [
            "try:",
            "except ImportError",
            "VECTOR is not None",
            "VECTOR = None",
            "if VECTOR",
            "else:",
            "JSONB"  # Should not be used for embeddings
        ]
        
        for py_file in models_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            content = py_file.read_text()
            
            for pattern in forbidden_patterns:
                # Skip if it's in a comment or docstring
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if pattern in line and not line.strip().startswith('#'):
                        # Check if it's in a docstring
                        if '"""' not in line and "'''" not in line:
                            # For JSONB, only allow it in specific contexts (not embeddings)
                            if pattern == "JSONB":
                                if "embedding" not in line.lower():
                                    continue
                            pytest.fail(f"Found forbidden pattern '{pattern}' in {py_file.name}:{i+1}: {line.strip()}")
    
    def test_all_models_import_from_pgvector_directly(self):
        """All models should import VECTOR directly."""
        models_dir = Path(__file__).parent.parent / "api" / "core" / "models"
        
        for py_file in models_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
                
            content = py_file.read_text()
            
            # If the file mentions embedding or vector, it should import VECTOR
            if "embedding" in content.lower() or "vector" in content.lower():
                assert "from pgvector.sqlalchemy import VECTOR" in content, f"{py_file.name} should import VECTOR directly"
    
    def test_migration_has_vector_extension(self):
        """Migration should create vector extension deterministically."""
        migration_file = Path(__file__).parent.parent / "api" / "alembic" / "versions" / "0001_initial.py"
        content = migration_file.read_text()
        
        # Should create vector extension
        assert 'CREATE EXTENSION IF NOT EXISTS vector' in content
        
        # Should not have conditional logic
        assert "try:" not in content
        assert "except" not in content
    
    def test_vector_index_is_deterministic(self):
        """Vector index should be deterministic, not conditional."""
        from api.core.models.analytics import VectorMemory
        
        # Check for vector index
        table_args = VectorMemory.__table_args__
        vector_index = None
        
        for index in table_args:
            if hasattr(index, 'columns') and 'embedding' in index.columns:
                vector_index = index
                break
        
        assert vector_index is not None, "Should have vector index on embedding column"
    
    def test_schema_version_enforcement(self):
        """Schema versions should be enforced deterministically."""
        from api.core.models.analytics import VectorMemory, TradePerformance, SystemMetrics
        
        for model in [VectorMemory, TradePerformance, SystemMetrics]:
            schema_version_column = model.__table__.columns['schema_version']
            assert not schema_version_column.nullable, "Schema version should be NOT NULL"
            
            # Check for check constraint in table_args
            table_args = model.__table_args__
            has_check = any(
                'schema_version' in str(arg) and 'check' in str(arg).lower()
                for arg in table_args 
            )
            assert has_check, f"{model.__name__} should have schema version check constraint"


class TestNoEnvironmentBasedSchema:
    """Verify schema doesn't change based on environment."""
    
    def test_same_schema_across_imports(self):
        """Multiple imports of same model should yield identical schema."""
        from api.core.models.analytics import VectorMemory as VM1
        from api.core.models.analytics import VectorMemory as VM2
        
        # Compare table definitions
        assert VM1.__tablename__ == VM2.__tablename__
        assert len(VM1.__table__.columns) == len(VM2.__table__.columns)
        
        # Compare column names and types
        vm1_columns = {col.name: str(col.type) for col in VM1.__table__.columns}
        vm2_columns = {col.name: str(col.type) for col in VM2.__table__.columns}
        
        assert vm1_columns == vm2_columns, f"Schema differs: {vm1_columns} vs {vm2_columns}"
    
    def test_requirements_include_pgvector(self):
        """Requirements should include pgvector deterministically."""
        req_file = Path(__file__).parent.parent / "requirements.txt"
        content = req_file.read_text()
        
        assert "pgvector" in content, "pgvector should be in requirements.txt"
    
    def test_no_conditional_imports_in_codebase(self):
        """Scan entire codebase for conditional import patterns."""
        base_dir = Path(__file__).parent.parent
        
        # Only look for pgvector-specific conditional imports
        forbidden_patterns = [
            "try:\n    from pgvector",
            "VECTOR = None",
            "if VECTOR is not None"
        ]
        
        for py_file in base_dir.rglob("*.py"):
            if "test" in str(py_file):
                continue  # Skip test files
                
            content = py_file.read_text()
            
            for pattern in forbidden_patterns:
                if pattern in content:
                    pytest.fail(f"Found pgvector conditional import pattern in {py_file}: {pattern}")
            
            # Check for except ImportError with pgvector context
            if "except ImportError:" in content and "pgvector" in content:
                pytest.fail(f"Found pgvector conditional import in {py_file}")


if __name__ == "__main__":
    pytest.main([__file__])
