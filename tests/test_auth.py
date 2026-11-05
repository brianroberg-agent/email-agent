"""Tests for auth.py: parsing the token settings and deciding a request.

Every token in this file is synthetic. Nothing here is a real credential.
"""

import pytest

import auth

TOKEN_A = "synthetic-token-aaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "synthetic-token-bbbbbbbbbbbbbbbbbbbbbbbb"
TOKEN_C = "synthetic-token-cccccccccccccccccccccccc"


class TestParseApiKeys:
    def test_single_pair_gives_one_named_key(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A}")

        assert [key.name for key in keys] == ["alpha"]
        assert keys[0].matches(TOKEN_A)
        assert not keys[0].matches(TOKEN_B)

    def test_several_pairs_keep_their_order_and_their_own_tokens(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A},beta:{TOKEN_B}")

        assert [key.name for key in keys] == ["alpha", "beta"]
        assert keys[0].matches(TOKEN_A) and not keys[0].matches(TOKEN_B)
        assert keys[1].matches(TOKEN_B) and not keys[1].matches(TOKEN_A)

    def test_whitespace_around_entries_names_and_tokens_is_ignored(self):
        keys = auth.parse_api_keys(f"  alpha : {TOKEN_A} ,\n beta:{TOKEN_B}  ")

        assert [key.name for key in keys] == ["alpha", "beta"]
        assert keys[0].matches(TOKEN_A)
        assert keys[1].matches(TOKEN_B)

    def test_blank_entries_from_stray_commas_are_skipped(self):
        keys = auth.parse_api_keys(f"alpha:{TOKEN_A},,beta:{TOKEN_B},")

        assert [key.name for key in keys] == ["alpha", "beta"]

    @pytest.mark.parametrize("raw", [None, "", "   ", ",", " , "])
    def test_unset_or_blank_setting_gives_no_keys(self, raw):
        assert auth.parse_api_keys(raw) == ()

    def test_a_token_may_contain_colons(self):
        token = "synthetic:token:with:colons:dddddddddddd"
        keys = auth.parse_api_keys(f"alpha:{token}")

        assert keys[0].name == "alpha"
        assert keys[0].matches(token)


# Each case: (setting value, text the error must contain). The values are
# built so that no part of them is a valid configuration.
MALFORMED_KEYS = {
    "entry without a colon": (TOKEN_A, "entry 1"),
    "entry with an empty name": (f":{TOKEN_A}", "entry 1"),
    "empty token": ("alpha:", "entry 1"),
    "whitespace-only token": ("alpha:   ", "entry 1"),
    "duplicate name": (f"alpha:{TOKEN_A},beta:{TOKEN_B},alpha:{TOKEN_C}", "entry 3"),
    "duplicate token": (f"alpha:{TOKEN_A},beta:{TOKEN_A}", "entry 2"),
    "token shorter than the minimum": ("alpha:synthetic-short-token", "entry 1"),
    "token one character short": ("alpha:" + "s" * 31, "entry 1"),
    "token with a space inside": (f"alpha:synthetic token {TOKEN_A}", "entry 1"),
    "token with a non-ASCII character": (f"alpha:{TOKEN_A}é", "entry 1"),
    "name with a space": (f"al pha:{TOKEN_A}", "entry 1"),
    "name with a control character": (f"al\x1bpha:{TOKEN_A}", "entry 1"),
    "name as long as a token": (f"{TOKEN_B}:{TOKEN_A}", "entry 1"),
    "second entry malformed": (f"alpha:{TOKEN_A},beta", "entry 2"),
}


class TestParseApiKeysRejectsMalformedSettings:
    @pytest.mark.parametrize("case", sorted(MALFORMED_KEYS))
    def test_malformed_setting_is_a_configuration_error(self, case):
        raw, expected = MALFORMED_KEYS[case]

        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.parse_api_keys(raw)

        message = str(excinfo.value)
        assert "EMAIL_AGENT_API_KEYS" in message
        assert expected in message

    @pytest.mark.parametrize("case", sorted(MALFORMED_KEYS))
    def test_error_message_echoes_nothing_from_the_setting(self, case):
        """The message names the entry by position. It repeats no name and no
        token, because a token pasted in the wrong place would otherwise be
        printed at start-up."""
        raw, _ = MALFORMED_KEYS[case]

        with pytest.raises(auth.AuthConfigError) as excinfo:
            auth.parse_api_keys(raw)

        message = str(excinfo.value)
        for entry in raw.split(","):
            for piece in entry.split(":"):
                piece = piece.strip()
                if len(piece) >= 4:
                    assert piece not in message

    def test_a_token_of_exactly_the_minimum_length_is_accepted(self):
        token = "s" * auth.MIN_TOKEN_LENGTH

        assert auth.MIN_TOKEN_LENGTH == 32
        assert auth.parse_api_keys(f"alpha:{token}")[0].matches(token)

    def test_a_name_of_31_characters_is_accepted(self):
        name = "n" * 31

        assert auth.parse_api_keys(f"{name}:{TOKEN_A}")[0].name == name

    def test_key_repr_shows_the_name_and_not_the_token_or_digest(self):
        key = auth.parse_api_keys(f"alpha:{TOKEN_A}")[0]

        assert "alpha" in repr(key)
        assert TOKEN_A not in repr(key)
        assert "digest" not in repr(key)
