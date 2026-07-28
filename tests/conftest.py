import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "smart-training.json"


@pytest.fixture(scope="session")
def weeks() -> list[dict]:
    return json.loads(FIXTURE.read_text())
