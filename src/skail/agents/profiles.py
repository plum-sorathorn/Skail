from __future__ import annotations

from skail.agents.profile_loader import AgentProfile
from skail.domain.security import PermissionSet
from skail.routing.requirements import ROLE_FLOORS

_REVISION = "builtin-v1"


def _profile(
    *,
    name: str,
    description: str,
    tools: tuple[str, ...],
    permissions: PermissionSet,
    prompt: str,
    expected_calls: int,
    response_schema: str,
    delegation: bool = False,
) -> AgentProfile:
    return AgentProfile(
        name=name,
        description=description,
        role=name,
        tools=tools,
        permissions=permissions,
        prompt=prompt,
        source="builtin",
        revision=_REVISION,
        delegation=delegation,
        response_schema=response_schema,
        role_floor=ROLE_FLOORS[name],
        expected_calls=expected_calls,
    )


def builtin_profiles() -> dict[str, AgentProfile]:
    """Return fresh immutable definitions for Skail's stable built-in roles."""

    file_read_tools = ("ls", "glob", "grep", "read_file")
    read_tools = (*file_read_tools, "skills", "memory", "ask_user")
    general_tools = (
        *file_read_tools,
        "write_file",
        "edit_file",
        "execute",
        "skills",
        "memory",
        "ask_user",
    )
    return {
        "lead": _profile(
            name="lead",
            description=(
                "Own the user request, work directly or delegate, then synthesize and verify."
            ),
            tools=(
                *file_read_tools,
                "write_file",
                "edit_file",
                "execute",
                "write_todos",
                "task",
                "skills",
                "memory",
                "ask_user",
            ),
            permissions=PermissionSet(read=True, write=True, execute=True, network=True),
            prompt="Own the request, preserve constraints, and explain blocked or returned work.",
            expected_calls=12,
            response_schema="lead_response",
            delegation=True,
        ),
        "general-purpose": _profile(
            name="general-purpose",
            description="Complete bounded delegated work and return concise evidence.",
            tools=general_tools,
            permissions=PermissionSet(read=True, write=True, execute=True),
            prompt=(
                "Return changed paths and verification evidence rather than a conversational essay."
            ),
            expected_calls=8,
            response_schema="task_result",
        ),
        "explorer": _profile(
            name="explorer",
            description="Trace code and report evidence without modifying the workspace.",
            tools=read_tools,
            permissions=PermissionSet(read=True),
            prompt=(
                "Report file and symbol references, explicit unknowns, "
                "and make no workspace changes."
            ),
            expected_calls=4,
            response_schema="exploration_result",
        ),
        "implementer": _profile(
            name="implementer",
            description="Make a bounded code change and run focused verification.",
            tools=general_tools,
            permissions=PermissionSet(read=True, write=True, execute=True),
            prompt=(
                "Preserve user changes, report touched paths, "
                "and include relevant verification evidence."
            ),
            expected_calls=8,
            response_schema="task_result",
        ),
        "tester": _profile(
            name="tester",
            description="Construct or run tests and distinguish product from environment failures.",
            tools=(*read_tools, "execute"),
            permissions=PermissionSet(read=True, execute=True),
            prompt="Do not treat a zero exit code with skipped required assertions as success.",
            expected_calls=6,
            response_schema="test_result",
        ),
        "reviewer": _profile(
            name="reviewer",
            description=(
                "Independently review correctness, security, compatibility, and maintenance."
            ),
            tools=(*file_read_tools, "execute", "skills", "memory", "ask_user"),
            permissions=PermissionSet(read=True, execute=True),
            prompt="Order findings by severity and state inspected evidence and verification gaps.",
            expected_calls=5,
            response_schema="review_result",
        ),
        "researcher": _profile(
            name="researcher",
            description="Research local or external documentation and report sourced conclusions.",
            tools=read_tools,
            permissions=PermissionSet(read=True, network=True),
            prompt=(
                "Separate sourced facts from inference and return citations or local references."
            ),
            expected_calls=4,
            response_schema="research_result",
        ),
    }
