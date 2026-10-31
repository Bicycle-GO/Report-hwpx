# 기존 HWPX 서식 보존 수정

새 문서 생성(`app.cli`, `exporter.py`) 및 스타일 추출(`templates.py`)과 독립된 경로다. 업로드한 문서를 `HwpxDocument`로 재조립하거나 `finalize_package()`로 정규화하지 않는다. 원본을 열어 지원 가능한 문단을 찾고, 승인된 `hp:t`의 문자 데이터 바이트 구간만 바꾼다.

## 대상 지정과 비교

`inspect_document(bytes)`는 원본 SHA-256과 모든 문단의 `id`, `section`, `location`, `kind`, `text`, `supported`, `reason`, `length_locked`를 돌려준다. ID는 XML 내부의 중복 가능한 `id` 속성 대신 구역과 구조상 위치로 만든다. 원본 해시와 함께만 사용한다.

| 예제 ID | 의미 |
|---|---|
| `section0/p2` | section0의 세 번째 최상위 문단 (0부터 계산) |
| `section0/table0/r1c1/p0` | section0의 첫 번째 표, 두 번째 행·두 번째 열, 첫 번째 셀 문단 |
| `section0/protected1` | 머리말·꼬리말·도형 등 보존 전용 영역의 문단 |

화면의 위치 표시는 1부터 계산한다. 셀이 여러 문단을 가지면 각 문단을 별도로 지정한다. 구조 위치는 해당 원본에서만 유효하므로 원본 파일이 달라지면 다시 검사해야 한다.

요청 형식 (`app.preserve.EditRequest`):

```json
{
  "source_sha256": "검사 응답의 64자리 SHA-256 값을 입력",
  "replacements": [
    {
      "target_id": "section0/table0/r1c1/p0",
      "before": "240",
      "after": "360",
      "expected_count": 1
    }
  ]
}
```

`before`는 공백을 포함한 정확한 원문이다. `after`는 빈 문자열도 허용하며 입력 공백을 자르지 않는다. 해당 문단 안의 일치 횟수가 `expected_count`와 정확히 같아야 한다. 기본값은 1이며 반복 문구를 모두 바꾸려면 실제 횟수를 명시한다. 전역 검색·정규식 치환·자동 대상 추측은 제공하지 않는다.

한 요청에서 같은 대상 문단을 두 번 지정할 수 없다. 모든 요청을 원본 기준으로 검사하며 연쇄 치환을 하지 않는다. 최대 100개 문단, 문단당 최대 12,000자다. 하나라도 실패하면 복사본과 비교 파일을 생성하지 않는다. 전체 치환 후 텍스트를 다시 읽어 대조한다.

비교 JSON에는 원본/출력 SHA-256, 문단별 전체 변경 전·후 텍스트, 치환 횟수, 변경한 ZIP 항목, 검증 결과가 포함된다. 원문을 담으므로 수정본과 같은 보관 기준으로 취급한다.

## 지원 범위와 거부 기준

- 최상위 본문 문단의 직접 `hp:run/hp:t` 텍스트와, 본문에 직접 배치한 병합 없는 표의 셀 문단을 수정한다.
- 다른 글자 서식 run의 텍스트를 각각 수정할 수 있지만 하나의 치환이 서로 다른 run 속성의 경계를 넘으면 거부한다. 같은 run 속성의 경계는 넘어도 되며 기존 run과 서식 참조는 유지한다.
- 표의 어떤 셀이라도 병합되어 있으면 **그 표의 모든 셀**을 제외한다. 중첩표는 바깥 표와 안쪽 표 모두 제외한다. 행·열·문단·셀 추가/삭제와 병합/해제는 제공하지 않는다.
- 머리말·꼬리말·로고·그림·도형 위치와 그 내부 텍스트, 필드·주석·각주·미지의 제어 요소·CDATA가 있는 문단은 보존만 한다. 부분 지원이 확인되지 않은 요소는 건너뛰어 임의로 치환하지 않고 요청을 거부한다.
- `hp:linesegarray`가 있는 문단은 줄 배치 캐시의 위치를 바꾸지 않기 위해 `before`와 `after`의 UTF-16 코드 단위 수가 같아야 한다. 길이가 달라지는 치환은 `layout_cache_length` 오류다. 캐시를 삭제하거나 재계산하지 않는다.
- 줄바꿈·탭·XML 제어문자 삽입/치환은 제공하지 않는다. `<`, `>`, `&`는 문자 데이터로 이스케이프한다.
- 입력은 UTF-8 XML 기반 HWPX만 지원한다. OLE 바이너리 `.hwp`, 전자서명·암호화된 문서는 지원하지 않는다.

## 구조 검사와 보존 보장

입력과 출력 모두 다음을 확인한다.

1. 10MB 업로드·40MB 압축 해제·400개 ZIP 항목 한도. 경로 이동·중복 경로·심볼릭 링크·암호화·지원하지 않는 압축 방식 거부. 파일을 디스크에 압축 해제하지 않고 모든 항목의 CRC 확인.
2. 첫 번째 비압축 `mimetype`, 필수 header/section0/content.hpf/container 구성요소 확인.
3. XML/HPF/RDF 파싱. DTD·외부 엔터티·외부 네트워크 접근 금지.
4. 머리정보·구역·컨테이너·OPF 루트, 컨테이너와 manifest/spine의 참조, 문단/글자 스타일, 머리말/꼬리말 및 이미지 바이너리 참조 확인.
5. 표의 행 수·셀 주소·병합 범위·격자의 누락/중복 검사. 표당 최대 10,000칸.
6. 출력 재개봉·수정 텍스트 및 다른 문단의 텍스트 대조·변경 구역 이외 ZIP 항목의 원본 바이트 대조.

XML을 재직렬화하지 않고 원본의 바이트 위치를 따라 편집하므로 변경 구역의 네임스페이스 접두사·속성·여백·주석과 표·도형 정의도 그대로 남는다. ZIP 항목 순서·압축 방식·타임스탬프·확장 필드·댓글과 아카이브 댓글을 전달한다. 재압축된 ZIP 파일 자체의 바이트가 원본과 같은 것은 아니다.

검사 응답의 `structure_valid`는 위 범위의 구조 검사 결과다. **전체 HWPX XSD 검증 또는 한글 시각 검증을 의미하지 않는다.** `full_schema_checked`와 `native_render_verified`는 `false`다. 예제와 자동 테스트에서는 추가로 python-hwpx의 XSD 검사도 통과하는지 확인한다.

글꼴 설치, 조판, 줄바꿈, 셀 넘침과 쪽수는 실제 한글에서 검토해야 한다. 원본의 `Preview/*`, `settings.xml`, 문서 속성과 제목은 보존하므로 미리보기/속성이 수정 후 본문과 다를 수 있다. 복사본을 실제 한글에서 열어 확인하고 저장하면 된다. 이 모드의 결과를 기존 새 문서의 승인 기능과 연결하거나 승인본이라고 표시하지 않는다.

## API

기존과 동일하게 `X-Report-Client: studio-v1` 헤더와 로컬 경계 정책을 사용한다. 모두 `multipart/form-data`다. 원본·결과·비교는 메모리에서 처리하며 문서나 작업 세션을 DB에 저장하지 않는다.

| 메서드·경로 | 입력 | 출력 |
|---|---|---|
| `POST /api/hwpx/inspect` | `file` | 원본 해시·문단/셀 목록·지원 이유·구조 검사 |
| `POST /api/hwpx/preview` | `file`, `request_json` | 완성된 수정본의 검증 결과·변경 전후·출력 해시 |
| `POST /api/hwpx/replace` | 위 입력 + `reviewed_output_sha256` | preview의 결과와 해시가 동일할 때 HWPX 복사본 다운로드 |

오류는 HTTP 400의 `detail`과 `code`로 돌려준다. 폼 필수 필드 누락은 422다. 주요 코드: `target_not_found`, `text_not_found`, `match_count_mismatch`, `source_changed`, `preview_changed`, `unsupported_target`, `style_boundary`, `layout_cache_length`, `unsupported_text`, `invalid_package`, `invalid_xml`.

## 예제·회귀 검사

```bash
python -m examples.make_preserve_fixture
python -m app.preserve_cli --input examples/preserve-template.hwpx --inspect
python -m app.preserve_cli --input examples/preserve-template.hwpx --replacements examples/preserve-replacements.json --dry-run
python -m app.preserve_cli --input examples/preserve-template.hwpx --replacements examples/preserve-replacements.json --output outputs/preserve-copy.hwpx
python -m pytest -q
node --check app/static/app.js
node --check app/static/preserve.js
```

`--dry-run`은 전체 치환과 재검증을 메모리에서 수행하고 비교 JSON을 표준출력에 표시한다. 일반 출력은 수정본과 비교 파일을 배타적으로 새로 만든다. 원본·요청 JSON·수정본·비교 파일은 서로 다른 경로여야 하며, 기존 파일을 덮어쓰지 않는다. 두 파일 중 하나의 생성이 실패하면 이 작업이 만든 파일을 정리한다.

예제 양식은 생성 스크립트만으로 동일한 바이트를 재생성할 수 있다. 실제 기관명·로고·예산이나 사용자 자료를 포함하지 않는다. 머리말·꼬리말·가상 로고·일반표·병합표·도형 내부 텍스트·서로 다른 글자 서식·두 개 구역을 포함한다. 예제 치환은 연도와 일반 문장, 단순 표의 금액 셀을 바꾸며 병합표/도형/둘째 구역은 그대로 둔다.
