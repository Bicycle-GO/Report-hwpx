import io
import zipfile
from pathlib import Path
import pytest
from pydantic import ValidationError
from hwpx import HwpxDocument
from hwpx.templates import blank_document_bytes
from app.models import Block, Report, Source, BUILTINS
from app.planner import demo,plan
from app.validation import validate
from app.layout import paginate
from app.templates import inspect_template,read_package,extract_text,HP
from app.exporter import render_hwpx
from app.editing import ai_edit,enforce_locks,local_edit

PROFILE=BUILTINS["public"]

def codes(r):
    return {i["code"] for i in validate(r,PROFILE)["issues"] if i["level"]=="error"}

def test_purpose_changes_structure_without_inventing_facts():
    a=plan(Report(purpose="budget",decision="추진방향 승인"))
    b=plan(Report(purpose="performance"))
    assert a.blocks[0].kind=="request"
    assert any(x.kind=="chart" for x in b.blocks)
    assert all(not x.values and not x.rows for x in a.blocks+b.blocks)

def test_style_reference_never_becomes_evidence_or_planned_content():
    r=Report(sources=[Source(id="old",name="옛 보고서",role="style",text="지난해 사업비 900억원")])
    result=plan(r)
    assert "900" not in str([b.model_dump() for b in result.blocks])
    result.blocks=[Block(kind="text",text="900억원",source_ids=["old"])]
    assert {"style_as_fact","unsupported_number"}<=codes(result)

def test_numeric_provenance_and_missing_chart_metadata():
    r=demo()
    assert not codes(r)
    chart=next(b for b in r.blocks if b.kind=="chart")
    chart.values[0]=999
    chart.unit=""
    assert {"unsupported_number","chart_metadata"}<=codes(r)
    chart.values=[float("nan")]
    with pytest.raises(ValidationError):
        Report.model_validate(r.model_dump())

def test_missing_sources_unconfirmed_and_irregular_table():
    r=demo()
    r.sources[0].confirmed=False
    r.blocks[0].source_ids=["does-not-exist"]
    r.blocks[3].rows[0].append("extra")
    assert {"missing_source","unconfirmed","table_shape"}<=codes(r)

def test_locks_cannot_be_bypassed_by_unlock_and_edit_together():
    r=demo();new=r.model_copy(deep=True)
    new.blocks[3].locked=False
    new.blocks[3].rows[0][1]="999"
    with pytest.raises(ValueError,match="잠금"):
        enforce_locks(r,new)
    new=r.model_copy(deep=True)
    new.sources[0].text="바뀐 원자료"
    with pytest.raises(ValueError,match="근거"):
        enforce_locks(r,new)

def test_required_blocks_and_demo_flag_preserved():
    r=demo();n=r.model_copy(deep=True);n.blocks=n.blocks[:-1]
    with pytest.raises(ValueError,match="필수"):
        enforce_locks(r,n)
    n=r.model_copy(deep=True);n.demo=False
    with pytest.raises(ValueError,match="가상"):
        enforce_locks(r,n)

def test_local_edit_is_scoped_and_unknown_commands_fail():
    r=demo();b=r.blocks[2]
    new=local_edit(r,b.id,"단계: 선정 / 촬영 / 검수 / 납품")
    assert new.blocks[2].items==["선정","촬영","검수","납품"]
    assert new.blocks[3]==r.blocks[3]
    with pytest.raises(ValueError):
        local_edit(r,b.id,"예산을 적당히 늘려줘")

def test_ai_never_sends_internal_evidence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test-key")
    monkeypatch.setenv("OPENAI_MODEL","test-model")
    monkeypatch.setattr("app.editing.urlopen",lambda *a,**k:pytest.fail("Network must not be called"))
    r=demo();r.sources[0].sensitivity="internal"
    with pytest.raises(ValueError,match="공개"):
        ai_edit(r,r.blocks[0].id,"요약",True)
    with pytest.raises(ValueError,match="동의"):
        ai_edit(r,r.blocks[0].id,"요약",False)

def test_long_content_paginates_without_loss():
    text="긴제목과근거문구를그대로유지하는시험문장입니다."*220
    r=Report(title="긴 제목 "*20,blocks=[Block(kind="text",title="본문",text=text),Block(kind="table",title="큰 표",columns=["항목","내용"],rows=[[str(i),"줄이 긴 표의 내용 "*6] for i in range(100)]),Block(kind="process",title="긴 절차",items=["단계 설명 "+str(i) for i in range(30)])])
    layout=paginate(r,PROFILE)
    fs=[f["block"] for p in layout["pages"] for f in p if not f.get("reference")]
    assert "".join(f["text"] for f in fs if f["id"]==r.blocks[0].id)==text
    assert sum(len(f["rows"]) for f in fs)==100
    assert sum(len(f["items"]) for f in fs)==30
    assert layout["estimated_pages"]>5
    assert PROFILE.body_pt==11

def test_native_export_schema_and_readback(tmp_path):
    path=tmp_path/"sample.hwpx"
    result=render_hwpx(demo(),PROFILE,path)
    assert result["schema_valid"] and result["readback_valid"]
    d=HwpxDocument.open(path)
    assert not d.validate().issues
    parts=read_package(path.read_bytes())
    section=parts["Contents/section0.xml"]
    assert len(section.findall(f".//{{{HP}}}tbl"))>=3
    assert not section.findall(f".//{{{HP}}}rect")
    assert not section.findall(f".//{{{HP}}}drawText")
    assert len(section.findall(f".//{{{HP}}}tbl"))>=5
    ids=[el.get("id") for el in section.findall(f".//{{{HP}}}subList")]
    assert len(ids)==len(set(ids)) and all(ids)
    text=extract_text(path.read_bytes())
    assert "가상 예시 데이터" in text and "600" in text and "납품" in text
    with zipfile.ZipFile(path) as z:
        assert z.namelist()[0]=="mimetype"
        assert "Preview/PrvImage.png" not in z.namelist()
        assert "농지 드론촬영".encode() in z.read("Preview/PrvText.txt")
        assert b"synthetic-fixture-author" not in z.read("Contents/content.hpf")
        assert z.read("mimetype")==b"application/hwp+zip"
        assert z.getinfo("mimetype").compress_type==zipfile.ZIP_STORED

def test_custom_style_extraction_drops_old_facts(tmp_path):
    path=tmp_path/"template.hwpx"
    render_hwpx(demo(),PROFILE,path)
    profile,metadata=inspect_template(path.read_bytes(),"기관 양식")
    assert profile.font==PROFILE.font
    assert profile.width_mm==pytest.approx(210,abs=.01)
    assert "120" not in profile.model_dump_json()
    assert metadata["mode"]=="style-extraction"

@pytest.mark.parametrize("bad_path",["../outside.xml","/absolute.xml","C:/bad.xml","Contents\\bad.xml"])
def test_zip_traversal_rejected(bad_path):
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blank_document_bytes())) as src, zipfile.ZipFile(out,"w") as dest:
        for item in src.infolist():
            dest.writestr(item.filename,src.read(item.filename))
        info=zipfile.ZipInfo("entry.xml")
        info.filename=bad_path  # bypass Windows writer normalization to test raw archive paths
        dest.writestr(info,b"bad")
    with pytest.raises(ValueError,match="안전"):
        read_package(out.getvalue())

def test_xml_entity_rejected():
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blank_document_bytes())) as src, zipfile.ZipFile(out,"w") as dest:
        for item in src.infolist():
            content=src.read(item.filename)
            if item.filename=="Contents/section0.xml":
                content=b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
            dest.writestr(item.filename,content)
    with pytest.raises(ValueError,match="DTD"):
        read_package(out.getvalue())


def test_incompatible_block_data_is_rejected_instead_of_silently_dropped():
    with pytest.raises(ValidationError):
        Block(kind="text",rows=[["hidden","120"]],columns=["name","value"])
    with pytest.raises(ValidationError):
        Block(kind="summary",labels=["hidden"],values=[120])
    r=demo()
    r.blocks[3].locked=False
    with pytest.raises(ValueError,match="직접 검토"):
        local_edit(r,r.blocks[3].id,"단계: 새 단계")

def test_ai_rejects_extra_fields_and_changed_numbers(monkeypatch):
    import json
    monkeypatch.setenv("OPENAI_API_KEY","test-key")
    monkeypatch.setenv("OPENAI_MODEL","test-model")
    r=demo()
    b=r.blocks[1]
    class Response:
        def __init__(self,change):
            self.body=io.BytesIO(json.dumps({"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps(change)}]}]}).encode())
        def read(self,*args):return self.body.read(*args)
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr("app.editing.urlopen",lambda *a,**k:Response({"title":b.title,"text":b.text,"items":b.items,"id":"overridden"}))
    with pytest.raises(ValueError,match="형식"):
        ai_edit(r,b.id,"문장 다듬기",True)
    monkeypatch.setattr("app.editing.urlopen",lambda *a,**k:Response({"title":b.title,"text":"999 필지","items":[]}))
    with pytest.raises(ValueError,match="수치"):
        ai_edit(r,b.id,"문장 다듬기",True)

@pytest.mark.parametrize("template",["public","policy","brief"])
def test_every_builtin_template_generates_schema_valid_document(template,tmp_path):
    r=demo();r.template_id=template
    result=render_hwpx(r,BUILTINS[template],tmp_path/(template+".hwpx"))
    assert result["schema_valid"] and result["readback_valid"]

def test_many_rows_and_long_paragraph_export_without_loss(tmp_path):
    r=Report(title="긴 문서 검증",blocks=[
        Block(kind="text",title="긴 본문",text="내용과근거를생략하지않는긴문장입니다."*130),
        Block(kind="table",title="행이 많은 표",columns=["항목","설명"],rows=[[f"항목 {i}","설명 "*10] for i in range(45)]),
        Block(kind="process",title="다단계 절차",items=[f"검토 단계 {i}" for i in range(20)])
    ])
    file=tmp_path/"long.hwpx"
    assert render_hwpx(r,PROFILE,file)["schema_valid"]
    text=extract_text(file.read_bytes())
    assert "항목 44" in text and "검토 단계 19" in text

