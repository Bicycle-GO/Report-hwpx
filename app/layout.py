"""Conservative shared pagination estimates, never shrink fonts or omit content."""
import math
import unicodedata
from .models import Block, Profile, Report

def units(text):
    return sum(1 if unicodedata.east_asian_width(c) in "WF" else .55 for c in text)

def lines(text, width_mm, pt):
    capacity = max(3, width_mm / (pt * .353 * 1.08))
    return sum(max(1, math.ceil(units(line) / capacity)) for line in text.split("\n"))

def text_height(text, width, pt):
    return lines(text, width, pt) * pt * .353 * 1.65

def columns_for(items):
    longest = max((units(x) for x in items), default=0)
    return 1 if longest > 40 else 2 if longest > 18 else 3

def estimate(block, profile):
    width = profile.width_mm - 2 * profile.margin_mm
    pt = profile.body_pt
    height = 12 + text_height(block.title or " ", width, pt + 2)
    if block.text:
        height += text_height(block.text, width - 8, pt) + 3
    if block.kind in ("process", "strategy"):
        cellwidth = width * .85 - 5
        height += max(8, text_height("추진내용", cellwidth, pt) + 4)
        height += sum(max(8, text_height(t, cellwidth, pt) + 4) for t in block.items)
    elif block.items:
        height += sum(text_height(t, width - 8, pt) + 2 for t in block.items)
    if block.columns:
        cellwidth = width / max(1,len(block.columns)) - 5
        for row in [block.columns, *block.rows]:
            height += max((text_height(c, cellwidth, pt) for c in row), default=6) + 5
    if block.kind == "chart":
        height += len(block.labels) * 15 + 12
    if block.source_ids:
        height += 7
    return round(height, 1)

def fragments(block, profile, max_height):
    # Split at row/item/text boundaries; repeat the table header on every fragment.
    if estimate(block, profile) <= max_height:
        return [block]
    field = "rows" if block.rows else "items" if block.items else "labels" if block.labels else "text"
    if field == "text":
        # Character chunks preserve every character, including unbroken long strings.
        chunks = [block.text[i:i+220] for i in range(0,len(block.text),220)]
    else:
        chunks = getattr(block,field)
    if not chunks:
        return [block]
    result = []
    current = block.model_copy(deep=True)
    setattr(current,field, "" if field == "text" else [])
    if field == "labels":
        current.values=[]
    for idx, chunk in enumerate(chunks):
        candidate = current.model_copy(deep=True)
        if field == "text":
            candidate.text += chunk
        else:
            getattr(candidate,field).append(chunk)
        if field == "labels":
            candidate.values.append(block.values[idx] if idx < len(block.values) else 0)
        if estimate(candidate,profile) > max_height and getattr(current,field):
            result.append(current)
            current = block.model_copy(deep=True)
            current.title = block.title + " (계속)"
            if field != "text":
                current.text = ""
            setattr(current,field, chunk if field=="text" else [chunk])
            if field == "labels":
                current.values=[block.values[idx] if idx < len(block.values) else 0]
        else:
            current = candidate
    result.append(current)
    return result

def paginate(report: Report, profile: Profile):
    capacity = profile.height_mm - 2 * profile.margin_mm - 15
    title_height = text_height(report.title, profile.width_mm-2*profile.margin_mm, profile.title_pt) + 24
    pages = [[]]
    used = title_height
    oversize=[]
    for block in report.blocks:
        item_start=0
        for fragment in fragments(block, profile, capacity - 12):
            height=estimate(fragment, profile)
            if height > capacity:
                oversize.append(block.id)
            if used + height > capacity and (pages[-1] or used > 0):
                pages.append([])
                used=0
            pages[-1].append({"block": fragment.model_dump(), "height_mm": height, "continued": fragment.title != block.title, "item_start":item_start})
            item_start += len(fragment.items)
            used += height
    # References are appended by the exporter on their own page and disclosed here.
    refs = [s for s in report.sources if s.role=="evidence" and any(s.id in b.source_ids for b in report.blocks)]
    reference_blocks=[Block(id="ref-"+s.id, kind="text", title=s.name, text=" · ".join(v for v in [s.reference, "기준: "+s.as_of if s.as_of else "", "검토 확인" if s.confirmed else "미확인"] if v)) for s in refs]
    if reference_blocks:
        pages.append([])
        used=15
        for b in reference_blocks:
            for fragment in fragments(b,profile,capacity-15):
                height=estimate(fragment,profile)
                if used+height>capacity and pages[-1]:
                    pages.append([]); used=15
                pages[-1].append({"block":fragment.model_dump(),"height_mm":height,"continued":False,"reference":True})
                used+=height
    return {"pages":pages,"estimated_pages":len(pages),"oversize_ids":list(set(oversize)),
            "notice":"계산에 따른 예상 배치입니다. 실제 한글에서 줄바꿈·쪽수·잘림을 확인해 주세요."}

