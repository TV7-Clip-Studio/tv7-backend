from __future__ import annotations

from app.services import youtube_oauth


def test_build_and_parse_state_token() -> None:
    state, secret = youtube_oauth.build_state_token(42)
    assert str(42) in state
    parsed = youtube_oauth.parse_state_token(state)
    assert parsed == (42, secret)


def test_parse_state_token_invalid() -> None:
    assert youtube_oauth.parse_state_token("invalid") is None
    assert youtube_oauth.parse_state_token("not-a-number:abc") is None
