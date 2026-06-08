from pydantic import BaseModel, Field


class CursorPageMeta(BaseModel):
    next_cursor: str | None = Field(default=None)
