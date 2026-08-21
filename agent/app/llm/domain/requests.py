from pydantic import BaseModel


class StructuredGenerationRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    model: str | None = None  # falls back to Settings.llm_model when unset


class TextGenerationRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    model: str | None = None
