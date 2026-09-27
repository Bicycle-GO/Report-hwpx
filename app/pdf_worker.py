"""Separate COM process. Only a newly created Hangul instance is used."""
import json
import os
import sys
from pathlib import Path

def main():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    hwp=None
    try:
        print("stage:create",file=sys.stderr,flush=True)
        hwp=win32com.client.DispatchEx("HWPFrame.HwpObject")
        hwp.XHwpWindows.Item(0).Visible=False
        module=os.environ.get("HWP_SECURITY_MODULE")
        if module and not hwp.RegisterModule("FilePathCheckDLL",module):
            raise RuntimeError("설정된 한글 보안모듈 등록에 실패했습니다.")
        print("stage:open",file=sys.stderr,flush=True)
        source,target=map(lambda p:str(Path(p).resolve()),sys.argv[1:3])
        if not hwp.Open(source,"HWPX",""):
            raise RuntimeError("한글에서 HWPX를 열지 못했습니다.")
        print("stage:render",file=sys.stderr,flush=True)
        pages=int(hwp.PageCount)
        if not hwp.SaveAs(target,"PDF",""):
            raise RuntimeError("한글 PDF 저장이 실패했습니다.")
        if len(sys.argv)>3:
            if not hwp.SaveAs(str(Path(sys.argv[3]).resolve()),"HWPX",""):
                raise RuntimeError("한글 재저장에 실패했습니다.")
        print(json.dumps({"pages":pages,"engine":"Hancom Hangul","rendered":True}))
    finally:
        if hwp is not None:
            try:
                print("stage:close",file=sys.stderr,flush=True)
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

if __name__=="__main__":
    main()

