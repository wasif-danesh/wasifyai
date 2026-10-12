from wasifyai_stt.formats import content_disposition, file_name, title_of, to_srt, to_text, to_vtt
from wasifyai_stt.languages import load_languages

SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": " Hello there. "},
    {"start": 2.5, "end": 3725.123, "text": "A very\nlong   one."},
    {"start": 4000.0, "end": 4001.0, "text": "   "},
]


def test_srt_numbers_the_lines_and_uses_commas_in_the_times():
    assert to_srt(SEGMENTS) == (
        "1\n00:00:00,000 --> 00:00:02,500\nHello there.\n\n"
        "2\n00:00:02,500 --> 01:02:05,123\nA very long one.\n"
    )


def test_vtt_has_a_header_and_dots_in_the_times():
    out = to_vtt(SEGMENTS)
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:02.500\nHello there." in out
    assert "4000" not in out  # an empty segment is dropped


def test_text_ends_with_one_newline():
    assert to_text("  some words \n\n") == "some words\n"


def test_the_title_is_the_first_words_cut_at_a_word():
    assert title_of("short") == "short"
    long = "word " * 40
    t = title_of(long)
    assert t.endswith("…") and len(t) <= 61 and not t[:-1].endswith(" ")
    assert title_of("আমাদের দোকানে আপনাকে স্বাগতম") == "আমাদের দোকানে আপনাকে স্বাগতম"


def test_file_names_are_safe_and_keep_other_scripts():
    assert file_name("Hello, World!", "srt") == "hello-world.srt"
    assert file_name("../../etc/passwd", "txt") == "etc-passwd.txt"
    assert file_name("!!!", "vtt") == "transcript.vtt"
    assert file_name("বাংলা কথা", "txt") == "বাংলা-কথা.txt"


def test_the_language_catalog_is_consistent():
    langs = load_languages()
    ids = [x.id for x in langs.languages]
    assert len(ids) == len(set(ids)) and "en" in ids and "bn" in ids
    assert langs.get("bn").english == "Bengali" and langs.get("bn").name == "বাংলা"  # type: ignore[union-attr]
    assert langs.get("xx") is None
    assert langs.engine.model and langs.engine.detect_model
    # every language the Indic engine serves is offered, and it has all 22 of IndicConformer's
    assert len(langs.indic) == 22 and all(langs.get(code) for code in langs.indic)
    assert {"bn", "hi", "ta", "sat", "mni"} <= set(langs.indic) and "en" not in langs.indic


def test_the_download_header_keeps_a_non_latin_name_and_has_an_ascii_fallback():
    h = content_disposition("বাংলা কথা", "txt")
    assert 'filename="transcript.txt"' in h
    assert "filename*=UTF-8''%E0%A6%AC" in h
    assert content_disposition("Hello", "srt").startswith('attachment; filename="hello.srt"')
