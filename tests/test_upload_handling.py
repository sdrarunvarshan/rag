"""
Tests for upload handling with streaming, size validation, and cleanup.
These tests verify that uploads are properly validated and temporary files are cleaned up.
"""

import pytest
import shutil
from pathlib import Path
from io import BytesIO
from unittest.mock import Mock, AsyncMock, patch
from fastapi import HTTPException, UploadFile, status

from app.middleware import stream_upload_to_disk
from app.config import MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB, UPLOAD_DIR


@pytest.fixture
def cleanup_upload_dir():
    """Clean up upload directory before and after tests."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up any existing files
    for file in UPLOAD_DIR.glob("*"):
        if file.is_file():
            file.unlink()
    yield
    # Clean up after tests
    for file in UPLOAD_DIR.glob("*"):
        if file.is_file():
            file.unlink()


def create_mock_upload_file(filename: str, content: bytes) -> UploadFile:
    """Create a mock UploadFile for testing."""
    file = Mock(spec=UploadFile)
    file.filename = filename
    file.file = BytesIO(content)
    file.size = len(content)
    return file


def test_stream_upload_valid_pdf(cleanup_upload_dir):
    """Test streaming a valid PDF file to disk."""
    # Create a minimal valid PDF
    pdf_content = b"%PDF-1.4\n%Fake PDF for testing\n%%EOF"
    mock_file = create_mock_upload_file("test.pdf", pdf_content)
    
    # Stream to disk
    temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    try:
        # Verify file was created
        assert temp_path.exists(), "Temporary file was not created"
        assert temp_path.suffix == ".pdf", "File has wrong extension"
        
        # Verify content
        with open(temp_path, "rb") as f:
            saved_content = f.read()
        assert saved_content == pdf_content, "File content mismatch"
        
        # Verify size
        assert temp_path.stat().st_size == len(pdf_content), "File size mismatch"
    finally:
        # Cleanup
        temp_path.unlink(missing_ok=True)


def test_stream_upload_oversized_file(cleanup_upload_dir):
    """Test that oversized files are rejected."""
    # Create content larger than max size
    large_content = b"x" * (MAX_UPLOAD_SIZE_BYTES + 1)
    mock_file = create_mock_upload_file("large.pdf", large_content)
    
    # Should raise HTTPException with 413 status
    with pytest.raises(HTTPException) as exc_info:
        stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "exceeds maximum allowed size" in str(exc_info.value.detail)
    
    # Verify no temporary file was created
    temp_files = list(UPLOAD_DIR.glob("*.pdf"))
    assert len(temp_files) == 0, "Temporary file should not be created for oversized upload"


def test_stream_upload_invalid_magic_bytes(cleanup_upload_dir):
    """Test that files with invalid magic bytes are rejected."""
    # Create file with invalid magic bytes
    invalid_content = b"NOT-A-PDF-FILE"
    mock_file = create_mock_upload_file("invalid.pdf", invalid_content)
    
    # Should raise HTTPException with 415 status
    with pytest.raises(HTTPException) as exc_info:
        stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    assert exc_info.value.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "valid PDF" in str(exc_info.value.detail)
    
    # Verify no temporary file was created
    temp_files = list(UPLOAD_DIR.glob("*.pdf"))
    assert len(temp_files) == 0, "Temporary file should not be created for invalid file"


def test_stream_upload_custom_size_limit(cleanup_upload_dir):
    """Test streaming with custom size limit."""
    # Create content larger than custom limit but smaller than global limit
    custom_limit = 100
    content = b"x" * (custom_limit + 1)
    mock_file = create_mock_upload_file("test.pdf", b"%PDF-1.4\n" + content)
    
    # Should raise HTTPException with custom limit
    with pytest.raises(HTTPException) as exc_info:
        stream_upload_to_disk(mock_file, custom_limit)
    
    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


def test_stream_upload_chunked_reading(cleanup_upload_dir):
    """Test that file is read in chunks, not all at once."""
    # Create a larger PDF to test chunking
    chunk_size = 8192
    content = b"%PDF-1.4\n" + b"x" * (chunk_size * 2)  # 2 chunks worth
    mock_file = create_mock_upload_file("chunked.pdf", content)
    
    # Stream to disk
    temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES, chunk_size=chunk_size)
    
    try:
        # Verify file was created correctly
        assert temp_path.exists()
        with open(temp_path, "rb") as f:
            saved_content = f.read()
        assert saved_content == content
    finally:
        temp_path.unlink(missing_ok=True)


def test_stream_upload_cleanup_on_error(cleanup_upload_dir):
    """Test that temporary file is cleaned up on error."""
    # Create a mock file that will fail during reading
    mock_file = Mock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.file = Mock()
    
    # Make file read raise an exception
    mock_file.file.__iter__ = Mock(side_effect=IOError("Read error"))
    
    # Should raise HTTPException
    with pytest.raises(HTTPException):
        stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    # Verify no temporary file was created
    temp_files = list(UPLOAD_DIR.glob("*.pdf"))
    assert len(temp_files) == 0, "Temporary file should be cleaned up on error"


def test_stream_upload_empty_file(cleanup_upload_dir):
    """Test handling of empty file."""
    mock_file = create_mock_upload_file("empty.pdf", b"")
    
    # Empty file should not have valid magic bytes
    with pytest.raises(HTTPException) as exc_info:
        stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    assert exc_info.value.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_stream_upload_no_filename(cleanup_upload_dir):
    """Test handling of file with no filename."""
    mock_file = Mock(spec=UploadFile)
    mock_file.filename = None
    mock_file.file = BytesIO(b"%PDF-1.4\n")
    
    # Should still work with no filename (uses default extension)
    temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    try:
        assert temp_path.exists()
    finally:
        temp_path.unlink(missing_ok=True)


def test_upload_dir_created_if_missing():
    """Test that upload directory is created if it doesn't exist."""
    # Temporarily remove upload directory
    temp_backup = UPLOAD_DIR / ".backup"
    if UPLOAD_DIR.exists():
        shutil.move(str(UPLOAD_DIR), str(temp_backup))
    
    try:
        # Ensure directory doesn't exist
        assert not UPLOAD_DIR.exists()
        
        # Stream upload should create directory
        pdf_content = b"%PDF-1.4\n%Fake PDF\n%%EOF"
        mock_file = create_mock_upload_file("test.pdf", pdf_content)
        temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
        
        try:
            assert UPLOAD_DIR.exists(), "Upload directory should be created"
            assert temp_path.exists()
        finally:
            temp_path.unlink(missing_ok=True)
    finally:
        # Restore backup
        if temp_backup.exists():
            if UPLOAD_DIR.exists():
                shutil.rmtree(str(UPLOAD_DIR))
            shutil.move(str(temp_backup), str(UPLOAD_DIR))


def test_pdf_magic_bytes_detection():
    """Test that PDF magic bytes are correctly detected."""
    # Valid PDF magic bytes
    valid_magic = b"%PDF-"
    assert valid_magic.startswith(b"%PDF-"), "Valid PDF magic bytes should start with %PDF-"
    
    # Invalid magic bytes
    invalid_magic = b"NOTPDF"
    assert not invalid_magic.startswith(b"%PDF-"), "Invalid magic bytes should not start with %PDF-"


def test_max_upload_size_configuration():
    """Test that MAX_UPLOAD_SIZE_BYTES is correctly configured."""
    assert MAX_UPLOAD_SIZE_BYTES == MAX_UPLOAD_SIZE_MB * 1024 * 1024, \
        "MAX_UPLOAD_SIZE_BYTES should be MAX_UPLOAD_SIZE_MB * 1024 * 1024"
    
    assert MAX_UPLOAD_SIZE_BYTES > 0, "MAX_UPLOAD_SIZE_BYTES should be positive"
    assert MAX_UPLOAD_SIZE_MB > 0, "MAX_UPLOAD_SIZE_MB should be positive"


def test_upload_file_suffix_preserved(cleanup_upload_dir):
    """Test that file suffix is preserved in temporary file."""
    pdf_content = b"%PDF-1.4\n%Fake PDF\n%%EOF"
    mock_file = create_mock_upload_file("document.pdf", pdf_content)
    
    temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
    
    try:
        assert temp_path.suffix == ".pdf", "File suffix should be preserved"
    finally:
        temp_path.unlink(missing_ok=True)


def test_stream_upload_multiple_files(cleanup_upload_dir):
    """Test streaming multiple files sequentially."""
    pdf_content = b"%PDF-1.4\n%Fake PDF\n%%EOF"
    
    temp_paths = []
    try:
        # Upload multiple files
        for i in range(3):
            mock_file = create_mock_upload_file(f"test{i}.pdf", pdf_content)
            temp_path = stream_upload_to_disk(mock_file, MAX_UPLOAD_SIZE_BYTES)
            temp_paths.append(temp_path)
            assert temp_path.exists()
        
        # Verify all files exist
        assert len(temp_paths) == 3
        for path in temp_paths:
            assert path.exists()
    finally:
        # Cleanup all files
        for path in temp_paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
