from app.curriculum.application.problem_sessions import ProblemSessionService
from app.curriculum.application.services import CurriculumService
from app.problems.application.library import ProblemLibraryService
from app.revision.application.services import RevisionService
from app.sessions.tools.base import ChatTool
from app.sessions.tools.curriculum import EditPlanTool, GeneratePlanTool, GetPlanTool
from app.sessions.tools.library import (
    CreatePracticePlanTool,
    FindProblemsTool,
    SetProblemFlagTool,
)
from app.sessions.tools.revision import PracticeRecordTool


def build_default_tools(
    curriculum_service: CurriculumService | None = None,
    revision_service: RevisionService | None = None,
    problem_session_service: ProblemSessionService | None = None,
    library_service: ProblemLibraryService | None = None,
) -> list[ChatTool]:
    return [
        GeneratePlanTool(curriculum_service),
        EditPlanTool(curriculum_service),
        GetPlanTool(curriculum_service),
        PracticeRecordTool(revision_service, library_service),
        FindProblemsTool(library_service, problem_session_service),
        SetProblemFlagTool(problem_session_service, library_service),
        CreatePracticePlanTool(curriculum_service, library_service),
    ]
