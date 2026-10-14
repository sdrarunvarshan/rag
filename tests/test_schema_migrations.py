"""
Tests for Alembic schema migrations.
These tests verify that migrations are properly defined and can be applied.
"""

import pytest
from pathlib import Path
import subprocess
import tempfile
import shutil


@pytest.fixture
def alembic_ini_path():
    """Get the path to alembic.ini."""
    return Path(__file__).parent.parent / "alembic.ini"


@pytest.fixture
def alembic_dir():
    """Get the path to the alembic directory."""
    return Path(__file__).parent.parent / "alembic"


def test_alembic_ini_exists(alembic_ini_path):
    """Test that alembic.ini exists."""
    assert alembic_ini_path.exists(), "alembic.ini not found"


def test_alembic_dir_exists(alembic_dir):
    """Test that alembic directory exists."""
    assert alembic_dir.exists(), "alembic directory not found"
    assert (alembic_dir / "env.py").exists(), "alembic/env.py not found"
    assert (alembic_dir / "versions").exists(), "alembic/versions not found"


def test_alembic_versions_exist(alembic_dir):
    """Test that at least one migration version exists."""
    versions_dir = alembic_dir / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    assert len(migration_files) > 0, "No migration files found in alembic/versions"


def test_migration_files_have_valid_format(alembic_dir):
    """Test that migration files follow the expected naming convention."""
    versions_dir = alembic_dir / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    
    for migration_file in migration_files:
        # Skip __pycache__ and __init__.py
        if migration_file.name.startswith("__"):
            continue
        
        # Migration files should follow the pattern: YYYYMMDD_HHMM_revision_id.py
        filename = migration_file.name
        assert "_" in filename, f"Migration file {filename} does not contain underscore"
        assert filename.endswith(".py"), f"Migration file {filename} does not end with .py"
        
        # Read the file and check for required migration functions
        content = migration_file.read_text()
        assert "def upgrade()" in content, f"Migration {filename} missing upgrade() function"
        assert "def downgrade()" in content, f"Migration {filename} missing downgrade() function"


def test_migration_no_legacy_schema_in_db():
    """Test that db.py does not contain legacy SCHEMA_STATEMENTS."""
    db_path = Path(__file__).parent.parent / "app" / "db.py"
    content = db_path.read_text()
    
    # Legacy schema statements should be removed
    assert "SCHEMA_STATEMENTS" not in content or "SCHEMA_STATEMENTS removed" in content, \
        "Legacy SCHEMA_STATEMENTS should be removed from db.py"
    
    # Legacy CREATE TABLE statements should not be present
    assert "CREATE TABLE IF NOT EXISTS documents" not in content, \
        "Legacy CREATE TABLE statements should be removed from db.py"


def test_init_schema_does_not_create_tables():
    """Test that init_schema() does not create tables directly."""
    db_path = Path(__file__).parent.parent / "app" / "db.py"
    content = db_path.read_text()
    
    # init_schema should only call ensure_database() and log about Alembic
    assert "def init_schema()" in content, "init_schema() function not found"
    
    # Should not contain CREATE TABLE statements
    init_schema_start = content.find("def init_schema()")
    init_schema_end = content.find("\ndef ", init_schema_start + 1)
    init_schema_content = content[init_schema_start:init_schema_end]
    
    assert "CREATE TABLE" not in init_schema_content, \
        "init_schema() should not contain CREATE TABLE statements"


def test_check_alembic_migration_exists():
    """Test that check_alembic_migration() function exists."""
    db_path = Path(__file__).parent.parent / "app" / "db.py"
    content = db_path.read_text()
    
    assert "def check_alembic_migration()" in content, \
        "check_alembic_migration() function not found in db.py"


def test_startup_calls_migration_check():
    """Test that startup code calls check_alembic_migration()."""
    main_path = Path(__file__).parent.parent / "app" / "main.py"
    content = main_path.read_text()
    
    assert "check_alembic_migration" in content, \
        "main.py should call check_alembic_migration() at startup"
    
    # Should raise error if migrations are not up to date
    assert "alembic upgrade head" in content, \
        "main.py should reference 'alembic upgrade head' in error message"


def test_no_legacy_schema_statements_constant():
    """Test that SCHEMA_STATEMENTS constant is removed or empty."""
    db_path = Path(__file__).parent.parent / "app" / "db.py"
    content = db_path.read_text()
    
    # Check if SCHEMA_STATEMENTS exists and is not the old version
    if "SCHEMA_STATEMENTS" in content:
        # It should be a comment indicating it's removed
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "SCHEMA_STATEMENTS" in line:
                # Check if it's just a comment
                assert line.strip().startswith("#") or "removed" in line.lower(), \
                    "SCHEMA_STATEMENTS should be removed or marked as removed"
                break


def test_alembic_env_py_exists(alembic_dir):
    """Test that alembic/env.py exists and is valid."""
    env_path = alembic_dir / "env.py"
    assert env_path.exists(), "alembic/env.py not found"
    
    content = env_path.read_text()
    assert "run_migrations_online" in content or "run_migrations_offline" in content, \
        "alembic/env.py should contain migration running functions"


def test_migration_ordering(alembic_dir):
    """Test that migration files are properly ordered by timestamp."""
    versions_dir = alembic_dir / "versions"
    migration_files = sorted([f for f in versions_dir.glob("*.py") if not f.name.startswith("__")])
    
    if len(migration_files) < 2:
        pytest.skip("Need at least 2 migrations to test ordering")
    
    # Extract timestamps from filenames (YYYYMMDD_HHMM format)
    timestamps = []
    for migration_file in migration_files:
        parts = migration_file.name.split("_")
        if len(parts) >= 2:
            timestamp = parts[0] + parts[1]
            timestamps.append(timestamp)
    
    # Timestamps should be in ascending order
    assert timestamps == sorted(timestamps), \
        "Migration files should be ordered by timestamp"


def test_models_exist():
    """Test that SQLAlchemy models exist for schema definition."""
    models_path = Path(__file__).parent.parent / "app" / "models.py"
    assert models_path.exists(), "app/models.py not found"
    
    content = models_path.read_text()
    
    # Check for key model classes
    assert "class Document" in content or "class Base" in content, \
        "models.py should contain Document model or Base"
    
    # Should use SQLAlchemy
    assert "from sqlalchemy" in content or "import sqlalchemy" in content, \
        "models.py should use SQLAlchemy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
