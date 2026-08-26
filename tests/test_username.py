from src.username import (
    extract_username,
    extract_username_from_messages,
    normalize_username,
)


def test_extract_skips_blocklist_and_picks_real_handle():
    text = "Привет @username, выдайте на @roblox_hero99 пожалуйста"
    assert extract_username(text) == "@roblox_hero99"


def test_extract_requires_leading_at():
    assert extract_username("ник roblox_hero99 без собаки") is None


def test_extract_from_messages_prefers_latest():
    found = extract_username_from_messages(
        ["сначала @alpha_user", "потом @beta_user99"]
    )
    assert found == "@beta_user99"


def test_normalize_adds_at():
    assert normalize_username("  NickName  ") == "@NickName"
    assert normalize_username("@already") == "@already"
