"""Editable paragraphs and tables using the conservative HWPX export path."""
from pathlib import Path
from hwpx import HwpxDocument
from .layout import paginate, text_height
from .models import Block, Profile, Report
from .templates import HP, read_package
from .hwpx_package import finalize_package

def hu(mm):
    return round(mm*7200/25.4)

def render_hwpx(report: Report, profile: Profile, destination: Path, *, approved=False):
    doc=HwpxDocument.new()
    doc.page.setup(width_mm=profile.width_mm,height_mm=profile.height_mm,
                   margins_mm={"left":profile.margin_mm,"right":profile.margin_mm,
                               "top":profile.margin_mm,"bottom":profile.margin_mm},
                   header_margin_mm=8,footer_margin_mm=8)
    head=doc.parts.headers[0]
    head.ensure_font(profile.font)
    body=doc.styles.ensure_run(font=profile.font,size=profile.body_pt)
    heading=doc.styles.ensure_run(font=profile.font,size=profile.body_pt+2,bold=True,color=profile.accent)
    title=doc.styles.ensure_run(font=profile.font,size=profile.title_pt,bold=True,color=profile.accent)
    small=doc.styles.ensure_run(font=profile.font,size=10,color="#66736E")
    para=head.ensure_paragraph_format(base_para_pr_id="0",alignment="LEFT",line_spacing_percent=165,
                                      margins={"prev":0,"next":350})
    center=head.ensure_paragraph_format(base_para_pr_id=para,alignment="CENTER")
    border=head.ensure_border_fill(border_color="#D7DFDC",border_width="0.12 mm",fill_color="#FFFFFF")
    shaded=head.ensure_border_fill(border_color="#D7DFDC",border_width="0.12 mm",fill_color="#EDF4F1")
    width=hu(profile.width_mm-2*profile.margin_mm)
    source_names={s.id:s.name for s in report.sources}
    def p(text="",style=body,break_before=False):
        # One hp:p per newline; do not put raw newlines in hp:t.
        result=None
        for i,line in enumerate(text.split("\n")):
            result=doc.add_paragraph(line,char_pr_id_ref=style,para_pr_id_ref=para,
                                     style_id_ref="0",inherit_style=False,
                                     pageBreak="1" if break_before and i==0 else "0")
        return result
    def table(columns,rows,fractions=None):
        data=[columns,*rows]
        if not columns:
            p("[확인 필요: 표의 열 정보가 없습니다.]")
            return
        if any(len(row)!=len(columns) for row in rows):
            raise ValueError("표의 각 행은 제목행과 열 수가 같아야 합니다.")
        fractions=fractions or [1/len(columns)]*len(columns)
        widths=[round(width*f) for f in fractions]
        widths[-1]=width-sum(widths[:-1])
        heights=[max(8,max(text_height(c,widths[i]*25.4/7200-5,profile.body_pt) for i,c in enumerate(row))+4) for row in data]
        t=doc.add_table(len(data),len(columns),width=width,height=hu(sum(heights)),border_fill_id_ref=border,
                        char_pr_id_ref=body,para_pr_id_ref=para)
        t.element.set("repeatHeader","1")
        for ri,row in enumerate(data):
            for ci in range(len(columns)):
                value=row[ci] if ci<len(row) else ""
                t.set_cell_text(ri,ci,value,split_paragraphs=True)
                cell=t.cell(ri,ci)
                cell.set_size(width=widths[ci],height=hu(heights[ri]))
                cell.element.set("header","1" if ri==0 else "0")
                t.set_cell_border_fill(ri,ci,shaded if ri==0 else border)
                for cp in cell.paragraphs:
                    cp.para_pr_id_ref=para
                    for run in cp.element.findall(f"{{{HP}}}run"):
                        run.set("charPrIDRef",heading if ri==0 else body)
        return t
    p(report.title,title)
    p(" · ".join(v for v in [report.department,report.audience,report.report_date] if v),small)
    p(("승인본" if approved else "검토용 초안") + (" · 가상 예시 데이터 / 실제 업무에 사용 금지" if report.demo else ""),small)
    layout=paginate(report,profile)
    for page_index,page in enumerate(layout["pages"]):
        if page_index:
            p("근거 및 출처" if page and page[0].get("reference") else report.title,small,True)
        for fragment in page:
            b=Block.model_validate(fragment["block"])
            p("□ "+b.title,heading)
            if b.text:
                if b.kind in ("summary","request"):
                    table(["핵심 내용"],[[b.text]])
                else:
                    p(b.text)
            if b.kind in ("process","strategy") and b.items:
                # Tables are editable in older Hangul and avoid drawText/shape filters.
                table(["단계" if b.kind=="process" else "구분", "추진내용"],
                      [[str(fragment.get("item_start",0)+i+1), item] for i,item in enumerate(b.items)], [.15,.85])
            elif b.items:
                for item in b.items:
                    p("ㅇ "+item)
            if b.kind in ("table","comparison","timeline"):
                table(b.columns,b.rows)
            if b.kind=="chart":
                if not b.labels or len(b.labels)!=len(b.values) or any(v<0 for v in b.values):
                    p("[확인 필요: 유효한 그래프 데이터를 입력해 주세요.]")
                else:
                    maximum=max(b.values,default=0)
                    p(f"단위: {b.unit or '미입력'} · 기준: {b.as_of or '미입력'}",small)
                    table(["항목","수치","비교 막대"], [
                        [label, f"{value:g} {b.unit}", "■"*max(1,round(20*value/maximum)) if value>0 and maximum>0 else "—"]
                        for label,value in zip(b.labels,b.values)])
                    p("막대 길이는 비교용이며, 정확한 값은 수치 열에 표시합니다.",small)
            if b.source_ids:
                p("근거: "+"; ".join(source_names.get(s,"연결 없음") for s in b.source_ids),small)
    # Schema validation and a read-back gate are independent from the web preview.
    result=doc.validate()
    if result.issues:
        raise ValueError("HWPX XML 검증 실패: "+"; ".join(str(x) for x in result.issues[:5]))
    destination.parent.mkdir(parents=True,exist_ok=True)
    doc.save_to_path(destination)
    finalize_package(destination, report)
    parts=read_package(destination.read_bytes())
    check=HwpxDocument.open(destination)
    again=check.validate()
    if again.issues:
        raise ValueError("저장된 HWPX 재검증에 실패했습니다.")
    actual="\n".join("".join(t.itertext()) for root in parts.values() for t in root.findall(f".//{{{HP}}}t"))
    # Include native shape text and table cells, not just top-level paragraphs.
    expected=[report.title]
    for b in report.blocks:
        expected.extend([b.title,*b.items,*b.columns,*(c for row in b.rows for c in row),*b.labels])
        # Pagination can split text inside words: compare ignoring only whitespace.
        if b.text and "".join(b.text.split()) not in "".join(actual.split()):
            # Continued fragment titles can intervene; verify each fragment separately instead.
            for page in layout["pages"]:
                for frag in page:
                    if frag["block"]["id"]==b.id:
                        expected.append(frag["block"]["text"])
    if any("".join(t.split()) not in "".join(actual.split()) for t in expected if t):
        raise ValueError("출력 내용 대조에 실패했습니다.")
    return {"schema_valid":True,"readback_valid":True,"estimated_pages":layout["estimated_pages"],
            "native_render_verified":False,"compatibility":"table-based","editable":"본문·표·단계별 절차표·수치 비교표. 도형 개체 없이 편집 가능."}

