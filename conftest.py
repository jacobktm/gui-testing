import pytest

PROGRAMS = ["system76-power"]


def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = item.path.parts
        if "tests" not in parts:
            continue
        program = parts[parts.index("tests") + 1]
        if program in PROGRAMS:
            marker = program.replace("-", "_")
            item.add_marker(getattr(pytest.mark, marker))
