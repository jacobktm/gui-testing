import os

import pytest

from harness.workflows import System76PowerGUIWorkflow


def _os_id():
    # Could be detected from system; default for manual runs
    return os.environ.get("TEST_OS_ID", "pop-24.04")


@pytest.mark.gui
class TestSystem76PowerGUI:
    def test_open_power_settings(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.open_power_settings(_os_id())
        assert res.success, res.summary

    def test_detect_power_profile(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_power_profile(_os_id())
        assert res.success, res.summary

    @pytest.mark.skipif(os.environ.get("TEST_OS_ID") != "pop-22.04", reason="Pop 22.04 only")
    def test_detect_graphics_mode_pop22(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_graphics_mode()
        assert res.success, res.summary
