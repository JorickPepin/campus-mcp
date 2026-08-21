import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def weeks() -> list[dict]:
    return json.loads((FIXTURES / "smart-training.json").read_text())


@pytest.fixture(scope="session")
def logged() -> list[dict]:
    return json.loads((FIXTURES / "logged-sessions.json").read_text())
