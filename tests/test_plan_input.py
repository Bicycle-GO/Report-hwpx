import pytest
from lxml import etree as E
from app.plan_input import PlanInput, from_input
from app.models import BUILTINS, text_of, numbers, Report, Block
from app.validation import validate
from app.exporter import render_hwpx
from app.templates import extract_text, read_package, HP
from app.hml import from_generated_hwpx
from app.layout import paginate

def sample():
    return PlanInput(title="현장 조사 추진계획", summary="120필지의 조사 일정을 수립한다.",
                     background="조사기한 준수 필요\n자료 정확성 확보",
                     goals="84필지 우선 조사", scope="대상은 120필지",
                     strategy="부서 간 협업", steps="대상 선정\n현장 조사\n성과 검토",
                     schedule="10월 | 현장 조사 | 조사팀\n11월 | 성과 검토 | 검토팀",
                     budget="조사 | 600만원 | 견적 기준", effects="자료 정확성 향상",
                     requests="추진방향 승인 요청", notes="기상 상황 확인", confirmed=True)

def test_direct_input_has_all_sections_and_verbatim_evidence():
    data=sample()
    report=from_input(data)
    assert len(report.blocks)==11
    assert report.purpose=="plan" and not report.demo
    assert report.blocks[5].items==["대상 선정","현장 조사","성과 검토"]
    assert report.blocks[6].rows==[["10월","현장 조사","조사팀"],["11월","성과 검토","검토팀"]]
    assert report.blocks[7].columns==["항목","금액","산출근거"]
    assert all(s.confirmed and s.sensitivity=="internal" for s in report.sources)
    assert validate(report,BUILTINS["public"])["errors"]==0
    for b,s in zip(report.blocks,report.sources):
        assert b.source_ids==[s.id]
        assert numbers(text_of(b))<=numbers(s.text)

def test_optional_empty_sections_omitted_and_unchecked_not_verified():
    report=from_input(PlanInput(title="간단 계획",summary="직접 작성한 요지"))
    assert len(report.blocks)==len(report.sources)==1
    assert not report.sources[0].confirmed
    assert any(i["code"]=="unconfirmed" for i in validate(report,BUILTINS["public"])["issues"])
    with pytest.raises(ValueError,match="최소"):
        from_input(PlanInput(title="내용 없음"))

def test_prose_budget_schedule_preserved_not_guessed():
    data=PlanInput(title="계획",schedule="내부 협의 후 일정을 확정합니다.",budget="현재 검토 중입니다.")
    report=from_input(data)
    assert [b.kind for b in report.blocks]==["text","text"]
    assert [b.text for b in report.blocks]==[data.schedule,data.budget]
    assert not any(b.rows for b in report.blocks)

@pytest.mark.parametrize("values",[
    {"steps":"단계\n"*41},
    {"steps":"긴"*2001},
    {"schedule":"10월 | 조사"},
    {"budget":"항목 | 500만원 | 근거 | 초과"},
])
def test_ambiguous_or_oversized_input_fails_without_truncation(values):
    with pytest.raises(ValueError):
        from_input(PlanInput(title="계획",**values))

def test_long_paragraph_preserved_as_prose():
    content="긴 배경문장"*450
    report=from_input(PlanInput(title="계획",background=content))
    assert report.blocks[0].kind=="text"
    assert report.blocks[0].text==content

def test_api_input_create_save_reopen_and_export(client):
    response=client.post("/api/plans/from-input",json=sample().model_dump())
    assert response.status_code==200,response.text
    item=response.json()
    assert item["revision"]==1 and item["stage"]=="draft"
    assert client.get("/api/reports/"+item["id"]).json()["report"]==item["report"]
    result=client.post("/api/reports/"+item["id"]+"/export",json={"revision":1,"format":"hwpx"})
    assert result.status_code==200,result.text
    text=extract_text(result.content)
    assert all(s in text for s in ["보고요지","120필지","600만원","11월","단계별 추진 절차"])
    assert client.post("/api/plans/from-input",json={"title":"빈 문서"}).status_code==400
    assert client.post("/api/plans/from-input",json={"title":"계획","summary":"요지","template_id":"missing"}).status_code==400

def test_generated_hml_preserves_all_visible_text_and_table_cells(tmp_path):
    hwpx=tmp_path/"plan.hwpx";hml=tmp_path/"plan.hml"
    render_hwpx(from_input(sample()),BUILTINS["public"],hwpx)
    expected=from_generated_hwpx(hwpx,BUILTINS["public"],hml)
    root=E.parse(str(hml)).getroot()
    actual="".join("".join(c.itertext()) for c in root.iter("CHAR"))
    assert all(t in actual for t in expected)
    assert len(root.findall(".//TABLE"))>=5
    assert root.find(".//PAGEDEF").get("Width")=="59528"

def test_split_steps_keep_continuous_numbering(tmp_path):
    r=Report(title="긴 절차",blocks=[Block(kind="process",title="절차",items=[str(i)+"번째 단계 "*8 for i in range(1,35)])])
    layout=paginate(r,BUILTINS["public"])
    fragments=[f for page in layout["pages"] for f in page]
    assert len(fragments)>1
    assert fragments[0]["item_start"]==0
    assert fragments[1]["item_start"]==len(fragments[0]["block"]["items"])
    p=tmp_path/"steps.hwpx"
    render_hwpx(r,BUILTINS["public"],p)
    tables=read_package(p.read_bytes())["Contents/section0.xml"].findall(f".//{{{HP}}}tbl")
    nums=[]
    for table in tables:
        for row in table.findall(f"{{{HP}}}tr")[1:]:
            cell=row.find(f"{{{HP}}}tc")
            nums.append("".join(t.text or "" for t in cell.findall(f".//{{{HP}}}t")))
    assert nums==[str(i) for i in range(1,35)]
