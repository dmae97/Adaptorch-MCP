# MCP·Python SDK 알고리즘 연동 계약 고도화

기준: wrapper `6376130`의 기존 변경을 보존한 작업 트리와 core `6955c1564770fd2694c5fc5fb87023d0f48809de`. 이 문서는 소스 구현 기록이며 패키지 게시·실서비스 배포·실제 모델 성능 개선을 뜻하지 않는다.

## 2026-09-13 통합 보정

아래 검사 수치는 당시 checkout 기록이다. 최신 통합은 core `f30189c22`와
공개 wrapper `1a9cfa3`의 0.5.1 계약을 보존하며 별도 검증했다. reference map의
이름은 하위 호환 `items`에도 남기고 raw reference를 `artifact_urls`로 함께 제공한다.
기존 0.5.1을 막는 제안 wheel 정책은 이번 통합에서 보류하여 현행 gate를 유지한다.
이 문서의 과거 MCP wheel 차단 결과를 현행 릴리즈 상태로 해석하지 않는다.

## 범위

커널 알고리즘을 다시 구현하지 않고, 알고리즘을 요청하고 그 결과를 읽는 경계를 고쳤다. `adaptorch-client`는 계속 표준 라이브러리만 사용한다. MCP는 기존 엔진의 task/poll/collect를 사용하고 HTTP 입출력과 공개 응답을 검증한다.

| 계층 | 변경 | 유지한 경계 |
| --- | --- | --- |
| MCP 모드 | serving `auto`를 포함한 실제 엔진 요청 타입에 parity 시험 결합 | `auto`는 실행 알고리즘이 아니며 지원 전략 목록은 그대로 엔진 소유 |
| MCP 관측 | 요청/선택 모드와 auto 이유를 run/get/cancel/list의 공통 projection에서 보존 | 내부 diagnostics·trace·raw receipt를 remote에 추가 노출하지 않음 |
| MCP HTTP | `SafeControlPlaneConnector`의 단일 시도, redirect/proxy 차단, 크기·JSON·subject 검사 | 원래 task/poll/collect 및 idempotency 생성은 부모 구현 사용 |
| SDK 실행 | `submit_run(..., provider_credential=...)` 요청별 BYOK | POST 자동 재시도, 환경변수 자동 탐색, provider 직접 호출 없음 |
| SDK 조회 | `wait_for_run`, 요청·응답 run ID 결합 | GET 관측만 수행. 보류 시 서버 작업 취소·재제출 없음 |
| SDK 데이터 | 모드/평가 관측, 서버 버전 handshake, artifact reference map | 없는 필드는 추측하지 않으며 임의 artifact ID·해시를 만들지 않음 |

원격 MCP 툴 목록과 접근 권한은 확대하지 않았다. 연구용 `inference-tape/v2`의 코드 결합 재생은 호스팅 실행 경로에 연결돼 있지 않다. SDK나 remote MCP가 해당 tape를 검증한다고 광고하지 않는다.

## 모드와 결과를 읽는 방법

| 필드 | 의미 |
| --- | --- |
| `synthesis_mode_requested` | POST에서 요청한 값. `auto` 가능 |
| `synthesis_mode_used` | 서버의 admission/collection 보고값. 현재 core 수집기는 없으면 저장된 `synthesis_mode`로 대체할 수 있음 |
| `auto_synthesis_reason` | 서버가 보고한 선택 이유 또는 null |
| `synthesis_mode` | GET run의 저장된 구성값 |
| `status` | 실행 생명주기: 완료됐는지 여부 |
| `result_status` | 출력 결과. `SUCCEEDED` 실행도 `DEGRADED`일 수 있음 |
| `evaluation_status`, `score_validity_status` | 독립적인 평가·점수 유효성 관측 |

`used`는 최종 엔진 실행이나 정답성의 증거가 아니다. 최종 엔진의 downshift 정보는 내부 diagnostics에 있을 수 있고 remote projection은 이를 무단 노출하지 않는다. SDK는 GET에 없는 POST 관측을 임의로 채워 넣지 않는다. 누락 값은 `None`, 낯선 상태 문자열은 그대로 보존한다.

숫자 관측의 규약도 고정했다. `consistency`는 null 또는 유한한 0–1 수, `duration_ms`는 null 또는 비음수 정수다. bool을 숫자로 읽지 않는다. 원본 추가 필드를 보존하는 SDK와 공개 allowlist만 남기는 MCP의 역할은 다르다.

## 요청별 BYOK와 대기

[SDK 사용 예제](../packages/adaptorch-client/README.md)에 `ProviderCredential`과 `PollPolicy`를 포함했다.

- SDK는 `X-Provider`, `X-Provider-Model`, `X-Provider-Key`를 그 POST `/v1/runs`에만 넣는다. 요청 body, GET·취소·artifact 조회에는 전달하지 않는다.
- SDK provider key는 repr에서 숨기고, 오류에서는 tenant key와 provider key를 모두 가린다. 입력은 최대 4096바이트의 안전한 printable Latin-1 헤더 값이며 주변 공백을 자동 변경하지 않는다.
- MCP의 안전한 backend도 provider credential을 명시적인 run POST에만 전달한다. MCP 헤더 경계는 ASCII이며, 부모 process-local credential 구성은 유지한다.
- 두 전송 경계 모두 HTTP redirect와 환경 proxy를 사용하지 않는다. TLS 검증을 끄지 않는다.
- 제출 실패가 이미 접수·청구된 요청을 뜻할 수 있으므로 자동 POST 재시도를 하지 않는다. logical run의 idempotency key는 호출자가 보존해야 한다.
- MCP factory는 유효 retry 설정도 1회로 기록한다. 다른 직접 n8n 소비자의 부모 retry 정책까지 바꾼 것은 아니다.

`PollPolicy` 기본값은 대기 120초, 조회 간격 1초, 최대 100회다. `terminal`, `deadline`, `poll_limit`, `unsupported_status` 중 중단 이유와 마지막 관측을 반환한다. 실패한 HTTP 요청은 즉시 예외를 반환하고 조용히 다시 읽지 않는다.

대기 기한은 HTTP 호출 사이와 결과 수신 후 검사하며, 각 요청 timeout을 남은 예산으로 줄인다. 동기식 transport를 강제로 중단하거나 이미 실행 중인 서버 작업을 취소하지 않는다. 시간 제한과 호출 수 제한은 provider 비용 상한이 아니다.

## 대상 결합과 JSON 모호성

SDK의 get-run·cancel·evidence·artifact 결과는 요청한 `run_id`와 같아야 한다. MCP remote projection도 부모가 정규화한 요청 subject에 결합한다. MCP의 기본 HTTP backend는 성공한 생성 응답의 `run_id`가 실제 비어 있지 않은 문자열인지 먼저 검사한다. null·숫자·bool을 문자열로 바꾸어 후속 GET에 사용하지 않는다. GET run·artifact도 수집 전에 검사하므로 다른 subject의 데이터를 합쳐 정상 결과로 내보내지 않는다.

JSON의 중복 키, 비유한수, 잘못된 root 형태와 크기 초과를 거부한다. SDK 및 MCP HTTP의 요청·응답 크기는 8 MiB, 컨테이너 깊이는 root를 포함해 64단계로 제한한다. 문자열 내부의 bracket·escaped quote는 깊이로 세지 않는다. UTF-8 JSON을 사용하며 SDK는 UTF-8 BOM도 허용한다. Python의 버전별 재귀 예외 시점에 의존하지 않는다. MCP text/resource 응답도 별도 8 MiB 경계를 갖는다. `isError`가 존재하면서 bool이 아니면 형식 오류로 처리한다. 누락된 legacy `isError`는 그대로 허용한다.

SDK 검증 오류는 서버가 보낸 임의 link 키를 메시지에 넣지 않는다. 깊은 응답의 복사 및 요청 인코딩 실패도 공개 API 오류로 정규화한다. MCP의 401/403 안내는 두 설정 키를 최장 문자열부터 가리고 제어 문자를 정리한 뒤 최대 512자로 보존한다. 다른 상태는 고정 오류를 유지한다.

이 검사는 대상·형식 일관성이다. 서버가 보고한 내용의 진위나 원래 후보의 semantic verification identity를 증명하지 않는다. 현재 evidence API는 `run_id`와 `checks`를 제공하며 kernel의 전체 identity를 전달하지 않는다.

## 버전·artifact 호환성

REST `capabilities()`의 다음 관측을 SDK 속성으로 노출한다: `server_build`, `receipt_schema_version`, `evidence_schema_version`, `mcp_toolset_version`, `supported_mcp_protocols`. 이는 서버의 보고값이고, 클라이언트가 계산한 코드 지문이 아니다. MCP의 알고리즘 discovery는 별도의 계약이다.

Artifact 조회는 두 형식을 구분한다.

- User API의 `items`: `Artifact`의 ID·이름·제공된 해시 등을 그대로 파싱한다.
- 현재 control-plane의 `artifacts` 문자열 맵: `artifact_urls`로 원문을 보존한다. 하위 호환을 위해 맵의 키는 이름만 있는 `items`로도 제공한다. URL을 자동으로 열거나 다운로드 URL·크기·해시를 추정하지 않는다.
- 두 컨테이너가 함께 오면 모호한 응답으로 거부한다.

## 구현 파일

- SDK: `client.py`, `models.py`, `responses.py`, `config.py`, `provider.py`, `transport.py`, `polling.py`, `json_limits.py`.
- MCP: `control_plane_backend.py`, `backend_config.py`, `hardening.py`, `run_output.py`, `response_json.py`, `response_policy.py`, `output_schema.py`.
- discovery·공통 값 projection은 `discovery_output.py`, `projection_values.py`로 분리했다. 기존 `output_schema.project_catalog/project_server_info`와 hardening의 내부 테스트 seam은 유지한다.
- Pyright 경로는 기존 pytest/mypy의 monorepo src 배치와 인접 private engine 개발 경로를 명시한다. 의존성 설치·전역 도구 설정·인증 설정은 바꾸지 않았다.

## 검증 기록

기준 엔진은 실행마다 `PYTHONPATH`로 지정했다. 가상환경을 재설치하거나 private engine 핀을 변경하지 않았다. SDK 자체 source에는 private engine import가 없다.

| 단계 | 결과 |
| --- | --- |
| 시작 baseline | 427개 중 serving `auto` parity 2건 실패, 1건 skip |
| SDK 관측·subject RED | 15 failed |
| bounded polling RED | 신규 API가 없는 상태에서 14 failed |
| MCP 공개 응답 RED | 48 failed |
| SDK artifact/version RED | 5 failed, 2 passed |
| timeout 입력 RED | 8 failed, 5 passed |
| 1차 전체 통합 GREEN | **827 passed, 1 skipped**, 69.42초 |
| 1차 lint·타입 | 변경 파일 Ruff, monorepo mypy **36개 source** 통과 |
| 리뷰 전 전체 통합 | 852 passed, 1 skipped |
| MCP 생성 ID·BYOK 안내 회귀 | 5 failed, 2 passed → 7 passed |
| SDK link 키·깊은 JSON 회귀 | 4 failed → 4 passed |
| Python 3.12 첫 교차 실행 | 861 passed, 1 skipped, 깊이 관련 2 failed. 예외 시점 차이를 명시적 깊이 제한으로 수정 |
| 최종 Python 3.11.14 | **869 passed, 1 skipped**, 70.09초, 종료 0 |
| 최종 Python 3.12.3 | **869 passed, 1 skipped**, 68.70초, 종료 0 |
| 최종 전체 Ruff | 종료 0 |
| 최종 전체 mypy | **37개 source**, 종료 0 |
| LSP·세션 진단 | 최신 18개 source 중 16개 confirmed clean, 2개 timeout으로 미확인. 별도 mypy는 전 source 통과. `lens_diagnostics(mode=all)`의 검사된 22개 파일에는 blocking error 없음 |
| 최종 wheel 빌드 | SDK·CLI·로컬 MCP 모두 종료 0 |
| 공개 wheel gate | SDK·CLI 통과. 로컬 MCP는 private engine 의존성 때문에 의도대로 차단 |
| 격리 wheel smoke | SDK는 `-I -S`와 private engine import 차단 상태에서 통과. MCP는 SDK import 차단 상태에서 safe backend·기존 remote 툴 목록 확인 |
| 독립 재검증 | 아래 영역별 판정 및 실제 실행 범위 참조 |

BYOK 헤더를 최초 설계의 `X-Provider-Name`에서 실제 엔진 계약인 `X-Provider`로 바로잡은 뒤 회귀 검사를 실행했다. 잘못된 `isError`를 정상으로 간주하던 두 기존 기대값도 형식 오류를 명시적으로 확인하도록 고쳤다. 기존 dirty 파일의 다른 변경은 보존했다.

한 건의 skip은 기준 엔진에 선택적 `adaptorch.hosted_hint`가 없기 때문이다. 알고리즘·credential·대기·subject 검사를 skip한 것이 아니다. Python별 통과 수는 별개 실행이며 합산해 테스트 종류 수로 쓰지 않는다.

### 독립 리뷰와 수정

| 영역 | 결과·근거 |
| --- | --- |
| 정확성 | `f227eb73…`의 생성 subject·401 안내 2건 수정. `ca002aec…` 재검증에서 원본 8 + 신규 7 + 부모 소유 1 = 16개 통과. 생성 오류 후 GET 0회, 401/403 제출 1회 확인 |
| 보안 | `6ec0b9ed…`의 SDK link 키 노출·깊은 복사 오류 2건 수정. 최종 `7bc5f8d8…`가 Python 3.12에서 응답 보안 4개·깊이 6개를 직접 실행하여 10개 통과 및 전후 source 해시 일치 확인 |
| 코드 품질 | `7215cfa1…` 검토 범위 PASS. 이후 수정 부분은 별도 회귀·타입 검사로 확인 |
| 독립 QA | `20e4e3d0…` 최신 변경 6개 파일 확인 후 MCP admission/refusal 7 + SDK response safety 4 + backend 162 = 173개 직접 통과 |
| 문서 | `83f48bb2…`가 기존 6개 항목 모두 PASS. 주장 범위·인증 변수·public wheel 차단·resource 권한·UUID/BYOK/auto 전제를 정정 |

실행 로그·초기 스냅샷·새 wheel은 `/tmp/adaptorch-mcp-sdk-upgrade-o07gws6f/`에 남긴다. 최종 전체 결과는 `verified-checks.json`과 `verified-py311.log`/`verified-py312.log`, 빌드는 `verified-builds.json`, wheel은 `verified-wheels/`다. 이전 실패·중간 통과를 최종 코드 결과로 대체하지 않는다.

테스트는 로컬 HTTP 서버·고정 wire fake·실제 설치 엔진의 순수 payload helper를 사용한다. 실제 모델 실행·유료 호출·실서비스 진단은 하지 않았다. core 알고리즘은 변경하지 않았고, 커밋·푸시·배포·패키지 게시는 이번 범위가 아니다.

**판정: 로컬 구현·검증 완료.** hosted 연구 tape 연동·실제 모델 효능·출시 승인은 미실시이며, engine 의존 MCP의 public wheel 차단은 유지한다.
