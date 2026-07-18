from api.middleware import request_id_from_header


def test_request_id_accepts_bounded_opaque_value():
    assert request_id_from_header("release-42.trace_1") == "release-42.trace_1"


def test_request_id_rejects_unsafe_or_oversized_value():
    assert request_id_from_header("bad value") != "bad value"
    assert request_id_from_header("x" * 65) != "x" * 65
