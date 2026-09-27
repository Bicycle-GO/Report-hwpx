"""Deterministic offline planning: never invent evidence, dates or budgets."""
from .models import Block, Report

STRUCTURES = {
    "budget": [("request", "승인 요청사항"), ("bullets", "추진 필요성"), ("comparison", "현행·개선 비교"), ("table", "소요예산"), ("text", "기대효과")],
    "plan": [("summary", "핵심 추진방향"), ("bullets", "추진 배경"), ("strategy", "추진전략"), ("process", "추진절차"), ("timeline", "추진일정"), ("request", "요청사항")],
    "performance": [("summary", "주요 성과"), ("chart", "목표·실적 비교"), ("bullets", "성과 분석"), ("text", "미달 원인 및 후속조치"), ("request", "향후 계획")],
    "issue": [("summary", "핵심 쟁점"), ("bullets", "현황 및 문제점"), ("comparison", "대안별 비교"), ("text", "판단기준 및 검토의견"), ("request", "의사결정 요청")],
    "cooperation": [("request", "협조 요청사항"), ("bullets", "업무 개요"), ("table", "역할분담"), ("process", "처리 절차"), ("timeline", "제출물 및 기한")],
}


def plan(report: Report) -> Report:
    result = report.model_copy(deep=True)
    result.blocks = []
    used_message = False
    for kind, title in STRUCTURES[report.purpose]:
        b = Block(kind=kind, title=title)
        if kind == "request":
            b.text = report.decision
            b.required = True
        elif kind == "summary" or (kind == "bullets" and not used_message):
            b.text = report.message
            used_message = True
        if kind in ("comparison", "table", "timeline"):
            b.columns = {"comparison": ["구분", "현행 / 대안 A", "개선 / 대안 B"], "table": ["항목", "내용", "근거"], "timeline": ["일정", "추진내용", "담당"]}[kind]
        result.blocks.append(b)
    # Preserve each excerpt exactly; long excerpts are split into separate blocks.
    for source in report.sources:
        if source.role == "evidence" and source.text:
            for offset in range(0, len(source.text), 12000):
                result.blocks.append(Block(kind="text", title="근거자료 발췌 · " + source.name[:150], text=source.text[offset:offset+12000], source_ids=[source.id]))
    if len(result.blocks) > 80:
        raise ValueError("근거자료가 너무 많습니다. 보고서에 사용할 자료를 줄여 주세요.")
    return result


def demo() -> Report:
    from .models import Source
    s = Source(id="sample-data", name="예시 사업 기획자료 (가상 데이터)", text="시범 촬영 대상은 120필지이며, 현재 84필지를 완료하였다. 조사기한 준수를 위해 공동 촬영과 검수를 추진한다. 예산은 촬영 600만원, 영상 제작 250만원, 검수 150만원이다. 대상 선정, 현장 촬영, 영상 제작, 성과 검토, 납품의 순서로 추진한다. 10월에는 대상 선정과 촬영, 11월에는 영상 제작과 납품을 진행한다.", reference="프로그램 사용법을 위한 가상 예시 · 실제 업무에 사용 금지", as_of="2026-09", confirmed=True, sensitivity="public")
    refs = [s.id]
    return Report(title="농지 드론촬영 사업 추진계획", purpose="plan", audience="기관장", department="농지관리팀", message="공동 촬영과 단계별 검수로 조사기한 준수", decision="시범 촬영 추진방향 승인 및 관계부서 협조", sources=[s], demo=True, blocks=[
        Block(kind="summary", title="보고 요지", text="공동 촬영과 단계별 검수를 통해 조사기한을 준수하고, 시범 촬영의 추진방향을 확정하고자 합니다.", source_ids=refs),
        Block(kind="bullets", title="추진 배경", items=["시범 촬영 대상 120필지 중 84필지 촬영 완료", "공동 촬영과 검수로 남은 조사일정 관리"], source_ids=refs),
        Block(kind="process", title="단계별 추진절차", items=["대상 선정", "현장 촬영", "영상 제작", "성과 검토", "납품"], source_ids=refs),
        Block(kind="table", title="소요예산", columns=["항목", "금액 (만원)", "내용"], rows=[["촬영", "600", "현장 촬영"], ["영상 제작", "250", "영상 제작"], ["검수", "150", "성과 검토"]], source_ids=refs, locked=True, required=True),
        Block(kind="chart", title="시범 촬영 현황", labels=["대상", "완료"], values=[120,84], unit="필지", as_of="2026-09", source_ids=refs),
        Block(kind="timeline", title="향후 일정", columns=["시기", "주요 내용"], rows=[["10월", "대상 선정 · 현장 촬영"], ["11월", "영상 제작 · 납품"]], source_ids=refs),
        Block(kind="request", title="검토 요청사항", text="시범 촬영 추진방향 승인 및 관계부서 협조", required=True),
    ])

