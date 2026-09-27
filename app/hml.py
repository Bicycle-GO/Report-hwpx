"""Lossless bridge for the application's paragraph/table-only HWPX output.

This is deliberately not a general-purpose HWPX converter.
"""
from copy import deepcopy
from pathlib import Path
from lxml import etree as E
from .templates import read_package, HP

def hu(mm):
    return round(mm * 7200 / 25.4)

def from_generated_hwpx(source: Path, profile, destination: Path):
    parts = read_package(source.read_bytes())
    root = E.parse(str(Path(__file__).parent / "assets/hancom2014-base.hml")).getroot()
    head = root.find("HEAD")
    section = root.find("BODY/SECTION")
    secdef = deepcopy(section.find(".//SECDEF"))
    coldef = deepcopy(section.find(".//COLDEF"))
    table_base = deepcopy(section.find(".//TABLE"))
    for child in list(section):
        section.remove(child)
    for font in head.findall(".//FONT"):
        font.set("Name", profile.font)
    page = secdef.find("PAGEDEF")
    page.set("Width", str(hu(profile.width_mm)))
    page.set("Height", str(hu(profile.height_mm)))
    margin = page.find("PAGEMARGIN")
    for name in ("Left", "Right", "Top", "Bottom"):
        margin.set(name, str(hu(profile.margin_mm)))
    margin.set("Header", str(hu(8))); margin.set("Footer", str(hu(8)))
    for para in head.findall(".//PARASHAPE"):
        para.set("Align", "Left")
        m = para.find("PARAMARGIN")
        m.set("LineSpacing", "165"); m.set("Next", "350")
    styles = head.find(".//CHARSHAPELIST")
    prototype = deepcopy(styles[0])
    for child in list(styles):
        styles.remove(child)
    hh = "http://www.hancom.co.kr/hwpml/2011/head"
    char_map = {}
    for c in parts["Contents/header.xml"].findall(f".//{{{hh}}}charPr"):
        new = deepcopy(prototype)
        new_id = str(len(char_map))
        char_map[c.get("id")] = new_id
        new.set("Id", new_id)
        new.set("Height", c.get("height", "1100"))
        color = c.get("textColor", "#000000").lstrip("#")
        new.set("TextColor", str(int.from_bytes(bytes.fromhex(color), "little")))
        if c.find(f"{{{hh}}}bold") is not None:
            E.SubElement(new, "BOLD")
        styles.append(new)
    styles.set("Count", str(len(char_map)))
    # All inherited style references still need to point at defined styles.
    for style in head.findall(".//STYLE"):
        if style.get("CharShape") not in set(char_map.values()):
            style.set("CharShape", "0")
    expected = []
    table_id = 1000
    def paragraph(src):
        p = E.Element("P", ParaShape="3", Style="0",
                      PageBreak="true" if src.get("pageBreak") == "1" else "false")
        for run in src.findall(f"{{{HP}}}run"):
            text = E.SubElement(p, "TEXT", CharShape=char_map.get(run.get("charPrIDRef"), "0"))
            for el in run:
                tag = E.QName(el).localname
                if tag == "t":
                    content = "".join(el.itertext())
                    E.SubElement(text, "CHAR").text = content
                    if content.strip():
                        expected.append(content)
                elif tag == "tbl":
                    text.append(table(el))
                    E.SubElement(text, "CHAR")
                elif tag not in ("secPr", "ctrl"):
                    raise ValueError("HWP 호환 변환에서 지원하지 않는 개체: " + tag)
        if not len(p):
            E.SubElement(p, "TEXT", CharShape="0")
        return p
    def table(src):
        nonlocal table_id
        t = deepcopy(table_base)
        for row in t.findall("ROW"):
            t.remove(row)
        t.set("RowCount", src.get("rowCnt"))
        t.set("ColCount", src.get("colCnt"))
        obj = t.find("SHAPEOBJECT")
        table_id += 1
        obj.set("InstId", str(table_id))
        obj.find("POSITION").set("TreatAsChar", "true")
        size = src.find(f"{{{HP}}}sz")
        obj.find("SIZE").set("Width", size.get("width"))
        obj.find("SIZE").set("Height", size.get("height"))
        for edge in ("Left", "Right", "Top", "Bottom"):
            obj.find("OUTSIDEMARGIN").set(edge, "0")
        for src_row in src.findall(f"{{{HP}}}tr"):
            row = E.SubElement(t, "ROW")
            for src_cell in src_row.findall(f"{{{HP}}}tc"):
                cell = deepcopy(table_base.find("ROW/CELL"))
                addr = src_cell.find(f"{{{HP}}}cellAddr")
                sz = src_cell.find(f"{{{HP}}}cellSz")
                cell.set("ColAddr", addr.get("colAddr"))
                cell.set("RowAddr", addr.get("rowAddr"))
                cell.set("Width", sz.get("width"))
                cell.set("Height", sz.get("height"))
                cell.set("Header", "true" if src_cell.get("header") == "1" else "false")
                pl = cell.find("PARALIST")
                for old in list(pl):
                    pl.remove(old)
                for cp in src_cell.findall(f"{{{HP}}}subList/{{{HP}}}p"):
                    pl.append(paragraph(cp))
                row.append(cell)
        return t
    for name in sorted(parts):
        if name.startswith("Contents/section"):
            for p in parts[name].findall(f"{{{HP}}}p"):
                section.append(paragraph(p))
    first = section[0].find("TEXT")
    first.insert(0, secdef); first.insert(1, coldef)
    destination.write_bytes(E.tostring(root, encoding="utf-8", xml_declaration=True))
    return expected
