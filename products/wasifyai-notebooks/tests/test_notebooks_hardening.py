"""What an upload must be before it is stored."""

import zipfile

import pytest
from wasifyai_notebooks import hardening
from wasifyai_notebooks.hardening import Refused, check_file, safe_name, suffix_of


def write(tmp_path, name, data: bytes):
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    return p, name


def test_the_extension_is_validated_and_lower_cased():
    assert suffix_of("Report.PDF") == ".pdf"
    assert suffix_of("C:\\x\\notes.TXT") == ".txt"
    for bad in ("run.exe", "archive.zip", "noextension", "x.pdf.sh", "x.p!f"):
        with pytest.raises(Refused):
            suffix_of(bad)


def test_bytes_must_agree_with_the_extension(tmp_path):
    p, _ = write(tmp_path, "a.pdf", b"%PDF-1.7\n...")
    assert check_file(p, "a.pdf").mime == "application/pdf"
    p, _ = write(tmp_path, "a.pdf", b"MZ\x90\x00 an executable")
    with pytest.raises(Refused, match="does not look like"):
        check_file(p, "a.pdf")
    p, _ = write(tmp_path, "n.txt", b"hello \x00 world")
    with pytest.raises(Refused):
        check_file(p, "n.txt")
    p, _ = write(tmp_path, "i.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    assert check_file(p, "i.png").suffix == ".png"
    p, _ = write(tmp_path, "i.png", b"GIF89a")
    with pytest.raises(Refused):
        check_file(p, "i.png")


def test_text_with_utf8_and_a_cut_character_is_text(tmp_path):
    body = ("é" * 40000).encode()  # 2 bytes each; the 64 KB read ends mid-character or not
    p, _ = write(tmp_path, "a.md", body)
    assert check_file(p, "a.md").mime == "text/markdown"
    p, _ = write(tmp_path, "a.txt", b"\xff\xfe\xfa not utf8 at the start" * 10)
    with pytest.raises(Refused):
        check_file(p, "a.txt")


def make_zip(path, names, size=10):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, b"x" * size)


def test_an_office_file_is_a_zip_with_its_main_part(tmp_path):
    p = tmp_path / "d.docx"
    make_zip(p, ["[Content_Types].xml", "word/document.xml"])
    assert check_file(p, "d.docx").suffix == ".docx"
    make_zip(p, ["[Content_Types].xml", "ppt/presentation.xml"])
    with pytest.raises(Refused):  # a deck named .docx
        check_file(p, "d.docx")
    make_zip(p, ["[Content_Types].xml", "word/document.xml"] + [f"x{i}" for i in range(10_001)], 1)
    with pytest.raises(Refused, match="too many parts"):
        check_file(p, "d.docx")


def test_unpacked_size_and_file_size_are_capped(tmp_path, monkeypatch):
    p = tmp_path / "d.xlsx"
    make_zip(p, ["[Content_Types].xml", "xl/workbook.xml"], size=100)
    monkeypatch.setattr(hardening, "MAX_UNPACKED", 150)
    with pytest.raises(Refused, match="unpacks"):
        check_file(p, "d.xlsx")
    monkeypatch.setattr(hardening, "MAX_BYTES", 5)
    q = tmp_path / "big.txt"
    q.write_bytes(b"123456")
    with pytest.raises(Refused, match="larger"):
        check_file(q, "big.txt")
    e = tmp_path / "e.txt"
    e.write_bytes(b"")
    with pytest.raises(Refused, match="empty"):
        check_file(e, "e.txt")


def test_a_stored_name_is_one_safe_path_part():
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("a/b\\c: d?.pdf") == "c_ d_.pdf"
    assert safe_name("   ") == "document"
    assert len(safe_name("x" * 500 + ".pdf")) <= 120
