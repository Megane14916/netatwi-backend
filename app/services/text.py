"""Weighted text length with the original URL and character rules."""

import re


# --- 文字数カウントロジック (追加) ---
def calculate_weighted_length(text):
    if not text:
        return 0

    # 改行コードの正規化: \r\n -> \n, \r -> \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    url_pattern = re.compile(r"https?://[\w/:%#\$&\?\(\)~\.=\+\-]+")
    processed_text = url_pattern.sub("x" * 23, text)

    length = 0
    for char in processed_text:
        code = ord(char)
        if (0x00 <= code <= 0x80) or (code == 0xF8F0) or (0xFF61 <= code <= 0xFF9F):
            length += 1
        else:
            length += 2

    return length
