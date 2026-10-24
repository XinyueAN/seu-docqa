from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict] = Field(default_factory=list)
    model: str
    conversation_id: str | None = None


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=80)


class DocumentSummary(BaseModel):
    id: str
    name: str
    kind: str
    status: str
    pages: int | None = None
    chunks: int = 0


class EvaluationCaseCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    relevant_documents: list[str] = Field(min_length=1, max_length=20)


class CategoryUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=40)
