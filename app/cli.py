"""Batch export using the same validated engine as the local web app."""
import argparse
import json
from pathlib import Path
from .models import BUILTINS, Profile, Report
from .validation import validate
from .exporter import render_hwpx
from .pdf import convert

def main():
    parser=argparse.ArgumentParser(description="JSON 보고서 → 편집 가능한 HWPX")
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--profile",type=Path,help="선택: Profile JSON 경로")
    parser.add_argument("--strict",action="store_true",help="근거·수치 검증 오류가 있으면 출력하지 않음")
    parser.add_argument("--pdf",type=Path,help="선택: 실제 한글로 PDF도 생성")
    args=parser.parse_args()
    report=Report.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
    profile=Profile.model_validate_json(args.profile.read_text(encoding="utf-8-sig")) if args.profile else BUILTINS.get(report.template_id)
    if profile is None:
        parser.error("사용자 양식에는 --profile JSON이 필요합니다.")
    if args.output.suffix.lower()!=".hwpx":
        parser.error("출력 확장자는 .hwpx여야 합니다.")
    check=validate(report,profile)
    for issue in check["issues"]:
        print(f"[{issue['level']}] {issue['message']}")
    if args.strict and check["errors"]:
        raise SystemExit(2)
    result=render_hwpx(report,profile,args.output)
    if args.pdf:
        args.pdf.parent.mkdir(parents=True,exist_ok=True)
        result["pdf"]=convert(args.output.resolve(),args.pdf.resolve())
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()

