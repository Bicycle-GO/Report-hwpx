"""Conservative, transactional text edits in an existing HWPX package.

Do not use the new-document exporter or serialize user XML. Only the character
data of approved hp:t elements is patched; every other member payload survives
byte for byte. This is structural preservation, not a Hangul layout renderer.
"""
from __future__ import annotations

import copy
import hashlib
import io
import posixpath
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.parsers import expat
from xml.sax.saxutils import escape

from lxml import etree as E
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .templates import HH, HP, MAX_UPLOAD

HS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
NS = {"hp": HP, "hh": HH, "opf": OPF, "ocf": OCF}
SECTION = re.compile(r"Contents/section(\d+)\.xml")
NOTICE = (
    "원본의 머리말·꼬리말·로고·문단 서식·표 구조를 보존하고 지정한 텍스트만 수정합니다. "
    "병합표·중첩표·도형·필드·주석 내부는 수정하지 않습니다. "
    "실제 한글의 줄바꿈·쪽수·넘침은 검증하지 않았습니다. "
    "원본의 미리보기·문서 속성은 그대로이므로 이전 내용이 보일 수 있습니다."
)


class PreserveError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class Replacement(BaseModel):
    # Existing report models strip whitespace. This operation must not do so.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    target_id: str = Field(min_length=1, max_length=160)
    before: str = Field(min_length=1, max_length=12000)
    after: str = Field(max_length=12000)
    expected_count: StrictInt = Field(default=1, ge=1, le=100)


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacements: list[Replacement] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_targets(self):
        ids = [r.target_id for r in self.replacements]
        if len(ids) != len(set(ids)):
            raise ValueError("한 요청에서는 각 문단을 한 번만 지정하세요. 중복·연쇄 치환은 지원하지 않습니다.")
        return self


@dataclass
class Target:
    id: str
    section: str
    location: str
    kind: str
    paragraph: E._Element
    reason: str = ""

    @property
    def nodes(self):
        return self.paragraph.findall("hp:run/hp:t", NS)

    @property
    def text(self):
        return "".join("".join(n.itertext()) for n in self.nodes)

    def public(self):
        return {"id": self.id, "section": self.section, "location": self.location,
                "kind": self.kind, "text": self.text, "supported": not self.reason,
                "reason": self.reason,
                "length_locked": self.paragraph.find("hp:linesegarray", NS) is not None}


@dataclass
class Package:
    infos: list[zipfile.ZipInfo]
    parts: dict[str, bytes]
    roots: dict[str, E._Element]
    sections: list[str]
    comment: bytes


def _error(message, code="invalid_package"):
    raise PreserveError(code, message)


def _xml(raw, name):
    if b"\x00" in raw:
        _error(f"{name}: UTF-8 XML만 지원합니다.", "unsupported_encoding")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        _error(f"{name}: 서식 보존 수정은 UTF-8 XML만 지원합니다.", "unsupported_encoding")
    encoding = re.match(r"\s*<\?xml\b[^?]*\bencoding\s*=\s*['\"]([^'\"]+)", text)
    if encoding and encoding[1].lower() not in ("utf-8", "utf8"):
        _error(f"{name}: UTF-8 XML만 지원합니다.", "unsupported_encoding")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        _error(f"{name}: DTD·엔터티 선언은 허용하지 않습니다.")
    try:
        root = E.fromstring(raw, E.XMLParser(resolve_entities=False, no_network=True,
                                           load_dtd=False, remove_blank_text=False))
    except (E.XMLSyntaxError, ValueError) as exc:
        raise PreserveError("invalid_xml", f"{name}: 정상적인 XML이 아닙니다.") from exc
    if root.getroottree().docinfo.doctype:
        _error(f"{name}: DTD는 허용하지 않습니다.")
    return root


def _reference(href, base, parts):
    parsed = urlsplit(href)
    path = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not path
            or path.startswith("/") or "\\" in path or "\x00" in path or ":" in path):
        _error("패키지에 외부 또는 안전하지 않은 참조가 있습니다.")
    # Hancom packages commonly use archive-root paths; also accept OPF-relative paths.
    candidates = [path, posixpath.normpath(posixpath.join(posixpath.dirname(base), path))]
    matches = {n for n in candidates if n in parts and not n.endswith("/")}
    if len(matches) != 1:
        _error(f"누락되었거나 모호한 패키지 참조입니다: {href}")
    return matches.pop()


def _number(el, name, *, minimum=0):
    try:
        value = int(el.get(name, ""))
    except (AttributeError, ValueError):
        _error(f"표의 {name} 값이 올바르지 않습니다.")
    if value < minimum:
        _error(f"표의 {name} 값이 허용 범위를 벗어납니다.")
    return value


def _table_reason(table):
    rows, cols = _number(table, "rowCnt", minimum=1), _number(table, "colCnt", minimum=1)
    if rows * cols > 10000:
        _error("표 격자는 최대 10,000칸까지 검사합니다.")
    trs = table.findall("hp:tr", NS)
    if len(trs) != rows:
        _error("표의 행 수와 rowCnt가 다릅니다.")
    occupied = set()
    merged = False
    for ri, row in enumerate(trs):
        for cell in row.findall("hp:tc", NS):
            addr, span = cell.find("hp:cellAddr", NS), cell.find("hp:cellSpan", NS)
            r, c = _number(addr, "rowAddr"), _number(addr, "colAddr")
            rs, cs = _number(span, "rowSpan", minimum=1), _number(span, "colSpan", minimum=1)
            if r != ri or r + rs > rows or c + cs > cols:
                _error("표 셀의 주소·병합 범위가 올바르지 않습니다.")
            cells = {(y, x) for y in range(r, r + rs) for x in range(c, c + cs)}
            if occupied & cells:
                _error("표 셀 주소·병합 범위가 중복됩니다.")
            occupied.update(cells)
            merged |= rs != 1 or cs != 1
    if len(occupied) != rows * cols:
        _error("표 격자에 누락된 셀이 있습니다.")
    if merged:
        return "병합표는 표 전체를 보존하며 내부 텍스트 수정은 지원하지 않습니다."
    if table.findall(".//hp:tbl", NS) or any(a.tag == f"{{{HP}}}tbl" for a in table.iterancestors()):
        return "중첩표 내부 수정은 지원하지 않습니다."
    parent = table.getparent()
    if (parent is None or parent.tag != f"{{{HP}}}run" or parent.getparent() is None
            or parent.getparent().getparent() is None
            or parent.getparent().getparent().tag != f"{{{HS}}}sec"):
        return "본문에 직접 배치한 단순 표만 수정할 수 있습니다."
    return ""


def _validate_structure(pkg):
    roots, parts = pkg.roots, pkg.parts
    if roots["Contents/header.xml"].tag != f"{{{HH}}}head":
        _error("HWPX header.xml의 루트가 올바르지 않습니다.")
    for name in pkg.sections:
        if roots[name].tag != f"{{{HS}}}sec":
            _error(f"{name}: HWPX 구역의 루트가 올바르지 않습니다.")
    container = roots["META-INF/container.xml"]
    if container.tag != f"{{{OCF}}}container":
        _error("HWPX container.xml의 루트가 올바르지 않습니다.")
    rootfiles = container.findall("ocf:rootfiles/ocf:rootfile", NS)
    resolved = [_reference(n.get("full-path", ""), "", parts) for n in rootfiles]
    if "Contents/content.hpf" not in resolved:
        _error("HWPX 컨테이너의 content.hpf 참조가 없습니다.")
    opf = roots["Contents/content.hpf"]
    if opf.tag != f"{{{OPF}}}package":
        _error("HWPX content.hpf의 루트가 올바르지 않습니다.")
    manifest = {}
    for item in opf.findall("opf:manifest/opf:item", NS):
        ident = item.get("id")
        if not ident or ident in manifest:
            _error("HWPX manifest의 식별자가 없거나 중복됩니다.")
        manifest[ident] = _reference(item.get("href", ""), "Contents/content.hpf", parts)
    spine = []
    for ref in opf.findall("opf:spine/opf:itemref", NS):
        if ref.get("idref") not in manifest:
            _error("HWPX spine의 참조 대상이 없습니다.")
        spine.append(manifest[ref.get("idref")])
    if any(spine.count(name) != 1 for name in pkg.sections) or "Contents/header.xml" not in manifest.values():
        _error("HWPX manifest·spine에 구역 또는 머리정보 참조가 누락·중복되었습니다.")
    header = roots["Contents/header.xml"]
    references = {
        "charPrIDRef": {n.get("id") for n in header.findall(".//hh:charPr", NS)},
        "paraPrIDRef": {n.get("id") for n in header.findall(".//hh:paraPr", NS)},
        "styleIDRef": {n.get("id") for n in header.findall(".//hh:style", NS)},
    }
    for name in pkg.sections:
        header_footer_ids = {kind: {n.get("id") for n in roots[name].iter(f"{{{HP}}}{kind}")}
                             for kind in ("header", "footer")}
        for node in roots[name].iter():
            if node.tag in (f"{{{HP}}}run", f"{{{HP}}}p"):
                for key, values in references.items():
                    if key in node.attrib and node.get(key) not in values:
                        _error(f"{name}: 존재하지 않는 문단·글자 스타일 참조입니다 ({key}).")
            for kind in ("header", "footer"):
                if node.tag == f"{{{HP}}}{kind}Apply" and node.get("idRef") not in header_footer_ids[kind]:
                    _error(f"{name}: 머리말·꼬리말 참조 대상이 없습니다.")
            binary = node.get("binaryItemIDRef")
            if binary and binary not in manifest:
                _error(f"{name}: 포함된 이미지·바이너리의 참조 대상이 없습니다.")
        for table in roots[name].iter(f"{{{HP}}}tbl"):
            _table_reason(table)


def _read(data):
    if len(data) > MAX_UPLOAD:
        _error("HWPX는 10MB 이하여야 합니다.", "package_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 400 or sum(i.file_size for i in infos) > 40 * 1024 * 1024:
                _error("압축 해제 크기 또는 파일 개수가 허용 범위를 초과합니다.")
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                _error("중복된 ZIP 경로가 있습니다.")
            for info in infos:
                name = info.filename
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or "\\" in info.orig_filename
                        or ":" in name or "\x00" in info.orig_filename or info.flag_bits & 1
                        or str(path) != name.rstrip("/") or stat.S_ISLNK(info.external_attr >> 16)
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    _error("안전하지 않거나 암호화된 패키지 경로·압축 방식입니다.")
                if re.search(r"(?:signature|encryption)", name, re.I):
                    _error("전자서명·암호화가 있는 패키지 수정은 지원하지 않습니다.", "signed_or_encrypted")
            required = {"mimetype", "Contents/header.xml", "Contents/section0.xml",
                        "Contents/content.hpf", "META-INF/container.xml"}
            if not required <= set(names):
                _error("HWPX의 필수 패키지 구성요소가 없습니다.")
            if names[0] != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
                _error("HWPX mimetype은 첫 번째 비압축 항목이어야 합니다.")
            # Reading every member also verifies CRCs without extracting any files.
            parts = {i.filename: archive.read(i) for i in infos}
            comment = archive.comment
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as exc:
        raise PreserveError("invalid_package", "정상적인 HWPX ZIP 파일이 아닙니다 (CRC·압축 포함).") from exc
    if parts["mimetype"] != b"application/hwp+zip":
        _error("HWPX mimetype(application/hwp+zip)이 아닙니다.")
    roots = {name: _xml(raw, name) for name, raw in parts.items()
             if name.lower().endswith((".xml", ".hpf", ".rdf"))}
    sections = sorted((n for n in parts if SECTION.fullmatch(n)), key=lambda n: int(SECTION.fullmatch(n)[1]))
    pkg = Package(infos, parts, roots, sections, comment)
    _validate_structure(pkg)
    return pkg


def _paragraph_reason(p):
    if p.get("merged", "0") not in ("0", "false"):
        return "변경 추적·병합 표시가 있는 문단은 지원하지 않습니다."
    for child in p:
        if child.tag == f"{{{HP}}}linesegarray":
            continue
        if child.tag != f"{{{HP}}}run":
            return "알 수 없는 문단 요소가 있어 수정하지 않습니다."
        for node in child:
            if node.tag == f"{{{HP}}}t" and not len(node):
                continue
            if node.tag == f"{{{HP}}}secPr":
                continue  # page settings and header/footer payloads stay untouched
            if node.tag == f"{{{HP}}}ctrl" and len(node) and all(
                    n.tag in {f"{{{HP}}}colPr", f"{{{HP}}}header", f"{{{HP}}}footer"} for n in node):
                continue
            return "도형·표·필드·제어문자 또는 복합 텍스트가 있는 문단은 수정하지 않습니다."
    text = "".join(n.text or "" for n in p.findall("hp:run/hp:t", NS))
    if not text:
        return "빈 문단은 치환할 텍스트가 없습니다."
    if len(text) > 12000:
        return "12,000자를 초과하는 문단은 수정하지 않습니다."
    if not _valid_text(text):
        return "줄바꿈·탭·제어문자가 포함된 문단은 수정하지 않습니다."
    return ""


def _inventory(pkg):
    targets = []
    for name in pkg.sections:
        root, prefix = pkg.roots[name], PurePosixPath(name).stem
        spans = _text_spans(pkg.parts[name])
        nodes = list(root.iter(f"{{{HP}}}t"))
        if len(nodes) != len(spans):
            _error("텍스트 위치 검사에 실패했습니다.", "invalid_xml")
        opaque = {node for node, (start, end, _) in zip(nodes, spans)
                  if b"<" in pkg.parts[name][start:end]}
        mapped = {}
        for pi, p in enumerate(root.findall("hp:p", NS)):
            mapped[p] = Target(f"{prefix}/p{pi}", name, f"본문 {pi + 1}문단", "paragraph", p)
        for ti, table in enumerate(root.iter(f"{{{HP}}}tbl")):
            reason = _table_reason(table)
            for row in table.findall("hp:tr", NS):
                for cell in row.findall("hp:tc", NS):
                    addr = cell.find("hp:cellAddr", NS)
                    r, c = int(addr.get("rowAddr")), int(addr.get("colAddr"))
                    for pi, p in enumerate(cell.findall("hp:subList/hp:p", NS)):
                        mapped[p] = Target(f"{prefix}/table{ti}/r{r}c{c}/p{pi}", name,
                                           f"표 {ti + 1} · {r + 1}행 {c + 1}열 · {pi + 1}문단", "cell", p, reason)
        for pi, p in enumerate(root.iter(f"{{{HP}}}p")):
            target = mapped.get(p)
            if target is None:
                ancestors = {a.tag for a in p.iterancestors()}
                label = "머리말" if f"{{{HP}}}header" in ancestors else "꼬리말" if f"{{{HP}}}footer" in ancestors else "도형·주석·기타 영역"
                target = Target(f"{prefix}/protected{pi}", name, label, "protected", p,
                                f"{label} 내부 텍스트는 보존만 하며 수정하지 않습니다.")
            target.reason = target.reason or _paragraph_reason(p)
            if not target.reason and any(n in opaque for n in target.nodes):
                target.reason = "CDATA·주석을 포함한 텍스트는 수정하지 않습니다."
            targets.append(target)
    if len(targets) > 20000:
        _error("문단은 최대 20,000개까지 검사합니다.")
    return targets


def _validation(pkg):
    return {"structure_valid": True, "xml_valid": True, "crc_valid": True,
            "references_valid": True, "table_geometry_valid": True,
            "sections": len(pkg.sections), "members": len(pkg.parts),
            "full_schema_checked": False, "native_render_verified": False}


def inspect_document(data: bytes):
    pkg = _read(data)
    targets = [t.public() for t in _inventory(pkg)]
    return {"source_sha256": hashlib.sha256(data).hexdigest(), "notice": NOTICE,
            "validation": _validation(pkg), "targets": targets,
            "supported_count": sum(t["supported"] for t in targets),
            "unsupported_count": sum(not t["supported"] for t in targets)}


def _text_spans(raw):
    """Map parsed hp:t nodes to byte offsets, independent of namespace prefixes."""
    parser = expat.ParserCreate(namespace_separator="}")
    spans, stack = [], []

    def start(tag, attrs):
        entry = None
        if tag == HP + "}t":
            at, quote = parser.CurrentByteIndex, None
            end = at + 1
            while end < len(raw):
                char = raw[end]
                if quote is not None:
                    if char == quote:
                        quote = None
                elif char in (34, 39):
                    quote = char
                elif char == 62:
                    break
                end += 1
            empty = raw[at:end].rstrip().endswith(b"/")
            entry = [end + 1, end + 1, empty]
            spans.append(entry)
        stack.append(entry)

    def end(tag):
        entry = stack.pop()
        if entry is not None and not entry[2]:
            entry[1] = parser.CurrentByteIndex

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.Parse(raw, True)  # already parsed and DTD/entity checked by _read
    return spans


def _valid_text(text):
    # No paragraph/line/control insertion and no invalid XML 1.0 characters.
    return all((32 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD
                or 0x10000 <= ord(c) <= 0x10FFFF) and c not in "\u2028\u2029" for c in text)


def _utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def _replacement_nodes(target, edit):
    text = target.text
    count = text.count(edit.before)
    if count == 0:
        _error(f"{target.location}: 지정한 원문을 찾을 수 없습니다.", "text_not_found")
    if count != edit.expected_count:
        _error(f"{target.location}: 원문이 {count}회 있습니다. expected_count({edit.expected_count})와 다릅니다.", "match_count_mismatch")
    if edit.before == edit.after:
        _error("변경 전후 텍스트가 같습니다.", "no_change")
    if not _valid_text(edit.before) or not _valid_text(edit.after):
        _error("줄바꿈·탭·제어문자 삽입·치환은 지원하지 않습니다.", "unsupported_text")
    after = text.replace(edit.before, edit.after)
    if len(after) > 12000:
        _error("치환 후 문단은 12,000자 이하여야 합니다.", "text_too_large")
    if target.paragraph.find("hp:linesegarray", NS) is not None and _utf16_len(edit.before) != _utf16_len(edit.after):
        _error("줄 배치 캐시가 있는 문단은 UTF-16 길이가 같은 치환만 지원합니다. 캐시는 임의 변경하지 않습니다.", "layout_cache_length")
    nodes = target.nodes
    values = [n.text or "" for n in nodes]
    offsets, pos = [], 0
    for value in values:
        offsets.append((pos, pos + len(value)))
        pos += len(value)
    starts = [m.start() for m in re.finditer(re.escape(edit.before), text)]
    for start in reversed(starts):
        end = start + len(edit.before)
        indices = [i for i, (a, b) in enumerate(offsets) if a < end and b > start]
        styles = {tuple(sorted(nodes[i].getparent().attrib.items())) for i in indices}
        if len(styles) != 1:
            _error("서로 다른 글자 서식 경계를 넘는 치환은 지원하지 않습니다. 각 구간을 나누어 지정하세요.", "style_boundary")
        first = indices[0]
        for i in indices:
            a, b = offsets[i]
            left, right = max(0, start - a), min(b - a, end - a)
            values[i] = values[i][:left] + (edit.after if i == first else "") + values[i][right:]
    if "".join(values) != after:
        _error("치환 내용 검증에 실패했습니다.", "verification_failed")
    return {node: value for node, value in zip(nodes, values) if (node.text or "") != value}, after, count


def replace_document(data: bytes, request: EditRequest):
    """Validate all edits, then return (new bytes, comparison). No filesystem writes."""
    if hashlib.sha256(data).hexdigest() != request.source_sha256:
        _error("검사한 원본과 파일이 다릅니다. 다시 검사하세요.", "source_changed")
    pkg = _read(data)
    targets = {t.id: t for t in _inventory(pkg)}
    changed, changes, expected = {}, [], {}
    for edit in request.replacements:
        target = targets.get(edit.target_id)
        if target is None:
            _error(f"수정 대상이 없습니다: {edit.target_id}", "target_not_found")
        if target.reason:
            _error(f"{target.location}: {target.reason}", "unsupported_target")
        updates, after, count = _replacement_nodes(target, edit)
        changed.setdefault(target.section, {}).update(updates)
        expected[target.id] = after
        changes.append({"target_id": target.id, "section": target.section, "location": target.location,
                        "kind": target.kind, "before": target.text, "after": after,
                        "match_count": count, "replacement": edit.model_dump(exclude={"target_id"})})
    modified = dict(pkg.parts)
    for name, updates in changed.items():
        raw = pkg.parts[name]
        nodes = list(pkg.roots[name].iter(f"{{{HP}}}t"))
        spans = _text_spans(raw)
        if len(nodes) != len(spans):
            _error("텍스트 위치 검증에 실패했습니다.", "verification_failed")
        patches = []
        for node, (start, end, empty) in zip(nodes, spans):
            if node not in updates:
                continue
            if empty or b"<" in raw[start:end]:
                _error("CDATA·주석·빈 축약 태그의 치환은 지원하지 않습니다.", "unsupported_text")
            patches.append((start, end, escape(updates[node]).encode("utf-8")))
        for start, end, value in sorted(patches, reverse=True):
            raw = raw[:start] + value + raw[end:]
        modified[name] = raw
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = pkg.comment
        for info in pkg.infos:
            archive.writestr(copy.copy(info), modified[info.filename])
    result = output.getvalue()
    verified = _read(result)
    actual = {t.id: t for t in _inventory(verified)}
    if actual.keys() != targets.keys():
        _error("수정 후 문단 구조가 달라졌습니다.", "verification_failed")
    for ident, original in targets.items():
        if actual[ident].text != expected.get(ident, original.text):
            _error("수정 후 텍스트 대조에 실패했습니다.", "verification_failed")
    # Patching character data plus payload equality proves all unrelated XML and
    # binaries are preserved; keep an explicit gate for future implementation edits.
    for name in pkg.parts.keys() - changed.keys():
        if verified.parts[name] != pkg.parts[name]:
            _error("수정 대상 이외의 패키지 내용이 변경되었습니다.", "verification_failed")
    comparison = {"source_sha256": request.source_sha256,
                  "output_sha256": hashlib.sha256(result).hexdigest(),
                  "changes": changes, "changed_members": list(changed),
                  "preserved_members": len(pkg.parts) - len(changed),
                  "validation": {**_validation(verified), "text_readback_valid": True,
                                 "unrelated_members_identical": True}, "notice": NOTICE}
    return result, comparison
