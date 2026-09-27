from .layout import paginate
from .models import Profile, Report, numbers, text_of

def validate(report: Report, profile: Profile):
    issues=[]
    def add(level,code,message,block_id=None):
        issues.append(dict(level=level,code=code,message=message,block_id=block_id))
    sources={s.id:s for s in report.sources}
    if not report.blocks:
        add("error","empty","구성안을 생성하거나 문서 부품을 추가해 주세요.")
    if report.demo:
        add("warning","demo","가상 예시 데이터가 포함된 연습용 보고서입니다.")
    for block in report.blocks:
        content=block.text or block.items or block.rows or block.values
        if not content:
            add("error","empty_block",f"‘{block.title}’의 내용을 입력해 주세요.",block.id)
        linked=[]
        for sid in block.source_ids:
            source=sources.get(sid)
            if not source:
                add("error","missing_source","연결된 근거자료가 없습니다.",block.id)
            elif source.role!="evidence":
                add("error","style_as_fact","양식 참고자료는 사실의 근거로 사용할 수 없습니다.",block.id)
            else:
                linked.append(source)
                if not source.confirmed:
                    add("error","unconfirmed","연결된 원자료를 확인한 후 ‘검토 완료’를 선택해 주세요.",block.id)
                if not source.reference:
                    add("warning","reference","근거자료의 문서명·경로·URL 등 출처 위치가 비어 있습니다.",block.id)
        present=numbers(text_of(block))
        evidence=numbers("\n".join(s.text+"\n"+s.as_of for s in linked))
        unsupported=present-evidence
        if unsupported:
            add("error","unsupported_number","연결 근거에서 찾지 못한 수치: "+", ".join(sorted(unsupported)),block.id)
        elif not linked and block.kind!="request":
            add("warning","no_source","출처가 연결되지 않았습니다. 사실·주장의 근거를 직접 확인해 주세요.",block.id)
        if block.kind in ("table","comparison","timeline"):
            if not block.columns or not block.rows:
                add("error","table_empty","표의 제목행과 데이터행을 입력해 주세요.",block.id)
            elif any(len(r)!=len(block.columns) for r in block.rows):
                add("error","table_shape","표의 각 행은 제목행과 열 개수가 같아야 합니다.",block.id)
        if block.kind in ("process","strategy") and not block.items:
            add("error","diagram_empty","단계 또는 전략 항목을 입력해 주세요.",block.id)
        if block.kind=="chart":
            if not block.labels or len(block.labels)!=len(block.values):
                add("error","chart_shape","그래프의 항목명과 숫자 개수가 같아야 합니다.",block.id)
            if any(v<0 for v in block.values):
                add("error","negative","현재 막대그래프는 0 이상의 값만 지원합니다.",block.id)
            if not block.unit or not block.as_of or not linked:
                add("error","chart_metadata","그래프에는 단위, 기준시점, 근거자료가 필요합니다.",block.id)
    layout=paginate(report,profile)
    for bid in layout["oversize_ids"]:
        add("error","overflow","한 개 항목이 페이지 높이를 초과합니다. 문단이나 표 셀을 나눠 주세요.",bid)
    if layout["estimated_pages"]>report.target_pages:
        add("warning","page_budget",f"출처 페이지 포함 예상 {layout['estimated_pages']}쪽으로 목표 {report.target_pages}쪽을 초과합니다. 내용을 임의로 삭제하거나 글자를 줄이지 않았습니다.")
    add("info","visual_review","수치 검사는 문자열 대조입니다. 단위·합계·인과관계와 실제 HWPX 배치는 최종 검토가 필요합니다.")
    return {"issues":issues,"errors":sum(i["level"]=="error" for i in issues),"warnings":sum(i["level"]=="warning" for i in issues),"layout":layout}

