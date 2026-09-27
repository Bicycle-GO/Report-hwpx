from __future__ import annotations

import re
from datetime import date
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


Purpose = Literal["budget", "plan", "performance", "issue", "cooperation"]
Kind = Literal["summary", "text", "bullets", "comparison", "table", "process", "strategy", "timeline", "chart", "request"]


class Source(Model):
    id: str = Field(default_factory=uid, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=180)
    role: Literal["evidence", "style"] = "evidence"
    sensitivity: Literal["internal", "public"] = "internal"
    text: str = Field(default="", max_length=40000)
    reference: str = Field(default="", max_length=1000)
    as_of: str = Field(default="", max_length=60)
    confirmed: bool = False


class Block(Model):
    id: str = Field(default_factory=uid, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    kind: Kind = "text"
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=12000)
    items: list[str] = Field(default_factory=list, max_length=40)
    columns: list[str] = Field(default_factory=list, max_length=8)
    rows: list[list[str]] = Field(default_factory=list, max_length=150)
    labels: list[str] = Field(default_factory=list, max_length=30)
    values: list[float] = Field(default_factory=list, max_length=30)
    unit: str = Field(default="", max_length=40)
    as_of: str = Field(default="", max_length=60)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    locked: bool = False
    required: bool = False

    @model_validator(mode="after")
    def bounded_content(self):
        if any(len(s) > 2000 for s in self.items + self.columns + self.labels):
            raise ValueError("항목 하나는 2,000자 이하여야 합니다.")
        if any(len(row) > 8 or any(len(c) > 2000 for c in row) for row in self.rows):
            raise ValueError("표는 최대 8열이며 셀 하나는 2,000자 이하여야 합니다.")
        table_kinds = ("table", "comparison", "timeline")
        if (self.columns or self.rows) and self.kind not in table_kinds:
            raise ValueError("표 데이터는 표·비교표·일정표 부품에만 사용할 수 있습니다.")
        if (self.labels or self.values or self.unit or self.as_of) and self.kind != "chart":
            raise ValueError("그래프 데이터는 그래프 부품에만 사용할 수 있습니다.")
        if self.items and self.kind not in ("bullets", "process", "strategy"):
            raise ValueError("항목 목록은 개조식·절차도·전략체계도에만 사용할 수 있습니다.")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("출처 연결이 중복되었습니다.")
        return self


class Report(Model):
    title: str = Field(default="새 업무보고", min_length=1, max_length=240)
    purpose: Purpose = "plan"
    audience: str = Field(default="기관장", max_length=100)
    department: str = Field(default="", max_length=100)
    report_date: str = Field(default_factory=lambda: date.today().isoformat(), max_length=30)
    message: str = Field(default="", max_length=3000)
    decision: str = Field(default="", max_length=3000)
    target_pages: int = Field(default=2, ge=1, le=30)
    template_id: str = Field(default="public", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    sources: list[Source] = Field(default_factory=list, max_length=40)
    blocks: list[Block] = Field(default_factory=list, max_length=80)
    demo: bool = False

    @model_validator(mode="after")
    def unique_ids(self):
        for seq in (self.sources, self.blocks):
            if len({obj.id for obj in seq}) != len(seq):
                raise ValueError("문서 내 식별자가 중복되었습니다.")
        return self


class Profile(Model):
    name: str = Field(min_length=1, max_length=180)
    font: str = Field(default="맑은 고딕", min_length=1, max_length=100)
    body_pt: float = Field(default=11, ge=10, le=18)
    title_pt: float = Field(default=21, ge=14, le=32)
    accent: str = Field(default="#174D48", pattern=r"^#[0-9A-Fa-f]{6}$")
    width_mm: float = Field(default=210, ge=140, le=320)
    height_mm: float = Field(default=297, ge=180, le=440)
    margin_mm: float = Field(default=20, ge=10, le=35)


PURPOSES = {"budget": "예산 확보", "plan": "사업 추진계획", "performance": "성과보고", "issue": "현안·대안 검토", "cooperation": "협조 요청"}
KINDS = {"summary": "요약상자", "text": "본문", "bullets": "개조식 본문", "comparison": "비교표", "table": "자료표", "process": "추진 절차도", "strategy": "전략체계도", "timeline": "일정표", "chart": "수치 비교그래프", "request": "요청사항"}
BUILTINS = {
    "public": Profile(name="기관 업무보고", accent="#174D48"),
    "policy": Profile(name="정책 검토", font="함초롬바탕", accent="#264B76", body_pt=12),
    "brief": Profile(name="성과 브리핑", accent="#744E34", title_pt=23),
}


def text_of(block: Block) -> str:
    return "\n".join([block.title, block.text, *block.items, *block.columns, *(c for r in block.rows for c in r), *block.labels, *(format(v, ".12g") for v in block.values), block.unit, block.as_of])


def numbers(text: str) -> set[str]:
    # Lexical support only: this cannot prove units, dates or business meaning.
    from decimal import Decimal, InvalidOperation
    found = set()
    for token in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?", text):
        try:
            found.add(format(Decimal(token.replace(",", "")).normalize(), "f"))
        except InvalidOperation:
            pass
    return found

