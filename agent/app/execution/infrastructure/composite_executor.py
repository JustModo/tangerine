from app.execution.domain.models import ExecutionRequest
from app.execution.infrastructure.citron_adapter import CitronAdapter
from app.execution.infrastructure.local_subprocess_executor import LocalSubprocessExecutor
from app.shared.types import Language

# Citron's real languages.toml (citron/configs/languages.toml, verified against the
# actual justmodo/citron:latest image) registers c/cpp/java/python only — no JS runtime.
_CITRON_LANGUAGES = {Language.C, Language.CPP, Language.JAVA, Language.PYTHON}


class CompositeExecutor:
    """Routes to CitronAdapter (real nsjail sandbox isolation) for the languages Citron
    supports, falling back to LocalSubprocessExecutor only for JavaScript. Deliberately
    not a failover — if Citron is unreachable, execution fails loudly rather than
    silently downgrading to a different sandbox with different resource limits."""

    def __init__(
        self,
        citron: CitronAdapter | None = None,
        local: LocalSubprocessExecutor | None = None,
    ) -> None:
        self._citron = citron or CitronAdapter()
        self._local = local or LocalSubprocessExecutor()

    def execute(self, request: ExecutionRequest):
        executor = self._citron if request.language in _CITRON_LANGUAGES else self._local
        return executor.execute(request)
