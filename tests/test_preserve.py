import copy
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from lxml import etree as E
from pydantic import ValidationError

from app.preserve import EditRequest, PreserveError, inspect_document, replace_document, HP, NS
from app.preserve_cli import _create_files
from examples.make_preserve_fixture import build_fixture, sample_request

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/preserve-template.hwpx"


@pytest.fixture(scope="module")
def source():
    return EXAMPLE.read_bytes()


def parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def rewrite(data, updates=None, drop=(), extra=()):
    """Make independently malformed or extended input packages for boundary tests."""
    updates = updates or {}
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            if info.filename not in drop:
                dst.writestr(copy.copy(info), updates.get(info.filename, src.read(info)))
        for name, content in extra:
            dst.writestr(name, content)
    return out.getvalue()


def change_xml(data, name, fn):
    root = E.fromstring(parts(data)[name])
    fn(root)
    return rewrite(data, {name: E.tostring(root, encoding="utf-8", xml_declaration=True)})


def target(data, text):
    matches = [t for t in inspect_document(data)["targets"] if t["text"] == text]
    assert len(matches) == 1
    return matches[0]


def request(data, text="사업 목적: 도로대장 최신성 확보", before="최신성 확보", after="최신성 및 활용성 강화", **kwargs):
    return EditRequest(source_sha256=hashlib.sha256(data).hexdigest(), replacements=[
        {"target_id": target(data, text)["id"], "before": before, "after": after, **kwargs}])


def test_committed_fixture_is_byte_reproducible_and_schema_valid(source):
    assert build_fixture() == source
    assert not HwpxDocument.open(io.BytesIO(source)).validate().issues
    saved = EditRequest.model_validate_json((ROOT / "examples/preserve-replacements.json").read_text())
    assert saved == sample_request(source)


def test_inspect_explicit_scope_and_multisection_support(source):
    info = inspect_document(source)
    assert info["validation"]["structure_valid"]
    assert info["validation"]["sections"] == 2
    assert not info["validation"]["native_render_verified"]
    assert not info["validation"]["full_schema_checked"]
    assert info["supported_count"] and info["unsupported_count"]
    assert target(source, "240")["kind"] == "cell"
    for text in ["병합 제목 · 수정 금지", "이 셀도 병합표에 속함", "도형 내부 · 수정 금지"]:
        assert not target(source, text)["supported"]
    protected = [t for t in info["targets"] if "머리말 보존" in t["text"] or "꼬리말 보존" in t["text"]]
    assert protected and all(not t["supported"] for t in protected)


def test_exact_xml_payload_preservation_and_readback(source):
    original_hash = hashlib.sha256(source).hexdigest()
    output, diff = replace_document(source, sample_request(source))
    old, new = parts(source), parts(output)
    assert hashlib.sha256(source).hexdigest() == original_hash
    assert old.keys() == new.keys()
    assert [n for n in old if old[n] != new[n]] == ["Contents/section0.xml"]
    expected = old["Contents/section0.xml"].replace("2026년 도로대장".encode(), "2027년 도로대장".encode())
    expected = expected.replace("최신성 확보".encode(), "최신성 및 활용성 강화".encode()).replace(b">240<", b">360<")
    assert new["Contents/section0.xml"] == expected  # all other XML bytes, not merely parsed styles
    assert not HwpxDocument.open(io.BytesIO(output)).validate().issues
    assert len(diff["changes"]) == 3 and diff["changes"][2]["before"] == "240"
    assert diff["changes"][2]["after"] == "360"
    assert diff["validation"]["unrelated_members_identical"] and diff["validation"]["text_readback_valid"]
    with zipfile.ZipFile(io.BytesIO(source)) as a, zipfile.ZipFile(io.BytesIO(output)) as b:
        assert a.comment == b.comment and a.namelist() == b.namelist()
        for x, y in zip(a.infolist(), b.infolist()):
            assert (x.date_time, x.compress_type, x.external_attr, x.extra, x.comment) == (y.date_time, y.compress_type, y.external_attr, y.extra, y.comment)
    assert replace_document(source, sample_request(source))[0] == output


def test_scoped_target_leaves_same_words_in_other_paragraphs(source):
    output, _ = replace_document(source, request(source, text="검토 검토", before="검토", after="확인", expected_count=2))
    assert target(output, "확인 확인")["supported"]
    assert target(output, "2026년 도로대장 통합관리 예산 검토")["supported"]


def test_same_style_run_boundary_preserves_runs(source):
    output, _ = replace_document(source, request(source, text="같은 서식의 문장", before="같은 서식의", after="동일한"))
    assert target(output, "동일한 문장")["supported"]
    old = E.fromstring(parts(source)["Contents/section0.xml"])
    new = E.fromstring(parts(output)["Contents/section0.xml"])
    assert len(old.findall(".//hp:run", NS)) == len(new.findall(".//hp:run", NS))


def test_mixed_style_edit_inside_run_is_allowed_but_crossing_is_rejected(source):
    output, _ = replace_document(source, request(source, text="보통 강조 문장", before="강조", after="굵게"))
    assert target(output, "보통 굵게 문장")["supported"]
    with pytest.raises(PreserveError) as error:
        replace_document(source, request(source, text="보통 강조 문장", before="보통 강조", after="변경"))
    assert error.value.code == "style_boundary"


@pytest.mark.parametrize("after", ["", "  앞뒤 공백  ", "<태그> & 비교 > 값", "한글과 😀"])
def test_empty_whitespace_unicode_and_xml_escaping(source, after):
    req = request(source, text="240", before="240", after=after)
    assert req.replacements[0].after == after
    output, diff = replace_document(source, req)
    assert any(t["text"] == after and t["id"] == req.replacements[0].target_id for t in inspect_document(output)["targets"])
    assert diff["changes"][0]["after"] == after
    assert len(E.fromstring(parts(source)["Contents/section0.xml"]).findall(".//hp:tc", NS)) == len(E.fromstring(parts(output)["Contents/section0.xml"]).findall(".//hp:tc", NS))


def test_second_section_and_cell_paragraph_addressing(source):
    output, diff = replace_document(source, request(source, text="둘째 구역의 원문 유지", before="원문", after="수정 내용"))
    assert parts(source)["Contents/section0.xml"] == parts(output)["Contents/section0.xml"]
    assert diff["changed_members"] == ["Contents/section1.xml"]
    def add_paragraph(root):
        sub = root.find(".//hp:tbl/hp:tr/hp:tc/hp:subList", NS)
        p = copy.deepcopy(sub.find("hp:p", NS)); p.set("id", "99999")
        p.find("hp:run/hp:t", NS).text = "추가 문단"
        sub.append(p)
    extended = change_xml(source, "Contents/section0.xml", add_paragraph)
    req = request(extended, text="추가 문단", before="추가", after="다음")
    assert req.replacements[0].target_id.endswith("/p1")
    output, _ = replace_document(extended, req)
    assert target(output, "항목")["text"] == "항목"
    assert target(output, "다음 문단")["supported"]


@pytest.mark.parametrize(("text", "before"), [("병합 제목 · 수정 금지", "병합"), ("이 셀도 병합표에 속함", "셀"), ("도형 내부 · 수정 금지", "도형")])
def test_unsafe_targets_fail_without_modification(source, text, before):
    snapshot = bytes(source)
    with pytest.raises(PreserveError) as error:
        replace_document(source, request(source, text=text, before=before, after="치환"))
    assert error.value.code == "unsupported_target" and source == snapshot


def test_header_footer_targets_are_explicitly_protected(source):
    for t in inspect_document(source)["targets"]:
        if t["kind"] == "protected" and t["text"]:
            req = EditRequest(source_sha256=hashlib.sha256(source).hexdigest(), replacements=[
                {"target_id": t["id"], "before": t["text"], "after": "변경 시도"}])
            with pytest.raises(PreserveError) as error:
                replace_document(source, req)
            assert error.value.code == "unsupported_target"


def test_nested_table_is_protected_including_outer_cells(source):
    def nest(root):
        outer = root.find(".//hp:tbl", NS)
        nested = copy.deepcopy(outer)
        outer.find("hp:tr/hp:tc/hp:subList/hp:p/hp:run", NS).append(nested)
    data = change_xml(source, "Contents/section0.xml", nest)
    cells = [t for t in inspect_document(data)["targets"] if t["kind"] == "cell"]
    assert all(not t["supported"] for t in cells)


def test_field_or_unknown_control_is_never_edited(source):
    def field(root):
        p = root.findall("hp:p", NS)[3]
        E.SubElement(p.find("hp:run", NS), f"{{{HP}}}ctrl").append(E.Element(f"{{{HP}}}fieldBegin", id="123", type="HYPERLINK"))
    data = change_xml(source, "Contents/section0.xml", field)
    t = target(data, "사업 목적: 도로대장 최신성 확보")
    assert not t["supported"]
    with pytest.raises(PreserveError) as error:
        replace_document(data, request(data))
    assert error.value.code == "unsupported_target"


def test_layout_cache_requires_utf16_length_preservation(source):
    def cache(root):
        p = root.findall("hp:p", NS)[3]
        lines = E.SubElement(p, f"{{{HP}}}linesegarray")
        E.SubElement(lines, f"{{{HP}}}lineseg", textpos="0")
    data = change_xml(source, "Contents/section0.xml", cache)
    assert target(data, "사업 목적: 도로대장 최신성 확보")["length_locked"]
    with pytest.raises(PreserveError) as error:
        replace_document(data, request(data))
    assert error.value.code == "layout_cache_length"
    output, _ = replace_document(data, request(data, before="확보", after="강화"))
    assert target(output, "사업 목적: 도로대장 최신성 강화")["supported"]


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda r: r.update(source_sha256="0" * 64), "source_changed"),
    (lambda r: r["replacements"][0].update(target_id="section99/p0"), "target_not_found"),
    (lambda r: r["replacements"][0].update(before="존재하지 않는 문장"), "text_not_found"),
    (lambda r: r["replacements"][0].update(expected_count=2), "match_count_mismatch"),
    (lambda r: r["replacements"][0].update(after="최신성 확보"), "no_change"),
    (lambda r: r["replacements"][0].update(after="줄\n바꿈"), "unsupported_text"),
    (lambda r: r["replacements"][0].update(after="탭\t문자"), "unsupported_text"),
    (lambda r: r["replacements"][0].update(after="잘못된\x00문자"), "unsupported_text"),
])
def test_precise_failure_codes(source, mutate, code):
    req = request(source).model_dump(); mutate(req)
    with pytest.raises(PreserveError) as error:
        replace_document(source, EditRequest.model_validate(req))
    assert error.value.code == code


def test_ambiguity_and_all_or_nothing_batch(source):
    with pytest.raises(PreserveError) as error:
        replace_document(source, request(source, text="검토 검토", before="검토", after="확인"))
    assert error.value.code == "match_count_mismatch"
    req = sample_request(source).model_dump()
    req["replacements"][-1]["before"] = "999999"
    with pytest.raises(PreserveError) as error:
        replace_document(source, EditRequest.model_validate(req))
    assert error.value.code == "text_not_found" and target(source, "240")["text"] == "240"


def test_request_rejects_empty_duplicate_unknown_and_noninteger_counts(source):
    req = request(source).model_dump()
    for updated in [
        {**req, "replacements": []},
        {**req, "replacements": req["replacements"] * 2},
        {**req, "unknown": True},
        {**req, "replacements": [{**req["replacements"][0], "expected_count": True}]},
        {**req, "replacements": [{**req["replacements"][0], "before": ""}]},
    ]:
        with pytest.raises(ValidationError):
            EditRequest.model_validate(updated)


@pytest.mark.parametrize("name", ["../escape.xml", "/absolute.xml", "Contents\\bad.xml", "C:/file.xml", "Contents//other.xml"])
def test_archive_paths_rejected(source, name):
    info = zipfile.ZipInfo("entry"); info.filename = name
    data = rewrite(source, extra=[(info, b"bad")])
    with pytest.raises(PreserveError):
        inspect_document(data)


@pytest.mark.parametrize("name", ["Contents/content.hpf", "META-INF/container.xml", "Contents/section1.xml", "settings.xml"])
def test_all_xml_parts_are_entity_checked(source, name):
    data = rewrite(source, {name: b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'})
    with pytest.raises(PreserveError, match="DTD"):
        inspect_document(data)


def test_utf16_and_non_utf8_xml_are_explicitly_unsupported(source):
    name = "Contents/section0.xml"
    raw = parts(source)[name].decode().replace("utf-8", "utf-16").encode("utf-16")
    with pytest.raises(PreserveError) as error:
        inspect_document(rewrite(source, {name: raw}))
    assert error.value.code == "unsupported_encoding"


def test_utf8_bom_offsets_are_preserved(source):
    name = "Contents/section0.xml"
    data = rewrite(source, {name: b"\xef\xbb\xbf" + parts(source)[name]})
    output, _ = replace_document(data, request(data))
    assert parts(output)[name] == parts(data)[name].replace("최신성 확보".encode(), "최신성 및 활용성 강화".encode())


def test_ascii_utf16_without_bom_is_rejected(source):
    data = rewrite(source, {"settings.xml": '<?xml version="1.0" encoding="UTF-16LE"?><settings/>'.encode("utf-16-le")})
    with pytest.raises(PreserveError) as error:
        inspect_document(data)
    assert error.value.code == "unsupported_encoding"


def test_size_member_and_uncompressed_limits(source, monkeypatch):
    from app import preserve
    monkeypatch.setattr(preserve, "MAX_UPLOAD", len(source) - 1)
    with pytest.raises(PreserveError) as error:
        inspect_document(source)
    assert error.value.code == "package_too_large"
    monkeypatch.setattr(preserve, "MAX_UPLOAD", 10 * 1024 * 1024)
    data = rewrite(source, extra=[(f"extra/{i}", b"") for i in range(401)])
    with pytest.raises(PreserveError, match="파일 개수"):
        inspect_document(data)
    compressed = zipfile.ZipInfo("large.bin"); compressed.compress_type = zipfile.ZIP_DEFLATED
    data = rewrite(source, extra=[(compressed, b"0" * (40 * 1024 * 1024))])
    with pytest.raises(PreserveError, match="압축 해제"):
        inspect_document(data)


@pytest.mark.parametrize("case", ["missing", "duplicate", "mime", "xml", "signature", "crc", "compressed_mime"])
def test_bad_packages_are_rejected(source, case):
    if case == "missing":
        data = rewrite(source, drop=["Contents/content.hpf"])
    elif case == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate"):
            data = rewrite(source, extra=[("Contents/header.xml", parts(source)["Contents/header.xml"])])
    elif case == "mime":
        data = rewrite(source, {"mimetype": b"application/not-hwpx"})
    elif case == "xml":
        data = rewrite(source, {"Contents/section0.xml": b"<broken>"})
    elif case == "signature":
        data = rewrite(source, extra=[("META-INF/signatures.xml", b"<signatures/>")])
    elif case == "compressed_mime":
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for name, raw in parts(source).items():
                dst.writestr(name, raw)
        data = out.getvalue()
    else:
        data = bytearray(source)
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            info = z.getinfo("Contents/section0.xml")
            start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
            data[start + info.compress_size // 2] ^= 0xFF
        data = bytes(data)
    with pytest.raises(PreserveError):
        inspect_document(data)


@pytest.mark.parametrize("case", ["manifest_href", "spine", "style", "header_ref", "image_ref", "table_span", "table_rows", "table_overlap", "root"])
def test_broken_references_and_table_structure_rejected(source, case):
    name = "Contents/section0.xml"
    def mutate(root):
        if case == "style": root.find(".//hp:run", NS).set("charPrIDRef", "missing")
        elif case == "header_ref": root.find(".//hp:headerApply", NS).set("idRef", "missing")
        elif case == "image_ref":
            next(n for n in root.iter() if "binaryItemIDRef" in n.attrib).set("binaryItemIDRef", "missing")
        elif case == "table_span": root.find(".//hp:cellSpan", NS).set("rowSpan", "9999")
        elif case == "table_rows": root.find(".//hp:tbl", NS).set("rowCnt", "5")
        elif case == "table_overlap": root.findall(".//hp:tbl", NS)[0].findall(".//hp:cellAddr", NS)[1].set("colAddr", "0")
        elif case == "root": root.tag = "not-a-section"
    if case == "manifest_href":
        name = "Contents/content.hpf"
        mutate = lambda root: root.find("opf:manifest/opf:item", NS).set("href", "https://example.com/file.xml")
    elif case == "spine":
        name = "Contents/content.hpf"
        mutate = lambda root: root.find("opf:spine", NS).remove(root.findall("opf:spine/opf:itemref", NS)[-1])
    with pytest.raises(PreserveError):
        inspect_document(change_xml(source, name, mutate))


def test_cdata_not_rewritten_and_xml_prefixes_and_entities_supported(source):
    raw = parts(source)["Contents/section0.xml"].replace(b"hp:", b"p:").replace(b"xmlns:hp=", b"xmlns:p=")
    data = rewrite(source, {"Contents/section0.xml": raw.replace("최신성 확보".encode(), "최신성 &#54869;보".encode())})
    output, _ = replace_document(data, request(data, after="A & B < C"))
    assert b"A &amp; B &lt; C" in parts(output)["Contents/section0.xml"]
    cdata = rewrite(source, {"Contents/section0.xml": parts(source)["Contents/section0.xml"].replace(b">240<", b"><![CDATA[240]]><")})
    with pytest.raises(PreserveError) as error:
        replace_document(cdata, request(cdata, text="240", before="240", after="360"))
    assert error.value.code == "unsupported_target"


def cli(*args):
    return subprocess.run([sys.executable, "-m", "app.preserve_cli", *map(str, args)], cwd=ROOT, capture_output=True, text=True)


def test_cli_inspect_dry_run_and_copy_output(source, tmp_path):
    original = tmp_path / "original.hwpx"; original.write_bytes(source)
    edits = tmp_path / "edits.json"; edits.write_text(sample_request(source).model_dump_json(), encoding="utf-8")
    out = tmp_path / "copy.hwpx"
    inspected = cli("--input", original, "--inspect")
    assert inspected.returncode == 0 and json.loads(inspected.stdout)["supported_count"]
    dry = cli("--input", original, "--replacements", edits, "--dry-run")
    assert dry.returncode == 0 and not out.exists()
    result = cli("--input", original, "--replacements", edits, "--output", out)
    assert result.returncode == 0, result.stderr
    diff = Path(str(out) + ".diff.json")
    assert original.read_bytes() == source and diff.exists()
    assert json.loads(diff.read_text()) == json.loads(dry.stdout)
    assert out.read_bytes() == replace_document(source, sample_request(source))[0]
    again = cli("--input", original, "--replacements", edits, "--output", out)
    assert again.returncode == 2 and original.read_bytes() == source
    assert cli("--input", original, "--replacements", edits, "--output", original).returncode == 2


def test_cli_missing_target_does_not_create_output_or_diff(source, tmp_path):
    original = tmp_path / "original.hwpx"; original.write_bytes(source)
    req = sample_request(source).model_dump(); req["replacements"][-1]["target_id"] = "missing"
    edits = tmp_path / "edits.json"; edits.write_text(json.dumps(req), encoding="utf-8")
    out = tmp_path / "copy.hwpx"
    result = cli("--input", original, "--replacements", edits, "--output", out)
    assert result.returncode == 2 and "target_not_found" in result.stderr
    assert not out.exists() and not Path(str(out) + ".diff.json").exists()
    assert original.read_bytes() == source


def test_copy_failure_rolls_back_comparison(tmp_path, monkeypatch):
    diff, output = tmp_path / "comparison.json", tmp_path / "output.hwpx"
    real_open = Path.open
    def fail_output(path, *args, **kwargs):
        if path == output: raise OSError("simulated storage failure")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_output)
    with pytest.raises(OSError):
        _create_files([(diff, b"comparison"), (output, b"output")])
    assert not diff.exists() and not output.exists()


def test_api_inspect_compare_and_download_copy(client, source):
    files = {"file": ("기관양식.hwpx", source, "application/hwp+zip")}
    inspected = client.post("/api/hwpx/inspect", files=files)
    assert inspected.status_code == 200, inspected.text
    data = {"request_json": sample_request(source).model_dump_json()}
    preview = client.post("/api/hwpx/preview", files=files, data=data)
    assert preview.status_code == 200, preview.text
    result = client.post("/api/hwpx/replace", files=files, data={**data, "reviewed_output_sha256": preview.json()["output_sha256"]})
    assert result.status_code == 200 and result.headers["content-type"] == "application/hwp+zip"
    assert result.content == replace_document(source, sample_request(source))[0]
    assert result.headers["x-native-render-verified"] == "false"
    assert "filename*=UTF-8''" in result.headers["content-disposition"]
    assert client.get("/api/reports").json() == []  # uploaded documents are not saved as reports


def test_api_stale_review_unsupported_missing_and_boundary_errors(client, source):
    files = {"file": ("source.hwpx", source, "application/hwp+zip")}
    data = {"request_json": sample_request(source).model_dump_json()}
    assert client.post("/api/hwpx/replace", files=files, data=data).status_code == 422
    bad = client.post("/api/hwpx/replace", files=files, data={**data, "reviewed_output_sha256": "0" * 64})
    assert bad.status_code == 400 and bad.json()["code"] == "preview_changed"
    req = request(source).model_dump(); req["replacements"][0]["target_id"] = "missing"
    bad = client.post("/api/hwpx/preview", files=files, data={"request_json": json.dumps(req)})
    assert bad.status_code == 400 and bad.json()["code"] == "target_not_found"
    bad = client.post("/api/hwpx/preview", files=files, data={"request_json": request(source, text="도형 내부 · 수정 금지", before="도형", after="변경").model_dump_json()})
    assert bad.status_code == 400 and bad.json()["code"] == "unsupported_target"
    assert client.post("/api/hwpx/inspect", files=files, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/hwpx/inspect", files={"file": ("file.hwp", source)}).status_code == 400
    assert client.get("/preserve.html").status_code == 200


@pytest.mark.parametrize("payload", ["{bad json", "{}", '{"source_sha256":"wrong","replacements":[]}'])
def test_api_invalid_request_is_a_structured_error(client, source, payload):
    response = client.post("/api/hwpx/preview", files={"file": ("source.hwpx", source)}, data={"request_json": payload})
    assert response.status_code == 400 and response.json()["code"] == "invalid_request"
