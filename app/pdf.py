import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

def available():
    if sys.platform!="win32" or importlib.util.find_spec("win32com") is None:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,"HWPFrame.HwpObject"):
            return True
    except OSError:
        return False

def convert(source: Path, target: Path):
    if not available():
        raise ValueError("실제 HWPX PDF 변환에는 Windows용 한글과 pywin32가 필요합니다. requirements-windows-pdf.txt를 설치하세요.")
    env={**os.environ,"PYTHONIOENCODING":"utf-8"}
    try:
        proc=subprocess.run([sys.executable,"-m","app.pdf_worker",str(source),str(target)],capture_output=True,text=True,encoding="utf-8",timeout=55,env=env,
                            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),cwd=str(Path(__file__).resolve().parents[1]))
    except subprocess.TimeoutExpired as e:
        raise ValueError("한글 변환 시간이 초과되었습니다. 한글의 파일 접근 확인창·설치를 확인하세요. 관리자가 승인한 보안모듈이 있으면 HWP_SECURITY_MODULE을 설정할 수 있습니다.") from e
    if proc.returncode or not target.exists() or not target.read_bytes().startswith(b"%PDF"):
        raise ValueError("한글 PDF 변환에 실패했습니다. 한글에서 초안 HWPX를 직접 열어 확인해 주세요.")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError) as e:
        raise ValueError("한글 렌더링 결과를 확인하지 못했습니다.") from e

