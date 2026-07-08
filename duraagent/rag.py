"""
Retrieval-Augmented Generation (RAG) for DuraAgent.

Layer: AI Engineering
Role:  Provides semantic search capabilities over codebases, documentation,
       or APIs. Serves as the backend for SemanticMemory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


class Document(BaseModel):
    """A chunk of text with associated metadata."""
    model_config = ConfigDict(frozen=True)

    text: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 1.0


class SimpleVectorStore:
    """
    A naive, in-memory BM25/TF-IDF style vector store for demonstration.
    In a real system, use ChromaDB, Pinecone, or pgvector.
    """
    def __init__(self):
        self.documents: list[Document] = []

    def add_texts(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> None:
        if metadatas is None:
            metadatas = [{} for _ in texts]
            
        for text, meta in zip(texts, metadatas):
            # source could be extracted from meta, or defaulted
            source = meta.get("source", "unknown")
            self.documents.append(Document(text=text, source=source, metadata=meta))

    def search(self, query: str, k: int = 5) -> list[Document]:
        """Simple keyword-overlap search (fake cosine similarity)."""
        if not self.documents:
            return []
            
        query_terms = set(query.lower().split())
        scored_docs = []
        
        for doc in self.documents:
            doc_terms = set(doc.text.lower().split())
            overlap = len(query_terms.intersection(doc_terms))
            # Fake TF-IDF: normalize by doc length to avoid bias to huge docs
            score = overlap / (math.log(len(doc_terms) + 2)) if doc_terms else 0.0
            
            # Create a new Document instance with the calculated score
            scored_docs.append(Document(
                text=doc.text,
                source=doc.source,
                metadata=doc.metadata,
                score=score
            ))
            
        # Sort by score descending
        scored_docs.sort(key=lambda d: d.score, reverse=True)
        return scored_docs[:k]
