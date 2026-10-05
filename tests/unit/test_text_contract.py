"""Pure text behavior copied from the existing shared-helper contract."""

import pytest

import app as app_module


@pytest.mark.parametrize(
    "text, expected",
    [
        (None, 0), (False, 0), (0, 0), ("", 0),
        ("abc", 3), ("あいう", 6), ("Aあ🙂", 5),
        ("a\r\nb\rc\n", 6),
        ("\x00\x7f\x80\x81", 5),
        ("\uf8ef\uf8f0\uf8f1", 5),
        ("\uff60\uff61\uff9f\uffa0", 6),
        ("https://example.com/long/path?x=1&y=2", 23),
        ("http://a https://b", 47),
        ("HTTPS://a", 9),
        ("https://example.com/あ", 23),
        ("https://a!あ", 26),
    ],
)
def test_weighted_text_contract(text, expected):
    assert app_module.calculate_weighted_length(text) == expected


@pytest.mark.parametrize("text", [1, object(), ["text"]])
def test_truthy_non_string_keeps_original_exception(text):
    with pytest.raises(AttributeError):
        app_module.calculate_weighted_length(text)
