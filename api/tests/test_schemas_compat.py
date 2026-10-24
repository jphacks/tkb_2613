import tkb_api.schemas as api_schemas
import tkb_common.schemas as common_schemas


def test_api_schemas_reexports_the_common_types() -> None:
    shared = [n for n in api_schemas.__all__ if n not in api_schemas.API_ONLY_NAMES]

    assert shared
    for name in shared:
        assert getattr(api_schemas, name) is getattr(common_schemas, name)


def test_session_types_stay_in_api_only() -> None:
    assert api_schemas.SessionRequest.__module__ == "tkb_api.schemas"
    assert not hasattr(common_schemas, "SessionRequest")
    assert not hasattr(common_schemas, "SessionResponse")
