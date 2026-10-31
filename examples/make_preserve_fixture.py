"""Build a synthetic, reproducible template and its exact replacement request.

Run from the repository root: python -m examples.make_preserve_fixture
No real agency document, logo, personal data, or network access is used.
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

from hwpx import HwpxDocument
from lxml import etree as E

from app.preserve import EditRequest, inspect_document, replace_document
from app.templates import HP

FIXED_DATE = (2026, 1, 1, 0, 0, 0)


def _logo():
    """A tiny fictional green cross logo, encoded using only the standard library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = b"".join(b"\0" + b"".join(
        b"\x17\x4d\x48" if 6 <= x < 10 or 6 <= y < 10 else b"\xff\xff\xff"
        for x in range(16)) for y in range(16))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def build_fixture():
    doc = HwpxDocument.new()
    doc.page.setup(width_mm=210, height_mm=297, margins_mm={"left": 20, "right": 20, "top": 20, "bottom": 20})
    header = doc.parts.headers[0]
    header.ensure_font("맑은 고딕")
    body = doc.styles.ensure_run(font="맑은 고딕", size=11)
    bold = doc.styles.ensure_run(font="맑은 고딕", size=11, bold=True)
    doc.page.set_header(text="가상기관 · 예산심의 검토자료 [머리말 보존]")
    doc.page.set_footer(text="가상 예시 / 실제 업무 사용 금지 [꼬리말 보존]")
    doc.add_picture(_logo(), "png", width_mm=10, height_mm=10)
    doc.add_paragraph("2026년 도로대장 통합관리 예산 검토", char_pr_id_ref=bold)
    doc.add_paragraph("사업 목적: 도로대장 최신성 확보", char_pr_id_ref=body)
    doc.add_paragraph("검토 검토", char_pr_id_ref=body)
    p = doc.add_paragraph("같은 ", char_pr_id_ref=body)
    p.add_run("서식의 문장", char_pr_id_ref=body)
    p = doc.add_paragraph("보통 ", char_pr_id_ref=body)
    p.add_run("강조 문장", char_pr_id_ref=bold)
    table = doc.add_table(3, 2, width=48000, height=9000, char_pr_id_ref=body)
    for r, values in enumerate([["항목", "금액(백만원)"], ["유지관리", "240"], ["갱신지원", "120"]]):
        for c, value in enumerate(values):
            table.set_cell_text(r, c, value)
    merged = doc.add_table(2, 2, width=48000, height=6000, char_pr_id_ref=body)
    merged.merge_cells(0, 0, 0, 1)
    merged.set_cell_text(0, 0, "병합 제목 · 수정 금지")
    merged.set_cell_text(1, 0, "이 셀도 병합표에 속함")
    merged.set_cell_text(1, 1, "360")
    shape_p = doc.add_paragraph("", include_run=False)
    shape = shape_p.add_rectangle(24000, 6000, fill_color="#EDF4F1")
    shape.set_draw_text("도형 내부 · 수정 금지")
    second = doc.add_section()
    doc.page.set_header(text="둘째 구역 머리말 보존", section=second)
    doc.add_paragraph("둘째 구역의 원문 유지", section=second, char_pr_id_ref=body)
    buffer = doc.to_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buffer)) as src, zipfile.ZipFile(out, "w") as dst:
        dst.comment = b"synthetic preservation fixture"
        for name in src.namelist():
            raw = src.read(name)
            if name.startswith("Contents/section") and name.endswith(".xml"):
                root = E.fromstring(raw)
                links = []
                for kind in ("header", "footer"):
                    for ref in root.iter(f"{{{HP}}}{kind}Apply"):
                        linked = next(n for n in ref.getparent() if n.tag == f"{{{HP}}}{kind}" and n.get("id") == ref.get("idRef"))
                        links.append((ref, linked))
                # Only generated fixture data is serialized here. The editor never does this.
                for i, el in enumerate(root.iter()):
                    if "id" in el.attrib:
                        el.set("id", str(i))
                    for key in ("instid", "instanceID"):
                        if key in el.attrib:
                            el.set(key, str(i + 100))
                for ref, linked in links:
                    ref.set("idRef", linked.get("id"))
                raw = E.tostring(root, encoding="utf-8", xml_declaration=True)
            elif name == "Contents/content.hpf":
                root = E.fromstring(raw)
                for el in root.iter():
                    if E.QName(el).localname == "title":
                        el.text = "가상기관 양식 보존 치환 예제"
                    if el.get("name") in {"CreatedDate", "ModifiedDate", "date"}:
                        el.text = "2026-01-01T00:00:00Z"
                raw = E.tostring(root, encoding="utf-8", xml_declaration=True)
            info = zipfile.ZipInfo(name, FIXED_DATE)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            dst.writestr(info, raw)
    return out.getvalue()


def sample_request(data):
    inspected = inspect_document(data)
    def target(text):
        return next(t["id"] for t in inspected["targets"] if t["supported"] and t["text"] == text)
    return EditRequest.model_validate({"source_sha256": inspected["source_sha256"], "replacements": [
        {"target_id": target("2026년 도로대장 통합관리 예산 검토"), "before": "2026년", "after": "2027년"},
        {"target_id": target("사업 목적: 도로대장 최신성 확보"), "before": "최신성 확보", "after": "최신성 및 활용성 강화"},
        {"target_id": target("240"), "before": "240", "after": "360"},
    ]})


def main():
    root = Path(__file__).parent
    data = build_fixture()
    request = sample_request(data)
    # Validate the example as part of regeneration; do not commit an unchecked fixture.
    replace_document(data, request)
    (root / "preserve-template.hwpx").write_bytes(data)
    (root / "preserve-replacements.json").write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print("Created examples/preserve-template.hwpx and examples/preserve-replacements.json (synthetic).")


if __name__ == "__main__":
    main()
