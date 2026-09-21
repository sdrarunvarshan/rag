"""
OpenTelemetry instrumentation for FastAPI and LangChain with Arize Phoenix.
This module sets up distributed tracing for the RAG application.
"""

import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import get_settings

log = logging.getLogger(__name__)


def setup_telemetry(
    phoenix_endpoint: Optional[str] = None,
    project_name: Optional[str] = None,
) -> Optional[TracerProvider]:
    """
    Set up OpenTelemetry instrumentation with Arize Phoenix.
    
    Args:
        phoenix_endpoint: Phoenix collector endpoint (e.g., "http://localhost:6006")
                        If None, reads from PHOENIX_ENDPOINT env var
        project_name: Project name for Phoenix
                     If None, reads from PHOENIX_PROJECT_NAME env var
    
    Returns:
        Configured TracerProvider or None if setup fails
    """
    settings = get_settings()
    
    # Get Phoenix configuration
    phoenix_endpoint = phoenix_endpoint or settings.phoenix_endpoint
    project_name = project_name or settings.phoenix_project_name
    
    try:
        # Try to use Phoenix for tracing
        from phoenix.otel import register_phoenix_tracer
        
        tracer_provider = register_phoenix_tracer(
            project_name=project_name,
            endpoint=phoenix_endpoint,
        )
        
        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)
        
        log.info(f"OpenTelemetry tracing enabled with Phoenix at {phoenix_endpoint}")
        return tracer_provider
        
    except ImportError as e:
        log.warning(f"Phoenix OTEL not available: {e}. Falling back to console tracing.")
        
        # Fallback to console tracing
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)
        
        # Add console exporter for development
        console_exporter = ConsoleSpanExporter()
        span_processor = SimpleSpanProcessor(console_exporter)
        tracer_provider.add_span_processor(span_processor)
        
        log.info("OpenTelemetry tracing enabled with console exporter")
        return tracer_provider
        
    except Exception as e:
        log.warning(f"Failed to set up Phoenix tracing: {e}. Tracing disabled.")
        return None


def instrument_fastapi(app):
    """
    Instrument a FastAPI application with OpenTelemetry.
    
    Args:
        app: FastAPI application instance
    """
    try:
        FastAPIInstrumentor.instrument_app(app)
        log.info("FastAPI instrumentation enabled")
    except Exception as e:
        log.warning(f"Failed to instrument FastAPI: {e}")
    
    return app


def get_tracer(name: str = "rag"):
    """
    Get a tracer instance for manual instrumentation.
    
    Args:
        name: Tracer name
    
    Returns:
        Tracer instance
    """
    return trace.get_tracer(name)
