import json

from pydantic import BaseModel, ValidationError


class SchemaValidationError(Exception):
    """Raised when a raw LLM response fails schema (Pydantic) validation — the
    generate/validate boundary."""


def parse_structured_response(raw_text: str, response_model: type[BaseModel]) -> BaseModel:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"LLM response was not valid JSON: {exc}") from exc
    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        raise SchemaValidationError(f"LLM response failed schema validation: {exc}") from exc
