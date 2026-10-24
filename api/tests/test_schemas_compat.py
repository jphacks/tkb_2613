import tkb_api.schemas as api_schemas
import tkb_common.schemas as common_schemas


def test_api_schemas_reexports_the_common_types() -> None:
    for name in api_schemas.__all__:
        assert getattr(api_schemas, name) is getattr(common_schemas, name)
