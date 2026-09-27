"""Extract reusable style values into a CLEAN document; never import old facts."""
import io
import re
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from lxml import etree
from .models import Profile

HP="http://www.hancom.co.kr/hwpml/2011/paragraph"
HH="http://www.hancom.co.kr/hwpml/2011/head"
NS={"hp":HP,"hh":HH}
MAX_UPLOAD=10*1024*1024

def read_package(data: bytes):
    if len(data)>MAX_UPLOAD:
        raise ValueError("HWPX는 10MB 이하여야 합니다.")
    try:
        z=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("정상적인 HWPX ZIP 파일이 아닙니다.") from e
    with z:
        infos=z.infolist()
        if len(infos)>400 or sum(i.file_size for i in infos)>40*1024*1024:
            raise ValueError("압축 해제 크기 또는 파일 개수가 허용 범위를 초과합니다.")
        names=[i.filename for i in infos]
        if len(names)!=len(set(names)):
            raise ValueError("중복된 ZIP 경로가 있습니다.")
        for i in infos:
            p=PurePosixPath(i.filename)
            if p.is_absolute() or ".." in p.parts or chr(92) in i.orig_filename or ":" in i.filename or i.flag_bits&1:
                raise ValueError("안전하지 않거나 암호화된 패키지입니다.")
        if "Contents/header.xml" not in names or "Contents/section0.xml" not in names:
            raise ValueError("HWPX의 필수 문서 구조가 없습니다.")
        mime=z.read("mimetype") if "mimetype" in names else b""
        if mime.strip()!=b"application/hwp+zip":
            raise ValueError("HWPX mimetype(application/hwp+zip)이 아닙니다.")
        result={}
        for name in names:
            if name=="Contents/header.xml" or re.fullmatch(r"Contents/section\d+\.xml",name):
                raw=z.read(name)
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise ValueError("DTD 또는 외부 엔터티를 포함한 XML은 허용하지 않습니다.")
                try:
                    result[name]=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
                except etree.XMLSyntaxError as e:
                    raise ValueError("HWPX XML을 읽을 수 없습니다.") from e
        return result

def extract_text(data: bytes):
    parts=read_package(data)
    sections=sorted((n for n in parts if "section" in n),key=lambda n:int(re.search(r"section(\d+)",n)[1]))
    return "\n".join("".join(p.itertext()) for n in sections for p in parts[n].findall(".//hp:t",NS))

def inspect_template(data: bytes, name: str):
    parts=read_package(data)
    header=parts["Contents/header.xml"]
    section=parts["Contents/section0.xml"]
    counts=Counter()
    for run in section.findall(".//hp:run",NS):
        counts[run.get("charPrIDRef","0")]+=sum(len(t.text or "") for t in run.findall("hp:t",NS))
    chosen=counts.most_common(1)[0][0] if counts else "0"
    props={n.get("id"):n for n in header.findall(".//hh:charPr",NS)}
    cp=props.get(chosen)
    font="맑은 고딕"
    body=11
    if cp is not None:
        body=max(10,min(18,int(cp.get("height","1100"))/100))
        fontref=cp.find("hh:fontRef",NS)
        if fontref is not None:
            fonts=header.findall(".//hh:fontface",NS)
            for face in fonts:
                if face.get("lang")=="HANGUL":
                    for f in face.findall("hh:font",NS):
                        if f.get("id")==fontref.get("hangul"):
                            font=f.get("face",font)
    page=section.find(".//hp:pagePr",NS)
    params={}
    if page is not None:
        params["width_mm"]=round(int(page.get("width","59528"))*25.4/7200,2)
        params["height_mm"]=round(int(page.get("height","84186"))*25.4/7200,2)
        margin=page.find("hp:margin",NS)
        if margin is not None:
            params["margin_mm"]=max(10,min(35,round(int(margin.get("left","5669"))*25.4/7200,2)))
    profile=Profile(name=name[:180],font=font,body_pt=body,**params)
    metadata={"mode":"style-extraction","sections":len(parts)-1,"notice":"용지, 왼쪽 여백을 기준으로 한 공통 여백, 대표 본문 글꼴·크기를 추출했습니다. 로고·머리말·병합표·도형 배치는 복제하지 않습니다. 원문 내용은 새 보고서에 포함되지 않습니다."}
    return profile,metadata

