# `adaptorchctl` 한국어 사용 가이드

`adaptorchctl`은 AdaptTorch SaaS의 User API를 호출하는 독립 CLI입니다. 현재 MVP는 실행 제출·조회·취소와 증거·아티팩트 목록 조회를 제공합니다.

## 이름과 역할

| 이름 | 역할 |
| --- | --- |
| `adaptorch` | 로컬 참조 엔진과 그 CLI입니다. SaaS User API CLI가 아닙니다. |
| `adaptorch-mcp` | MCP 클라이언트와 AdaptOrch를 연결하는 MCP 서버 진입점입니다. |
| `adaptorchctl` | `adaptorch-client`를 사용해 SaaS User API를 직접 호출하는 사용자·자동화용 CLI입니다. |

세 명령은 서로 대체하지 않습니다. `adaptorchctl`은 로컬 엔진이나 MCP 서버를 경유하지 않습니다.

## 설치

현재 저장소의 두 패키지를 함께 설치합니다. Python 3.11 이상이 필요합니다.

```bash
python -m pip install \
  ./packages/adaptorch-client \
  ./packages/adaptorch-cli

adaptorchctl --help
```

두 패키지가 PyPI에 게시된 뒤에는 다음 설치 방식을 사용할 예정입니다. **현재 PyPI 게시를 전제로 자동화하지 마세요.**

```bash
python -m pip install adaptorch-cli
```

`adaptorch-cli` 패키지가 `adaptorchctl` 명령을 설치하며 `adaptorch-client`에 의존합니다.

## 인증과 API 주소

API 키는 환경 변수로만 전달합니다.

```bash
export ADAPTORCH_API_KEY="<secret-store에서-주입할-값>"
export ADAPTORCH_API_URL="https://adaptorch.com"
```

- `ADAPTORCH_API_KEY`: 인증된 명령에 필요합니다.
- `ADAPTORCH_API_URL`: 선택 사항입니다. 기본값은 `https://adaptorch.com`입니다.
- `--api-url`도 사용할 수 있지만 전역 옵션이므로 하위 명령보다 앞에 둡니다.
- `--token`과 `--api-key` 인자는 지원하지 않습니다. 키를 명령행 인자에 넣지 마세요.

```bash
adaptorchctl --api-url https://adaptorch.com whoami
```

API URL은 루트 URL이어야 하며 경로, 쿼리, 프래그먼트, 사용자 정보가 없어야 합니다. 일반 호스트에는 HTTPS만 허용합니다. 평문 HTTP는 정확한 루프백 호스트 `localhost`, `127.0.0.1`, `::1`에만 허용합니다.

```bash
export ADAPTORCH_API_URL="http://127.0.0.1:8000"  # 로컬 개발 전용
```

클라이언트는 리디렉션을 따라가지 않으므로 인증 헤더가 다른 주소로 전달되지 않습니다.

## 상태와 서버 정보 확인

다음 두 명령은 로컬 환경만 확인하며 API 요청을 보내지 않습니다.

```bash
adaptorchctl auth status
# {"authenticated":true}

adaptorchctl config get
# {"api_url":"https://adaptorch.com"}
```

서버가 인식한 사용자와 공개 기능은 인증된 API 요청으로 확인합니다.

```bash
adaptorchctl whoami
adaptorchctl capabilities
```

`auth status`는 키의 존재 여부만 보여 줍니다. 키의 유효성은 `whoami` 같은 인증된 요청으로 확인하세요.

## 실행 제출

요청 본문은 JSON 객체여야 합니다. 파일 또는 표준 입력을 사용할 수 있습니다.

```bash
cat > run-request.json <<'JSON'
{
  "kind": "orchestration",
  "goal": "배포 후보의 검증 결과를 요약합니다.",
  "constraints": [
    "제공된 입력만 사용합니다.",
    "각 결론에 증거를 연결합니다."
  ]
}
JSON

adaptorchctl run submit \
  --file run-request.json \
  --request-id "release-check-example-001"
```

표준 입력 예시:

```bash
printf '%s\n' '{"kind":"orchestration","goal":"검증 결과를 요약합니다."}' \
  | adaptorchctl run submit --file - --request-id "stdin-example-001"
```

### 멱등성

`run submit`은 모든 요청에 `Idempotency-Key`를 보냅니다.

- `--request-id`를 지정하면 그 값을 사용합니다.
- 생략하면 실행할 때마다 새 UUID를 생성합니다.
- 같은 논리적 제출을 재시도할 때는 같은 JSON과 같은 `--request-id`를 다시 사용하세요.
- 같은 키를 다른 요청에 재사용하면 서버가 충돌로 거절할 수 있습니다.
- 클라이언트는 POST 제출을 자동 재시도하지 않습니다.

CI에서는 비밀 저장소가 `ADAPTORCH_API_KEY`를 환경 변수로 주입하게 하고, 논리적 작업마다 안정적인 요청 ID를 만드세요.

```bash
adaptorchctl run submit \
  --file run-request.json \
  --request-id "${CI_PIPELINE_ID:-local}-${CI_JOB_ID:-run-submit}" \
  > run-result.json
```

키를 로그에 출력하거나 셸 추적(`set -x`)이 활성화된 구간에서 직접 조합하지 마세요.

## 실행 조회와 취소

```bash
adaptorchctl run list
adaptorchctl run list --status running
adaptorchctl run list --project-id "project-example"

RUN_ID="<submit-응답의-run-id>"
adaptorchctl run get "$RUN_ID"
adaptorchctl run cancel "$RUN_ID"
adaptorchctl run cancel "$RUN_ID" --reason "중복 제출"
```

`--status`와 `--project-id`는 함께 사용할 수 있습니다. 취소는 요청이며, 서버 응답에서 최종 상태를 확인해야 합니다.

## 증거와 아티팩트 목록

```bash
RUN_ID="<submit-응답의-run-id>"
adaptorchctl evidence show "$RUN_ID"
adaptorchctl artifact list "$RUN_ID"
```

현재 CLI는 아티팩트 메타데이터 목록만 조회합니다. 파일 다운로드 명령은 아직 없습니다.

## 자동화 계약

`--output json`만 지원하며 기본값도 JSON입니다.

```bash
adaptorchctl --output json run get "$RUN_ID" > run.json
```

- 성공 응답은 정렬된 키를 가진 한 줄 JSON 객체와 줄바꿈으로 stdout에 기록합니다.
- 진단과 오류는 stderr에 기록합니다.
- API 오류가 발생하면 stdout은 비어 있습니다.
- `run get`이 실패·취소·불확정 상태를 반환하면 JSON은 stdout에 기록하되 종료 코드는 0이 아닙니다.

| 종료 코드 | 의미 |
| ---: | --- |
| `0` | 명령 성공 |
| `2` | 사용법 오류, 잘못된 제출 JSON, 금지된 자격 증명 인자 |
| `3` | API 키 없음 또는 HTTP 401/403 |
| `4` | HTTP 404 |
| `5` | HTTP 409 충돌 |
| `6` | HTTP 429 제한 초과 |
| `7` | 네트워크·응답 오류 또는 HTTP 5xx |
| `8` | `run get` 결과가 `failed` |
| `9` | `run get` 결과가 `cancelled` |
| `10` | `run get` 결과가 `inconclusive`이거나 별도 매핑이 없는 API 오류 |
| `130` | 사용자 인터럽트 |

종료 코드 `8`~`10`의 실행 상태 판정은 `run get`에만 적용됩니다. 자동화에서는 종료 코드와 stdout JSON을 함께 보관하세요.

## 현재 MVP 경계

현재 구현에는 다음 기능이 없습니다.

- 키 저장소·키링, 토큰 영구 저장, OAuth 디바이스 흐름, 프로필
- 셸 자동 완성, 짧은 별칭 `ado`, 표·리치 텍스트 출력
- SSE watch/reconnect, 아티팩트 다운로드
- 로컬 `adaptorch` 코어 임포트 또는 실행
- `adaptorch-mcp` 백엔드로의 전환

루트 워크스페이스·잠금 파일 통합, 호스팅 API 구현, 패키지 게시도 별도 작업입니다. 이 문서는 현재 저장소의 `adaptorch-client`와 `adaptorch-cli` 동작만 설명합니다.
