from __future__ import annotations

from rudder.agents.profiles import builtin_profiles
from rudder.routing.requirements import ROLE_FLOORS
from rudder.tools.assembly import default_registry


def test_builtin_profiles_declare_the_supported_roles_and_role_floors() -> None:
    profiles = builtin_profiles()

    assert set(profiles) == {
        "lead",
        "general-purpose",
        "explorer",
        "implementer",
        "tester",
        "reviewer",
        "researcher",
    }
    assert {name: profile.role_floor for name, profile in profiles.items()} == ROLE_FLOORS
    assert all(profile.model_policy is None for profile in profiles.values())
    assert all(profile.expected_calls > 0 for profile in profiles.values())
    assert all(profile.response_schema for profile in profiles.values())


def test_builtin_profiles_match_the_default_tool_registry() -> None:
    registry = default_registry()

    for name, profile in builtin_profiles().items():
        assert set(profile.tools) == {tool.name for tool in registry.visible_to(name)}


def test_only_lead_can_delegate_by_default() -> None:
    profiles = builtin_profiles()

    assert profiles["lead"].delegation is True
    assert all(
        profile.delegation is False
        for name, profile in profiles.items()
        if name != "lead"
    )


def test_read_only_roles_cannot_write_and_execute_roles_are_write_capable() -> None:
    profiles = builtin_profiles()

    for name in ("explorer", "researcher"):
        assert profiles[name].write_capable is False
        assert profiles[name].permissions.write is False
        assert profiles[name].permissions.execute is False

    assert profiles["reviewer"].permissions.write is False
    for name in ("lead", "general-purpose", "implementer", "tester", "reviewer"):
        assert profiles[name].write_capable is True
