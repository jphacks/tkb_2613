import pytest

from tkb_engine.scoring.sample import build_tables
from tkb_engine.scoring.tables import ScoringTables


@pytest.fixture
def tables() -> ScoringTables:
    return build_tables()
