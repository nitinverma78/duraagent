"""
Tracing and Observability for DuraAgent.

Layer: Harness Engineering
Role:  Provides span-level distributed tracing (OpenTelemetry style) for deep
       visibility into agent operations (LLM calls, tool execution, planning).
       Integrates with the event log for a unified observability picture.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from duraagent.types import SpanId, RunId


class Span(BaseModel):
    """An observable operation with a start and end time."""
    model_config = ConfigDict(frozen=False) # Mutable during execution

    span_id: SpanId = Field(default_factory=lambda: SpanId(str(uuid.uuid4())))
    run_id: RunId
    parent_span_id: SpanId | None = None
    operation: str = ""
    start_time_ms: float = Field(default_factory=lambda: time.time() * 1000)
    end_time_ms: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    def end(self, error: Exception | None = None) -> None:
        self.end_time_ms = time.time() * 1000
        if error:
            self.error = f"{type(error).__name__}: {str(error)}"

    @property
    def duration_ms(self) -> float:
        if self.end_time_ms is None:
            return (time.time() * 1000) - self.start_time_ms
        return self.end_time_ms - self.start_time_ms


class TraceExporter(ABC):
    """Destination for completed spans."""
    
    @abstractmethod
    def export(self, span: Span) -> None:
        pass


class ConsoleExporter(TraceExporter):
    """Exports spans to stdout/logging."""
    
    def __init__(self, logger_name: str = "duraagent.tracing"):
        self.logger = logging.getLogger(logger_name)
        
    def export(self, span: Span) -> None:
        duration = span.duration_ms
        status = "❌" if span.error else "✅"
        msg = f"{status} [Span: {span.operation}] {duration:.1f}ms"
        if span.error:
            msg += f" - {span.error}"
        self.logger.info(msg)


class Tracer:
    """Manages span lifecycles and context."""
    
    def __init__(self, run_id: RunId, exporter: TraceExporter | None = None):
        self.run_id = run_id
        self.exporter = exporter or ConsoleExporter()
        self._current_span: Span | None = None

    def start_span(self, operation: str, attributes: dict[str, Any] | None = None) -> Span:
        parent_id = self._current_span.span_id if self._current_span else None
        span = Span(
            run_id=self.run_id,
            parent_span_id=parent_id,
            operation=operation,
            attributes=attributes or {}
        )
        self._current_span = span
        return span

    def end_span(self, span: Span, error: Exception | None = None) -> None:
        span.end(error)
        self.exporter.export(span)
        # In a real async context, we'd use contextvars. For this demo, simple pop:
        if self._current_span and self._current_span.span_id == span.span_id:
            # We don't have the parent object reference here, so we just clear it.
            # Real implementation uses contextvars.
            self._current_span = None


# Global tracer context (simplified for demo)
_current_tracer: Tracer | None = None

def set_tracer(tracer: Tracer) -> None:
    global _current_tracer
    _current_tracer = tracer


def traced(operation: str | None = None):
    """
    Decorator to automatically trace a function execution.
    Creates a span, records execution time, and catches exceptions.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        op_name = operation or func.__name__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            tracer = _current_tracer
            if not tracer:
                return func(*args, **kwargs)
                
            span = tracer.start_span(op_name)
            try:
                result = func(*args, **kwargs)
                tracer.end_span(span)
                return result
            except Exception as e:
                tracer.end_span(span, error=e)
                raise
                
        return wrapper
    return decorator
