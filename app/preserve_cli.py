"""python -m app.preserve_cli: inspect or edit an existing HWPX copy."""
import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .preserve import EditRequest, PreserveError, inspect_document, replace_document
from .templates import MAX_UPLOAD


def _create_files(files):
    """Exclusive creation, with rollback on failure; never overwrite any path."""
    created = []
    try:
        for path, content in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                created.append(path)
                stream.write(content)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="기존 HWPX 서식 보존 · 텍스트 치환 · 복사본 출력")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--inspect", action="store_true", help="수정 대상 ID·지원 범위·원본 해시를 JSON으로 출력")
    parser.add_argument("--replacements", type=Path, help="EditRequest JSON")
    parser.add_argument("--output", type=Path, help="새 .hwpx 경로 (덮어쓰기 금지)")
    parser.add_argument("--diff", type=Path, help="치환 전후 비교 JSON (기본: 출력.hwpx.diff.json)")
    parser.add_argument("--dry-run", action="store_true", help="검증·비교만 수행하고 파일을 쓰지 않음")
    args = parser.parse_args(argv)
    if args.input.suffix.lower() != ".hwpx":
        parser.error("입력은 .hwpx 파일이어야 합니다.")
    if args.inspect:
        if any((args.replacements, args.output, args.diff, args.dry_run)):
            parser.error("--inspect는 다른 출력 옵션과 함께 사용할 수 없습니다.")
    elif not args.replacements or (not args.dry_run and not args.output):
        parser.error("--replacements와 --output을 지정하거나 --dry-run을 사용하세요.")
    try:
        with args.input.open("rb") as stream:
            data = stream.read(MAX_UPLOAD + 1)
        if args.inspect:
            result = inspect_document(data)
        else:
            if args.replacements.stat().st_size > 3000000:
                raise ValueError("치환 JSON은 3MB 이하여야 합니다.")
            request = EditRequest.model_validate_json(args.replacements.read_text(encoding="utf-8-sig"))
            output, result = replace_document(data, request)
            if not args.dry_run:
                if args.output.suffix.lower() != ".hwpx":
                    raise ValueError("출력 확장자는 .hwpx여야 합니다.")
                diff = args.diff or Path(str(args.output) + ".diff.json")
                paths = [args.input.resolve(), args.replacements.resolve(), args.output.resolve(), diff.resolve()]
                if len(set(paths)) != len(paths):
                    raise ValueError("원본·요청 JSON·복사본·비교 파일은 서로 다른 경로여야 합니다.")
                if args.output.exists() or diff.exists():
                    raise ValueError("복사본 또는 비교 파일이 이미 있습니다. 새 경로를 지정하세요.")
                _create_files([(diff, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()),
                               (args.output, output)])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (PreserveError, ValidationError, ValueError, OSError) as exc:
        parser.exit(2, f"오류 [{getattr(exc, 'code', 'invalid_request')}]: {exc}\n")


if __name__ == "__main__":
    main()
