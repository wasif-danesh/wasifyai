from wasifyai_platform_sdk.filenames import shown_name, shown_stem


def test_a_name_loses_its_folders_and_hidden_marks_but_keeps_its_letters():
    assert shown_name("../../../../etc/passwd.wav") == "passwd.wav"
    assert shown_name("C:\\Users\\me\\song.wav") == "song.wav"
    assert shown_name("photo\u202egnp.exe") == "photognp.exe"  # no right-to-left trick
    assert shown_name("a\x00b\x1fc\u200b.wav") == "abc.wav"
    assert shown_name("বাংলা গান 😀.wav") == "বাংলা গান 😀.wav"
    assert shown_name("", "recording") == "recording"
    assert len(shown_name("a" * 900)) == 200


def test_a_stem_is_the_title():
    assert shown_stem("../Holiday.wav") == "Holiday"
    assert shown_stem(".hidden") == ".hidden"
    assert shown_stem("\u202e", "Recording") == "Recording"
