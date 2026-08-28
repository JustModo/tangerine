import pytest
from google.genai import errors

from app.llm.infrastructure.gemini import retry


def _api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": "boom"}})


@pytest.mark.parametrize("code", [429, 500, 503])
def test_transient_api_errors_are_retryable(code: int) -> None:
    assert retry.is_retryable(_api_error(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_permanent_api_errors_are_not_retryable(code: int) -> None:
    """A bad key or a malformed request fails the same way forever — retrying wastes the
    user's time and, for a 429-adjacent quota, their quota."""
    assert not retry.is_retryable(_api_error(code))


def test_a_schema_failure_is_not_a_transport_failure() -> None:
    assert not retry.is_retryable(ValueError("not an APIError"))


async def test_with_retry_recovers_from_a_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(retry.asyncio, "sleep", lambda _: _noop())
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _api_error(429)
        return "ok"

    assert await retry.with_retry(flaky, "test") == "ok"
    assert len(calls) == 3


async def test_with_retry_gives_up_after_max_attempts(monkeypatch) -> None:
    monkeypatch.setattr(retry.asyncio, "sleep", lambda _: _noop())
    calls = []

    async def always_429():
        calls.append(1)
        raise _api_error(429)

    with pytest.raises(errors.APIError):
        await retry.with_retry(always_429, "test")
    assert len(calls) == retry.MAX_ATTEMPTS


async def test_with_retry_does_not_retry_a_permanent_failure(monkeypatch) -> None:
    monkeypatch.setattr(retry.asyncio, "sleep", lambda _: _noop())
    calls = []

    async def bad_key():
        calls.append(1)
        raise _api_error(403)

    with pytest.raises(errors.APIError):
        await retry.with_retry(bad_key, "test")
    assert len(calls) == 1


async def _noop():
    return None
