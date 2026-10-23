import pytest

from harness.workflows.system76_power import System76PowerCLIWorkflow

__all__ = ["test_get_perf_profile_returns_valid_profile"]

VALID_PERF_PROFILES = frozenset({"battery", "balanced", "performance"})


@pytest.fixture(scope="module")
def system76_workflow(artifacts):
    return System76PowerCLIWorkflow(artifacts=artifacts)


def test_get_perf_profile_returns_valid_profile(system76_workflow: System76PowerCLIWorkflow) -> None:
    result = system76_workflow.query_profile(item_id="cli.power_profiles_can_be_queried_and_set")
    assert result.success
    assert result.data["profile"] in VALID_PERF_PROFILES
