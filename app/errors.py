"""
Error handling and safe error responses.
"""

import logging
from typing import Any
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

log = logging.getLogger(__name__)


def safe_error_response(request: Request, exc: Exception) -> JSONResponse:
    """
    Generate safe error responses that don't leak sensitive information.
    
    This function:
    - Returns generic error messages to clients
    - Logs detailed errors server-side
    - Redacts PII from logs
    - Includes request ID for tracing
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Log detailed error with request ID
    log.error(
        "Request %s failed: %s",
        request_id,
        str(exc),
        exc_info=True,
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        }
    )
    
    # Return safe error message to client
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "request_id": request_id,
            }
        )
    
    # Generic error for unexpected exceptions
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An internal error occurred",
            "request_id": request_id,
        }
    )


def redact_pii(text: str) -> str:
    """
    Redact potential PII from text before logging.
    
    This is a basic implementation. In production, consider:
    - Email address redaction
    - Phone number redaction
    - Credit card number redaction
    - SSN redaction
    """
    if not text:
        return text
    
    # Redact email addresses
    import re
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REDACTED_EMAIL]', text)
    
    # Redact potential credit card numbers (basic pattern)
    text = re.sub(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[REDACTED_CC]', text)
    
    # Redact potential SSN patterns
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', text)
    
    return text


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with safe responses."""
    return safe_error_response(request, exc)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation exceptions with safe responses."""
    request_id = getattr(request.state, "request_id", "unknown")
    
    log.warning(
        "Request %s validation failed: %s",
        request_id,
        str(exc),
        extra={
            "request_id": request_id,
            "path": request.url.path,
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "request_id": request_id,
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle general exceptions with safe responses."""
    return safe_error_response(request, exc)
