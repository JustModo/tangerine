import logging

logger = logging.getLogger(__name__)


def log_usage(call: str, model: str, system_chars: int, usage) -> None:
    """Logs what a Gemini call actually cost. The SDK already returns usage_metadata on
    every response and the app threw it away, so there was no way to tell what a turn
    spent — this is the only measurement of token use in the app.

    `cached` is the number of prompt tokens served from Gemini's cache rather than billed
    at full rate: it stays 0 until a stable prompt prefix is long enough and repeated
    often enough to be worth caching. `thoughts` bills as output.

    system_chars identifies the flow without threading a label through every call site —
    the prompts differ enough in size to tell apart (problem 7.3k, code helper 5k,
    chat 8.5k, lesson notes 2.6k).
    """
    if usage is None:
        return
    logger.info(
        "llm usage call=%s model=%s sys_chars=%d prompt=%s cached=%s output=%s thoughts=%s",
        call,
        model,
        system_chars,
        usage.prompt_token_count,
        usage.cached_content_token_count or 0,
        usage.candidates_token_count,
        usage.thoughts_token_count or 0,
    )
