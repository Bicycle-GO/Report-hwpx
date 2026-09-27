"""Optional Windows export for older Hangul installations."""
import json
import os
import subprocess
import sys
from pathlib import Path
from .hml import from_generated_hwpx
from .pdf import available

def environment():
    result = {"available": available(), "version": "", "legacy": False}
    if not result["available"]:
        return result
    try:
        import winreg
        import win32api
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID") as key:
            clsid = winreg.QueryValueEx(key, "")[0]
        try:
            server_key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + r"\LocalServer32")
        except FileNotFoundError:
            server_key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + r"\LocalServer32", 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
        with server_key as key:
            command = winreg.QueryValueEx(key, "")[0]
        exe = command.split('"')[1] if command.startswith('"') else command.split(" -")[0]
        info = win32api.GetFileVersionInfo(exe, "\\")
        major, minor = info["FileVersionMS"] >> 16, info["FileVersionMS"] & 65535
        result.update(version=f"{major}.{minor}.{info['FileVersionLS'] >> 16}.{info['FileVersionLS'] & 65535}", legacy=major < 10)
    except (OSError, ImportError, KeyError, IndexError):
        pass
    return result

def convert(source: Path, target: Path, profile):
    if not available():
        raise ValueError("HWP 내보내기는 Windows용 한글과 pywin32 설치가 필요합니다.")
    hml = target.with_suffix(".hml")
    expected = from_generated_hwpx(source, profile, hml)
    check = target.with_suffix(".check.json")
    check.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    try:
        result = subprocess.run([sys.executable, "-m", "app.native_hwp_worker",
                                 str(hml.resolve()), str(target.resolve()), str(check.resolve())],
                                cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, encoding="utf-8", timeout=40,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise ValueError("한글 HWP 변환 응답이 지연되었습니다. 열려 있는 한글 오류창을 확인해 주세요.") from exc
    finally:
        hml.unlink(missing_ok=True)
        check.unlink(missing_ok=True)
    if result.returncode or not target.is_file():
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "응답 없음"
        raise ValueError("한글 HWP 변환 실패: " + detail[:220])
    return json.loads(result.stdout)
