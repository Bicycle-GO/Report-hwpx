"""Turn user-authored sections into a plan without generating facts."""
from datetime import date
from pydantic import Field
from .models import Model, Report, Block, Source

class PlanInput(Model):
    title: str = Field(min_length=1, max_length=240)
    department: str = Field(default="", max_length=100)
    audience: str = Field(default="기관장", max_length=100)
    report_date: str = Field(default_factory=lambda: date.today().isoformat(), max_length=30)
    template_id: str = Field(default="public", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    target_pages: int = Field(default=3, ge=1, le=30)
    summary: str = Field(default="", max_length=3000)
    background: str = Field(default="", max_length=12000)
    goals: str = Field(default="", max_length=12000)
    scope: str = Field(default="", max_length=12000)
    strategy: str = Field(default="", max_length=12000)
    steps: str = Field(default="", max_length=12000)
    schedule: str = Field(default="", max_length=12000)
    budget: str = Field(default="", max_length=12000)
    effects: str = Field(default="", max_length=12000)
    requests: str = Field(default="", max_length=3000)
    notes: str = Field(default="", max_length=12000)
    confirmed: bool = False

SECTIONS = [
    ("summary", "보고요지", "summary"),
    ("background", "추진배경 및 필요성", "bullets"),
    ("goals", "추진목표", "bullets"),
    ("scope", "사업개요 및 추진범위", "text"),
    ("strategy", "추진방향 및 전략", "bullets"),
    ("steps", "단계별 추진 절차", "process"),
    ("schedule", "추진일정", "timeline"),
    ("budget", "소요예산", "table"),
    ("effects", "기대효과", "bullets"),
    ("requests", "행정사항 및 협조 요청", "request"),
    ("notes", "기타 검토사항", "text"),
]

def from_input(data: PlanInput) -> Report:
    blocks, sources = [], []
    for key, title, kind in SECTIONS:
        content = getattr(data, key)
        if not content:
            continue
        source = Source(name="직접 작성 · " + title, text=content,
                        reference="계획서 작성창에 사용자가 직접 입력한 내용",
                        as_of=data.report_date, confirmed=data.confirmed)
        sources.append(source)
        args = dict(kind=kind, title=title, source_ids=[source.id])
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if kind == "process":
            if len(lines) > 40 or any(len(line) > 2000 for line in lines):
                raise ValueError("추진 절차는 한 줄에 한 단계씩, 최대 40단계·단계당 2,000자까지 입력해 주세요.")
            args["items"] = lines
        elif kind == "bullets":
            # Long prose is kept verbatim as paragraphs, never cut to fit a list.
            if len(lines) <= 40 and all(len(line) <= 2000 for line in lines):
                args["items"] = lines
            else:
                args.update(kind="text", text=content)
        elif kind in ("table", "timeline") and any("|" in line or "\t" in line for line in lines):
            rows = [[cell.strip() for cell in line.split("\t" if "\t" in line else "|")] for line in lines]
            if any(len(row) != 3 for row in rows):
                raise ValueError(title + " 표는 한 줄에 3개 항목을 | 기호 또는 탭으로 구분해 주세요.")
            if len(rows) > 150 or any(len(cell) > 2000 for row in rows for cell in row):
                raise ValueError(title + " 표는 150행·셀당 2,000자까지 입력할 수 있습니다.")
            args.update(columns=["시기", "추진내용", "담당"] if kind == "timeline" else ["항목", "금액", "산출근거"], rows=rows)
        else:
            args.update(kind="text" if kind in ("table", "timeline") else kind, text=content)
        blocks.append(Block(**args))
    if not blocks:
        raise ValueError("보고요지, 추진배경, 추진 절차 등 최소 한 항목의 내용을 입력해 주세요.")
    return Report(title=data.title, department=data.department, audience=data.audience,
                  report_date=data.report_date, template_id=data.template_id,
                  target_pages=data.target_pages, purpose="plan", message=data.summary,
                  decision=data.requests, blocks=blocks, sources=sources)
