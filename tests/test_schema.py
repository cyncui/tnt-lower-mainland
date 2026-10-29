import json
from pathlib import Path

from tnt.schema import Run

SCHEMA = Path(__file__).parents[1] / "schema" / "run.schema.json"


def test_published_json_schema_is_current():
    # Regenerate with: uv run tnt schema > schema/run.schema.json
    assert json.loads(SCHEMA.read_text()) == Run.model_json_schema()
