"""Read/write document bytes through Hangul, without file-open permission prompts."""
import base64
import json
import sys
from lxml import etree as E
from pathlib import Path

def main():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
        hwp.XHwpWindows.Item(0).Visible = False
        source, target = map(Path, sys.argv[1:3])
        expected = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        # BSTR contains UTF-16 text, irrespective of the on-disk UTF-8 source.
        xml_text = source.read_text(encoding="utf-8").replace("encoding='utf-8'", "encoding='UTF-16'")
        if not hwp.SetTextFile(xml_text, "HWPML2X", ""):
            raise RuntimeError("한글에서 호환 문서를 구성하지 못했습니다.")
        encoded = hwp.GetTextFile("HWP", "")
        raw = base64.b64decode(encoded)
        if not raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise RuntimeError("한글이 올바른 HWP 파일을 반환하지 않았습니다.")
        hwp.Clear(1)
        if not hwp.SetTextFile(encoded, "HWP", ""):
            raise RuntimeError("생성한 HWP의 실제 한글 재열기에 실패했습니다.")
        restored = E.fromstring(hwp.GetTextFile("HWPML2X", "").encode("utf-16"))
        actual = "".join("".join("".join(c.itertext()) for c in restored.iter("CHAR")).split())
        missing = [x for x in expected if "".join(x.split()) not in actual]
        if missing:
            raise RuntimeError("HWP 변환 후 내용 대조에 실패했습니다: " + missing[0][:80])
        target.write_bytes(raw)
        print(json.dumps({"pages": int(hwp.PageCount), "engine": "Hancom Hangul",
                          "version": str(hwp.Version), "native_open_verified": True, "native_render_verified": False,
                          "readback_valid": True}, ensure_ascii=False))
    finally:
        if hwp is not None:
            try:
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    main()
