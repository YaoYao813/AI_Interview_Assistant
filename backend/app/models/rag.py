from pydantic import BaseModel


class DocumentChunk(BaseModel):
    id: str
    content: str
    metadata: dict = {}


class QueryResult(BaseModel):
    chunks: list[DocumentChunk]
    total: int
