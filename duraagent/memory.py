"""
Memory Architecture for DuraAgent.

Layer: AI Engineering
Role:  Implements the 4-tier memory architecture required for advanced agents.
       1. Working Memory (Short-term context limit)
       2. Episodic Memory (Event log of past runs/conversations)
       3. Semantic Memory (RAG over documentation/codebases)
       4. Procedural Memory (Skill library & rule-based heuristics)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class MemoryRecord(BaseModel, Generic[T]):
    """Standardized wrapper for any memory retrieval."""
    model_config = ConfigDict(frozen=True)

    content: T
    relevance_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AbstractMemorySystem(ABC, Generic[T]):
    """Base interface for all memory tiers."""
    
    @abstractmethod
    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord[T]]:
        pass


class WorkingMemory(AbstractMemorySystem[str]):
    """
    Short-term memory. Typically an in-memory buffer of recent events,
    LLM outputs, and current variables, strictly bounded to fit in context window.
    """
    def __init__(self, capacity: int = 10):
        self.capacity = capacity
        self._buffer: list[str] = []

    def add(self, item: str) -> None:
        self._buffer.append(item)
        if len(self._buffer) > self.capacity:
            self._buffer.pop(0)

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord[str]]:
        # For working memory, usually we just dump the whole thing, but we satisfy interface.
        return [MemoryRecord(content=item, source="working") for item in self._buffer[-limit:]]


class ProceduralMemory(AbstractMemorySystem[dict[str, Any]]):
    """
    Skill library and rules. E.g., How to fix a specific type of linter error,
    or tool definitions.
    """
    def __init__(self, skills: list[dict[str, Any]]):
        self.skills = skills

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord[dict[str, Any]]]:
        # Dummy matching for demo purposes
        results = []
        for skill in self.skills:
            if query.lower() in skill.get("description", "").lower() or query.lower() in skill.get("name", "").lower():
                results.append(MemoryRecord(content=skill, source="procedural"))
        return results[:limit]


class EpisodicMemory(AbstractMemorySystem[dict[str, Any]]):
    """
    Event log of past runs. Used for few-shot prompting and learning from past mistakes.
    Backed by SQLiteStateStore.
    """
    def __init__(self, store: Any):  # Use Any to avoid circular dependency
        self.store = store

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord[dict[str, Any]]]:
        # In a real system, this would do a semantic search over past workflow events.
        # Here we just fetch recent events.
        runs = self.store.get_all_runs()
        results = []
        for run in runs[-limit:]:
            results.append(MemoryRecord(content=run, source="episodic"))
        return results


class SemanticMemory(AbstractMemorySystem[str]):
    """
    RAG over documentation, codebases, etc.
    Backed by a vector store (e.g. Chroma, Pinecone, or a local index).
    """
    def __init__(self, vector_store: Any):
        self.vector_store = vector_store

    def retrieve(self, query: str, limit: int = 5) -> list[MemoryRecord[str]]:
        if not hasattr(self.vector_store, "search"):
            return []
            
        docs = self.vector_store.search(query, k=limit)
        return [
            MemoryRecord(
                content=doc.text,
                relevance_score=doc.score,
                source=doc.source,
                metadata=doc.metadata
            )
            for doc in docs
        ]
