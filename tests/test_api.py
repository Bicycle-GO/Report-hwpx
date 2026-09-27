import json
from app.planner import demo
from app.models import Report

def create(client):
    res=client.post("/api/demo",json={})
    assert res.status_code==200,res.text
    return res.json()

def test_full_workflow_invalidation_and_history(client):
    item=create(client);rid=item["id"]
    assert client.get(f"/api/reports/{rid}/validation").json()["errors"]==0
    failed=client.post(f"/api/reports/{rid}/approve",json={"revision":item["revision"],"reviewer":"테스터","native_reviewed":True,"facts_reviewed":True})
    assert failed.status_code==400
    item=client.post(f"/api/reports/{rid}/confirm-plan",json={"revision":item["revision"]}).json()
    item=client.post(f"/api/reports/{rid}/approve",json={"revision":item["revision"],"reviewer":"자동 테스트 (실제 승인 아님)","native_reviewed":True,"facts_reviewed":True}).json()
    assert item["stage"]=="approved"
    exported=client.post(f"/api/reports/{rid}/export",json={"revision":item["revision"],"format":"hwpx","approved":True})
    assert exported.status_code==200 and exported.content[:2]==b"PK"
    item["report"]["title"]="수정된 제목"
    saved=client.put(f"/api/reports/{rid}",json={"revision":item["revision"],"report":item["report"]}).json()
    assert saved["stage"]=="draft" and saved["approval"] is None
    assert client.post(f"/api/reports/{rid}/export",json={"revision":saved["revision"],"approved":True}).status_code==400
    assert len(client.get(f"/api/reports/{rid}/history").json())==4

def test_stale_revision_cannot_overwrite(client):
    item=create(client);rid=item["id"]
    body={"revision":1,"report":item["report"]}
    assert client.put(f"/api/reports/{rid}",json=body).status_code==200
    assert client.put(f"/api/reports/{rid}",json=body).status_code==400
    assert client.get(f"/api/reports/{rid}").json()["revision"]==2

def test_undo_records_a_new_revision(client):
    item=create(client);rid=item["id"];original=item["report"]["title"]
    item["report"]["title"]="변경된 보고서"
    client.put(f"/api/reports/{rid}",json={"revision":1,"report":item["report"]})
    restored=client.post(f"/api/reports/{rid}/restore",json={"revision":2,"target_revision":1}).json()
    assert restored["revision"]==3 and restored["report"]["title"]==original

def test_cross_site_mutations_and_untrusted_host_rejected(client):
    assert client.post("/api/demo",json={},headers={"origin":"https://evil.example"}).status_code==403
    assert client.post("/api/demo",json={},headers={"X-Report-Client":""}).status_code==403
    assert client.get("/api/config",headers={"host":"evil.example"}).status_code==400

def test_import_text_and_bad_upload(client):
    res=client.post("/api/sources/extract",files={"file":("근거.csv","항목,수량\n사업,120".encode(),"text/csv")})
    assert res.status_code==200 and "120" in res.json()["text"]
    assert client.post("/api/templates",files={"file":("bad.hwpx",b"invalid","application/octet-stream")}).status_code==400
    assert client.post("/api/sources/extract",files={"file":("bad.pdf",b"%PDF","application/pdf")}).status_code==400

def test_custom_template_requires_review(client):
    from hwpx.templates import blank_document_bytes
    item=client.post("/api/templates",files={"file":("기관.hwpx",blank_document_bytes(),"application/hwp+zip")}).json()
    r=Report(template_id=item["id"]).model_dump()
    assert client.post("/api/reports",json=r).status_code==400
    assert client.post("/api/templates/"+item["id"]+"/approve",json=item["profile"]).status_code==200
    assert client.post("/api/reports",json=r).status_code==200
    assert client.post("/api/templates/"+item["id"]+"/approve",json=item["profile"]).status_code==400

def test_bad_chart_blocks_final_approval(client):
    item=create(client);rid=item["id"]
    item["report"]["blocks"][4]["values"][0]=99999
    item=client.put(f"/api/reports/{rid}",json={"revision":1,"report":item["report"]}).json()
    item=client.post(f"/api/reports/{rid}/confirm-plan",json={"revision":item["revision"]}).json()
    assert client.post(f"/api/reports/{rid}/approve",json={"revision":item["revision"],"reviewer":"test","native_reviewed":True,"facts_reviewed":True}).status_code==400

def test_lock_enforced_on_api_and_document_is_unchanged(client):
    item=create(client);rid=item["id"]
    item["report"]["blocks"][3]["rows"][0][1]="9999"
    result=client.put(f"/api/reports/{rid}",json={"revision":1,"report":item["report"]})
    assert result.status_code==400
    assert client.get(f"/api/reports/{rid}").json()["report"]["blocks"][3]["rows"][0][1]=="600"

def test_no_approval_claim_on_json_import(client):
    data=demo().model_dump();data["approval"]={"reviewer":"attacker"}
    assert client.post("/api/reports",json=data).status_code==422

