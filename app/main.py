from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import storage, native_hwp
from .editing import ai_edit, enforce_locks, local_edit
from .exporter import render_hwpx
from .models import BUILTINS, KINDS, PURPOSES, Model, Profile, Report, uid
from .pdf import available as pdf_available, convert
from .planner import demo, plan
from .plan_input import PlanInput, from_input
from .templates import MAX_UPLOAD, extract_text, inspect_template
from .validation import validate

@asynccontextmanager
async def lifespan(app):
    storage.init()
    yield

app=FastAPI(title="보고서 공방 · HWPX Studio",version="0.2.0",lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","[::1]","testserver"])

@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.method not in ("GET","HEAD","OPTIONS"):
        origin=request.headers.get("origin")
        if origin and urlparse(origin).netloc!=request.headers.get("host"):
            return JSONResponse({"detail":"다른 사이트의 변경 요청은 허용하지 않습니다."},status_code=403)
        if request.headers.get("x-report-client")!="studio-v1":
            return JSONResponse({"detail":"로컬 보고서 화면에서 요청해 주세요."},status_code=403)
        length=request.headers.get("content-length","0") or "0"
        if not length.isdigit() or int(length)>12*1024*1024:
            return JSONResponse({"detail":"요청 크기는 12MB 이하여야 합니다."},status_code=413)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Cache-Control"]="no-store"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response

@app.exception_handler(ValueError)
async def bad_value(request,exc):
    return JSONResponse({"detail":str(exc)},status_code=400)

@app.exception_handler(KeyError)
async def missing(request,exc):
    return JSONResponse({"detail":str(exc)},status_code=404)

def profile_for(template_id):
    if template_id in BUILTINS:
        return BUILTINS[template_id]
    with storage.connect() as con:
        row=con.execute("SELECT * FROM templates WHERE id=?",(template_id,)).fetchone()
    if row is None or not row["approved"]:
        raise ValueError("확인·등록된 양식을 선택해 주세요.")
    return Profile.model_validate_json(row["profile"])

def loaded(report_id):
    item=storage.get(report_id)
    return item,Report.model_validate(item["report"])

def fingerprint(report,profile):
    return hashlib.sha256(storage.dump({"report":report.model_dump(),"profile":profile.model_dump()}).encode()).hexdigest()

class Revision(Model):
    revision:int=Field(ge=1)

class SaveRequest(Revision):
    report:Report
    note:str=Field(default="내용 수정",max_length=300)

class EditRequest(Revision):
    block_id:str
    instruction:str=Field(min_length=1,max_length=3000)
    use_ai:bool=False
    consent:bool=False

class ApproveRequest(Revision):
    reviewer:str=Field(min_length=1,max_length=100)
    native_reviewed:bool=False
    facts_reviewed:bool=False

class ExportRequest(Revision):
    format:str=Field(default="hwpx",pattern=r"^(hwpx|hwp|pdf|json)$")
    approved:bool=False

class RestoreRequest(Revision):
    target_revision:int=Field(ge=1)

@app.get("/api/config")
def config():
    return {"purposes":PURPOSES,"kinds":KINDS,"pdf_available":pdf_available(),"hangul":native_hwp.environment(),
            "ai_available":bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL")),
            "ai_model":os.environ.get("OPENAI_MODEL",""),"mode":"local"}

@app.get("/api/templates")
def templates():
    result=[{"id":key,"profile":p.model_dump(),"approved":True,"builtin":True} for key,p in BUILTINS.items()]
    with storage.connect() as con:
        for row in con.execute("SELECT * FROM templates ORDER BY created DESC"):
            result.append({"id":row["id"],"profile":json.loads(row["profile"]),"approved":bool(row["approved"]),"builtin":False,"metadata":json.loads(row["metadata"])})
    return result

@app.post("/api/templates")
async def upload_template(file:UploadFile=File(...)):
    if not (file.filename or "").lower().endswith(".hwpx"):
        raise ValueError("HWPX 양식 파일을 선택해 주세요.")
    data=await file.read(MAX_UPLOAD+1)
    profile,metadata=inspect_template(data,file.filename or "기관 양식")
    tid=uid()
    # Store the profile only: no old report facts, thumbnails or embedded attachments.
    with storage.connect() as con:
        con.execute("INSERT INTO templates VALUES (?,?,0,?,?)",(tid,profile.model_dump_json(),storage.dump(metadata),storage.now()))
    return {"id":tid,"profile":profile.model_dump(),"metadata":metadata,"approved":False}

@app.post("/api/templates/{template_id}/approve")
def approve_template(template_id:str,profile:Profile):
    with storage.connect() as con:
        changed=con.execute("UPDATE templates SET profile=?,approved=1 WHERE id=? AND approved=0",(profile.model_dump_json(),template_id))
        if changed.rowcount!=1:
            raise ValueError("이미 등록되었거나 존재하지 않는 양식입니다.")
    return {"id":template_id,"approved":True}

@app.post("/api/sources/extract")
async def extract_source(file:UploadFile=File(...)):
    name=file.filename or "자료"
    data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD:
        raise ValueError("자료는 10MB 이하여야 합니다.")
    ext=Path(name).suffix.lower()
    if ext==".hwpx":
        text=extract_text(data)
    elif ext in (".txt",".md",".csv",".json"):
        try:
            text=data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text=data.decode("cp949")
            except UnicodeDecodeError as e:
                raise ValueError("UTF-8 또는 CP949 텍스트 파일을 사용해 주세요.") from e
    else:
        raise ValueError("현재 TXT, MD, CSV, JSON, HWPX에서 텍스트를 가져올 수 있습니다.")
    if len(text)>40000:
        raise ValueError("자료가 40,000자를 초과합니다. 필요한 부분을 나누어 등록해 주세요.")
    return {"name":name,"text":text}

@app.get("/api/reports")
def list_reports():
    with storage.connect() as con:
        rows=con.execute("SELECT * FROM reports ORDER BY updated DESC").fetchall()
    return [{"id":r["id"],"title":json.loads(r["body"])["title"],"revision":r["revision"],"stage":r["stage"],"updated":r["updated"]} for r in rows]

@app.post("/api/reports")
def create_report(report:Report):
    profile_for(report.template_id)
    return storage.create(uid(),report.model_dump())

@app.post("/api/demo")
def create_demo():
    return storage.create(uid(),demo().model_dump())

@app.post("/api/plans/from-input")
def create_plan_from_input(body:PlanInput):
    profile_for(body.template_id)
    return storage.create(uid(),from_input(body).model_dump())

@app.post("/api/plan")
def build_plan(report:Report):
    profile_for(report.template_id)
    return plan(report).model_dump()

@app.get("/api/reports/{report_id}")
def get_report(report_id:str):
    return storage.get(report_id)

@app.put("/api/reports/{report_id}")
def save_report(report_id:str,body:SaveRequest):
    current,old=loaded(report_id)
    profile_for(body.report.template_id)
    enforce_locks(old,body.report)
    return storage.save(report_id,body.revision,body.report.model_dump(),body.note)

@app.post("/api/reports/{report_id}/confirm-plan")
def confirm_plan(report_id:str,body:Revision):
    current,report=loaded(report_id)
    if not report.blocks:
        raise ValueError("문서 부품을 먼저 추가해 주세요.")
    return storage.save(report_id,body.revision,report.model_dump(),"구성안 확인",stage="review")

@app.post("/api/reports/{report_id}/edit")
def edit_report(report_id:str,body:EditRequest):
    current,report=loaded(report_id)
    if current["revision"]!=body.revision:
        raise ValueError("문서가 변경되었습니다. 다시 불러와 주세요.")
    revised=ai_edit(report,body.block_id,body.instruction,body.consent) if body.use_ai else local_edit(report,body.block_id,body.instruction)
    enforce_locks(report,revised)
    return storage.save(report_id,body.revision,revised.model_dump(),("AI 제안 적용: " if body.use_ai else "부분 편집: ")+body.instruction[:150])

@app.get("/api/reports/{report_id}/validation")
def validation(report_id:str):
    _,report=loaded(report_id)
    return validate(report,profile_for(report.template_id))

@app.get("/api/reports/{report_id}/history")
def history(report_id:str):
    storage.get(report_id)
    with storage.connect() as con:
        rows=con.execute("SELECT revision,note,created,body FROM revisions WHERE report_id=? ORDER BY revision DESC",(report_id,)).fetchall()
    return [dict(row) for row in rows]

@app.post("/api/reports/{report_id}/restore")
def restore(report_id:str,body:RestoreRequest):
    _,old=loaded(report_id)
    with storage.connect() as con:
        row=con.execute("SELECT body FROM revisions WHERE report_id=? AND revision=?",(report_id,body.target_revision)).fetchone()
    if row is None:
        raise ValueError("복원할 버전이 없습니다.")
    report=Report.model_validate_json(row["body"])
    enforce_locks(old,report)
    return storage.save(report_id,body.revision,report.model_dump(),f"버전 {body.target_revision} 복원")

@app.post("/api/reports/{report_id}/approve")
def approve(report_id:str,body:ApproveRequest):
    current,report=loaded(report_id)
    profile=profile_for(report.template_id)
    if current["stage"]!="review":
        raise ValueError("먼저 구성안 확인 버튼을 누르고 최종 검토해 주세요.")
    check=validate(report,profile)
    if check["errors"]:
        raise ValueError("오류를 모두 해결한 뒤 승인할 수 있습니다.")
    if not body.native_reviewed or not body.facts_reviewed:
        raise ValueError("실제 HWPX 배치 및 원자료·수치 검토 확인이 필요합니다.")
    approval={"reviewer":body.reviewer,"time":storage.now(),"sha256":fingerprint(report,profile),
              "native_reviewed":True,"facts_reviewed":True,"review_type":"user-attestation"}
    return storage.save(report_id,body.revision,report.model_dump(),"최종 승인: "+body.reviewer,stage="approved",approval=approval)

@app.post("/api/reports/{report_id}/export")
def export(report_id:str,body:ExportRequest):
    item,report=loaded(report_id)
    if body.revision!=item["revision"]:
        raise ValueError("저장된 최신 버전으로 내보내 주세요.")
    profile=profile_for(report.template_id)
    if body.approved and (item["stage"]!="approved" or not item["approval"] or item["approval"]["sha256"]!=fingerprint(report,profile)):
        raise ValueError("최신 내용의 최종 승인이 필요합니다.")
    safe_name=re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",report.title)[:90]
    folder=tempfile.TemporaryDirectory(prefix="hwpx-studio-",ignore_cleanup_errors=True)
    root=Path(folder.name)
    try:
        if body.format=="json":
            path=root/"report.json"
            path.write_text(json.dumps(report.model_dump(),ensure_ascii=False,indent=2),encoding="utf-8")
            media="application/json"; extra={}
        else:
            path=root/"report.hwpx"
            render_hwpx(report,profile,path,approved=body.approved)
            media="application/hwp+zip";extra={}
            if body.format=="hwp":
                nativepath=root/"report.hwp"
                info=native_hwp.convert(path,nativepath,profile)
                extra={"X-Render-Pages":str(info["pages"]),"X-Native-Verified":"true"}
                path=nativepath;media="application/x-hwp"
            elif body.format=="pdf":
                pdfpath=root/"report.pdf"
                info=convert(path,pdfpath)
                extra={"X-Render-Pages":str(info["pages"])}
                path=pdfpath;media="application/pdf"
        return FileResponse(path,media_type=media,filename=safe_name+("-승인본" if body.approved else "-초안")+"."+body.format,
                            headers=extra,background=BackgroundTask(folder.cleanup))
    except Exception:
        folder.cleanup()
        raise

app.mount("/",StaticFiles(directory=Path(__file__).parent/"static",html=True),name="studio")

