"""Stateless upload/inspect/compare/copy flow, separate from style extraction."""
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .preserve import EditRequest, PreserveError, inspect_document, replace_document
from .templates import MAX_UPLOAD

router = APIRouter(prefix="/api/hwpx", tags=["기존 HWPX 수정"])


async def _upload(file):
    if not (file.filename or "").lower().endswith(".hwpx"):
        raise PreserveError("invalid_extension", "기존 .hwpx 파일을 선택하세요. 바이너리 .hwp는 지원하지 않습니다.")
    return await file.read(MAX_UPLOAD + 1)


def _request(raw):
    try:
        return EditRequest.model_validate_json(raw)
    except ValidationError as exc:
        issues = [".".join(map(str, e["loc"])) + ": " + e["msg"]
                  for e in exc.errors(include_input=False, include_url=False)[:3]]
        raise PreserveError("invalid_request", "치환 요청 형식을 확인하세요. " + "; ".join(issues)) from exc


@router.post("/inspect")
async def inspect(file: UploadFile = File(...)):
    return await run_in_threadpool(inspect_document, await _upload(file))


@router.post("/preview")
async def preview(file: UploadFile = File(...), request_json: str = Form(..., max_length=3000000)):
    request = _request(request_json)
    _, comparison = await run_in_threadpool(replace_document, await _upload(file), request)
    return comparison


@router.post("/replace")
async def replace(file: UploadFile = File(...), request_json: str = Form(..., max_length=3000000),
                  reviewed_output_sha256: str = Form(..., pattern=r"^[0-9a-f]{64}$")):
    request = _request(request_json)
    result, comparison = await run_in_threadpool(replace_document, await _upload(file), request)
    if comparison["output_sha256"] != reviewed_output_sha256:
        raise PreserveError("preview_changed", "비교한 치환 결과와 다릅니다. 변경 전후 비교를 다시 실행하세요.")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(file.filename).stem)[:90] + "-수정본.hwpx"
    return Response(result, media_type="application/hwp+zip", headers={
        "Content-Disposition": "attachment; filename=edited-copy.hwpx; filename*=UTF-8''" + quote(name),
        "X-Output-SHA256": comparison["output_sha256"],
        "X-Structure-Valid": "true", "X-Native-Render-Verified": "false",
    })
