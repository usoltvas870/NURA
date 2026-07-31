from tools.build_prompt_review_packet import CHECKLIST, build_packet


def test_review_packet_is_sanitized_fixed_and_provider_free() -> None:
    packet = build_packet()
    assert packet["contract"] == "nura-prompt-human-review-v1"
    assert packet["external_ai_invocation"] is False
    assert packet["contains_prompt_text"] is False
    assert packet["contains_birth_dates"] is False
    entries = packet["entries"]
    assert isinstance(entries, list) and len(entries) == 10
    assert {entry["consumer"] for entry in entries} == {
        "report.full",
        "chat.free",
    }
    for entry in entries:
        assert len(entry["prompt_hash"]) == 64
        assert tuple(entry["checklist"]) == CHECKLIST
        serialized = str(entry)
        assert "01.01." not in serialized
        assert "api_key" not in serialized.lower()
        assert "system.txt" not in serialized
