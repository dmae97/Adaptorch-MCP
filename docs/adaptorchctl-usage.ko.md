# `adaptorchctl` 한국어 사용 가이드

`adaptorchctl`은 AdaptOrch SaaS의 User API를 호출하는 독립 CLI입니다. 현재 MVP는 실행 제출·조회·취소와 증거·아티팩트 목록 조회를 제공합니다.

## 이름과 역할

| 이름 | 역할 |
| --- | --- |
| `adaptorch` | PyPI에서는 클라이언트·CLI를 설치하는 메타패키지명입니다. 별도로 설치한 참조 엔진의 동명 명령과 구분하세요. |
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

다음 명령은 별도로 게시된 PyPI 버전을 설치합니다. 저장소 푸시만으로 PyPI 버전이 갱신되지는 않으므로, 최신 BYOK 변경은 위 소스 설치로 확인하세요.

```bash
python -m pip install adaptorch-cli
```

`adaptorch-cli` 패키지가 `adaptorchctl` 명령을 설치하며 `adaptorch-client`에 의존합니다.

## 인증과 API 주소

가장 쉬운 방법은 로그인입니다. 키를 한 번 저장하면 이후 명령이 알아서 사용합니다.

```bash
adaptorchctl auth login        # 키를 표준 입력/프롬프트로 입력 (화면에 남지 않음)
adaptorchctl auth status
adaptorchctl whoami            # 저장된 키로 바로 동작
```

로그인은 `whoami`로 키를 검증한 뒤 `~/.config/adaptorch/config.json`(권한 0600)에
저장합니다. 네트워크 없이 저장만 하려면 `auth login --no-verify`를 사용합니다.
제거는 `adaptorchctl auth logout`입니다.

자동화·CI에서는 환경 변수로 전달합니다. **환경 변수가 저장된 키보다 항상 우선**합니다.

```bash
export ADAPTORCH_API_KEY="<secret-store에서-주입할-값>"
export ADAPTORCH_API_URL="https://adaptorch.com"
```

- `ADAPTORCH_API_KEY`: 인증된 명령에 필요합니다.
- `ADAPTORCH_API_URL`: 선택 사항입니다. 기본값은 `https://adaptorch.com`입니다.
- `ADAPTORCH_CONFIG_DIR`: 선택 사항입니다. 설정 디렉터리를 옮길 때만 지정합니다.
- 대시보드에서 발급한 문서화된 `ado_` 접두사 키는 이 CLI에서 **`X-API-Key`로만** 전송합니다. 이 경우 `Authorization` 헤더는 보내지 않습니다. gateway는 이전 호출자 호환성 때문에 Bearer `ado_` 키도 일시적으로 수용할 수 있지만, 새 통합은 그 경로를 사용하면 안 됩니다.
- `ado_` 접두사가 없는 서비스 자격 증명은 기존처럼 `Authorization: Bearer <credential>`로 전송합니다.
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

## OAuth BYOK (현재 소스)

공급자가 지원하는 클라이언트로 로그인한 뒤 access token만 전달합니다. 현재 대상은
`openai_codex`이며, AdaptOrch tenant key를 대체하지 않습니다. 로그인 화면과 refresh는
CLI 외부의 사용자 클라이언트가 담당합니다.

```bash
export ADAPTORCH_PROVIDER=openai_codex
export ADAPTORCH_PROVIDER_MODEL=gpt-5-codex
export ADAPTORCH_PROVIDER_AUTH_TYPE=oauth
export ADAPTORCH_PROVIDER_ACCOUNT_ID=YOUR_CHATGPT_ACCOUNT_ID
# ADAPTORCH_PROVIDER_API_KEY에는 별도로 얻은 최신 access token을 주입합니다.
adaptorchctl run submit --file task.json
```

model ID는 계정에서 실제 제공되는 값을 사용하세요. JSON body에도 명시적 model을
지정하면 shared backend의 Auto 선택 제한과 구별할 수 있습니다. refresh token,
cookie, 전체 인증 파일을 `API_KEY` 값으로 보내지 않습니다.

비밀이 아닌 설정은 `config set provider.auth_type oauth`,
`config set provider.account_id <account-id>`로 저장할 수도 있습니다. 환경 credential을
사용하면 account ID 역시 같은 환경에서 읽고, 저장된 다른 계정 설정과 섞지 않습니다.
OAuth token과 account ID는 요청 body나 이후 조회 요청에 붙지 않습니다.
서버도 해당 source 기능으로 업데이트해야 합니다. RQ로의 요청 자격증명 전달은
여전히 지원하지 않습니다.

## 상태와 서버 정보 확인

다음 두 명령은 로컬 환경만 확인하며 API 요청을 보내지 않습니다. 비밀 값은 마스킹되어
표시되고 원문이 출력되지 않습니다.

```bash
adaptorchctl auth status
# {"authenticated":true,"credential_source":"env","api_url":"https://adaptorch.com"}

adaptorchctl config get
# {"api_key":null,"api_url":"https://adaptorch.com","config_path":"~/.config/adaptorch/config.json",...}
```

`config set`/`config unset`으로 영구 설정을 바꿉니다.

```bash
adaptorchctl config set api_url https://adaptorch.com
adaptorchctl config set provider.name openai
adaptorchctl config set provider.model gpt-4o-mini
printf '%s' "$OPENAI_API_KEY" | adaptorchctl config set provider.api_key --value-stdin
adaptorchctl config unset provider.model
```

저장된 `provider.*` 값은 `run submit`의 BYOK 헤더로 사용됩니다. 환경 변수
`ADAPTORCH_PROVIDER`/`ADAPTORCH_PROVIDER_MODEL`/`ADAPTORCH_PROVIDER_API_KEY`가 있으면
저장값보다 우선합니다. 비밀 키(`api_key`, `provider.api_key`)는 `--value-stdin`으로만
받고 명령행 인자로는 거부합니다.

서버가 인식한 사용자와 공개 기능은 인증된 API 요청으로 확인합니다.

```bash
adaptorchctl whoami
adaptorchctl capabilities
```

`auth status`는 키의 존재 여부만 보여 줍니다. 키의 유효성은 `whoami` 같은 인증된 요청으로 확인하세요.

## 실행 제출

호스팅 모델 실행에는 본인의 공급자 인증을 별도로 전달합니다. 다음 세 변수를 함께 설정하세요.

```bash
export ADAPTORCH_PROVIDER="openai"
export ADAPTORCH_PROVIDER_MODEL="gpt-4o-mini"
export ADAPTORCH_PROVIDER_API_KEY="$OPENAI_API_KEY"
```

공급자 키는 `run submit`의 헤더에만 실립니다. JSON 본문·조회·취소 요청에는 넣지 않습니다.
누락 시 서버의 `byok_credentials_required` 안내를 그대로 확인할 수 있습니다.

요청 본문은 JSON 객체여야 합니다. 파일 또는 표준 입력을 사용할 수 있습니다.

```bash
cat > run-request.json <<'JSON'
{
  "subtasks": [
    {
      "id": "summarize-validation",
      "description": "배포 후보의 검증 결과를 요약하고 각 결론에 증거를 연결합니다."
    }
  ],
  "dependencies": []
}
JSON

adaptorchctl run submit \
  --file run-request.json \
  --request-id "11111111-1111-4111-8111-111111111111"
```

표준 입력 예시:

```bash
printf '%s\n' '{"subtasks":[{"id":"summarize","description":"검증 결과를 요약합니다."}],"dependencies":[]}' \
  | adaptorchctl run submit --file - --request-id "22222222-2222-4222-8222-222222222222"
```

### 멱등성

`run submit`은 모든 요청에 `Idempotency-Key`를 보냅니다.

- `--request-id`를 지정하면 하이픈이 포함된 UUID를 사용해야 합니다.
- 생략하면 실행할 때마다 새 UUID를 생성합니다.
- 같은 논리적 제출을 재시도할 때는 같은 JSON과 같은 `--request-id`를 다시 사용하세요.
- 같은 키를 다른 요청에 재사용하면 서버가 충돌로 거절할 수 있습니다.
- 클라이언트는 POST 제출을 자동 재시도하지 않습니다.

CI에서는 비밀 저장소가 `ADAPTORCH_API_KEY`를 환경 변수로 주입하게 하고, 논리적 작업마다 안정적인 요청 ID를 만드세요.

```bash
# 같은 논리 작업의 재시도에는 보관한 동일 UUID를 다시 사용합니다.
adaptorchctl run submit \
  --file run-request.json \
  --request-id "11111111-1111-4111-8111-111111111111" \
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

### 응답을 잃은 뒤 이어서 확인하기

`run submit`의 응답을 받지 못했다면 **작업을 다시 제출하지 마세요.** 응답 실패만으로
작업이 생성되지 않았다고 단정할 수 없습니다. `run_id`를 이미 알고 있다면 `run wait`로
종료 상태까지 조회만 합니다. 새 실행을 만들지 않으며, MCP `resume_run_id`와 같은 계약입니다.

```bash
adaptorchctl run wait "$RUN_ID"
adaptorchctl run wait "$RUN_ID" --timeout 300 --interval 2
```

응답은 `reason`(`terminal`/`deadline`/`poll_limit`/`unsupported_status`), `polls`,
`elapsed_seconds`, 그리고 마지막으로 관측한 `run`을 담습니다. `terminal`이 아닌 종료는
실패가 아니라 **조회를 멈춘 것**이므로 같은 명령을 다시 실행하면 됩니다.
`run_id`를 모른다면 `run list`로 먼저 기존 실행을 확인하세요.

제출 자체를 다시 보내야 한다면 보관해 둔 **동일한 `--request-id`와 동일한 JSON**을 그대로
사용합니다(위 “멱등성” 참고).

## 증거와 아티팩트 목록

```bash
RUN_ID="<submit-응답의-run-id>"
adaptorchctl evidence show "$RUN_ID"
adaptorchctl artifact list "$RUN_ID"
```

현재 CLI는 아티팩트 메타데이터 목록만 조회합니다. 파일 다운로드 명령은 아직 없습니다.

## 호스팅 API 호환성의 현재 한계

이 클라이언트의 인증 헤더 선택은 Spec 007과 일치하지만, 실제 호스팅 서버의 모든 엔드포인트·상태·페이지네이션 호환성을 이미 검증했다는 뜻은 아닙니다.

- `run submit`은 gateway의 `subtasks` 배열과 선택 `dependencies`를 전송하며, `201`과 대문자 `QUEUED` 상태를 수용합니다. `run cancel`은 `PUT`을 사용하며 전파 대기 시 `202 CANCELLING`, 확정 취소 시 `200 FAILED`와 `error_class=CANCELLED`를 받을 수 있습니다.
- `run list`는 `status`와 `project_id`만 전송합니다. 응답의 `next_cursor`는 보존하지만 OpenAPI에 있는 `cursor`와 `limit` 입력은 아직 CLI/클라이언트에서 지원하지 않습니다.
- `Run` DTO는 `run_id`와 `status`를 필수로 처리하고, `kind`·`phase`·`created_at`·`policy_version`·`links`는 선택적으로 보존합니다. 서버별 추가 필드와 상태 의미의 호환성은 별도 통합 검증이 필요합니다.
- 오류 DTO는 안전한 코드·메시지만 진단에 사용하며 `request_id`와 세부 오류 구조를 자동화 계약으로 노출하지 않습니다.

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
