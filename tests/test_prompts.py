from imageeval.judge.prompts import build_messages, prompt_hash


def test_prompt_hash_is_stable(rubric) -> None:
    first = prompt_hash(rubric)
    assert first == prompt_hash(rubric)
    assert len(first) == 16


def test_messages_contain_query_image_and_anchors(rubric) -> None:
    messages = build_messages("一只红色的猫", "data:image/png;base64,AAA", rubric)
    assert messages[0]["role"] == "system"
    assert "1 = 严重问题" in messages[0]["content"]
    assert "至少一条必须是 critical" in messages[0]["content"]

    user_parts = messages[1]["content"]
    assert user_parts[0]["type"] == "text"
    assert "一只红色的猫" in user_parts[0]["text"]
    assert user_parts[1]["image_url"]["url"] == "data:image/png;base64,AAA"
