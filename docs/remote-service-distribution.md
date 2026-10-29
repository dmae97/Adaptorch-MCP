# 비공개 엔진과 공개 원격 클라이언트 배포 경계

- 기준: 현재 작업 트리 `d1f6020181514337b0c42314297d247964a537c3`와 그 이후 변경
- 상태: 원격 MCP 클라이언트 구현. 로컬 bearer 인증과 원격 서비스 자격증명 전달은 구현됨. hosted 사용자 인증 및 플랫폼별 OAuth/OIDC 연동은 미구현 또는 실제 서비스 미검증
- 목표: 비공개 AdaptOrch 엔진은 서버에만 두고, GitHub Action, ChatGPT, Grok에는 호출 인터페이스만 제공

## 현재 구현된 구조

```text
MCP 호스트
  → 공개 adaptorch-mcp (thin_remote / thin_stdio / thin_http)
  → HTTPS POST /v1/mcp, 서비스 인증
  → 비공개 AdaptOrch 엔진과 실행 환경
```

- `adaptorch-mcp`의 런타임 의존성은 `adaptorch-client`뿐이다. 비공개 `adaptorch`는 maintainer 전용 `engine-dev` extra로 분리했다.
- 공개 CLI와 HTTP factory는 `thin_runtime`을 사용한다. 기존 `hardening.py`와 `runtime.py`의 코어 상속 경로를 공개 진입점에서 import하지 않는다.
- `thin_remote`는 원격 tool 목록을 최소 공개 프로필로 투영하고, 낯선 도구, verification command, 잘못된 wait 인자를 로컬에서 거부한다. 응답 ID가 요청과 다르면 실패한다.
- `thin_stdio`는 newline과 Content-Length framing을 지원하고 종료 시 transport를 닫는다.
- `thin_http`는 loopback 전용으로 구성하고, 별도의 client-facing bearer token, protocol version 확인, 스트리밍 요청 크기 제한과 요청 시간 제한을 적용한다. `fastapi`와 `uvicorn`은 `http` extra다.
- BYOK는 `adaptorch_run` 요청에만 헤더로 전달한다. 서비스 API 키와 모델 자격증명은 별개이며, 모델 키를 MCP 인자나 로그에 넣지 않는다. 이것이 현재 대화 모델의 묵시적 사용권을 뜻하지는 않는다.

## 서버 강제와 로컬 브리지의 구분

| 경계 | 확인 범위 |
| --- | --- |
| `thin_remote` 도구/인자 제한 | 클라이언트 방어. 서버 권한의 증거가 아님 |
| `thin_http` bearer 인증/요청 제한 | loopback HTTP 브리지. 공개 HTTPS 서비스가 아님 |
| 서비스 API 키 전달 | 구현됨. 사용자 OAuth/OIDC 연동과 별개 |
| 서버 공개 프로필 | 엔진 작업 트리에서 `/mcp`와 `/v1/mcp`에 동일한 9개 도구 프로필 적용. 호출마다 인자와 tenant scope 검사, quota/모델 처리 전에 금지 요청 거절 |
| 공개 응답 | 내부 diagnostics, trace, raw artifact 경로/내용 미노출. raw artifact는 `not_published`이며 검증 보고서 제공 완료를 뜻하지 않음 |
| 실제 호스트 | OMK 1.5.10 native MCP manager에서 실제 stdio→loopback HTTP→sandbox→보고서 조회 인수 통과. production/다른 플랫폼 미배포 |

서버 변경의 로컬 시험 기록은 비공개 엔진 저장소의
`docs/plans/2026-10-28-mcp-server-boundary-acceptance.md`에 둔다.
클라이언트를 수정하거나 생략한 직접 JSON-RPC 요청을 시험 대상으로 삼는다.
HTTP 요청 간 protocol 상태는 공유하지 않으며 metrics는 요청 범위다.
이 변경은 기존 hosted full catalog를 축소하므로 배포 전 호환성 검토가 필요하다.

## 채널별 배포 계획

| 채널 | 공개 산출물 | 서버에 남길 것 | 현재 상태 |
| --- | --- | --- | --- |
| GitHub Action | `adaptorch-client`를 사용하는 작업 제출, 상태 조회, Job Summary/Check 표시 | 엔진, 검증, 저장소/커밋 권한 매핑, OIDC 토큰 교환 | Action 미구현 |
| ChatGPT Plugin | 플러그인 메타데이터와 원격 MCP 연결 설정 | 동일한 원격 MCP, 사용자 인증, 공개 도구 프로필 | 등록/실제 호스트 검증 안 함 |
| Grok Custom Connector | 원격 MCP URL과 사용자별 인증 설정 | 동일한 원격 MCP와 최소 도구 목록 | 연결 검증 안 함 |
| Grok Build Plugin | MCP 설정과 사용 지침 | 동일한 원격 MCP와 정책 | 패키지 미구현 |

공식 플랫폼 문서, 클라이언트별 지원 버전과 등록 절차는 제출 전에 다시 확인해야 한다. Custom Connector 설정과 공개 카탈로그 입점을 같은 의미로 간주하지 않는다.

## GitHub Action 구현 순서

1. 공개 Action은 저장소와 정확한 커밋을 입력으로 받아 서버에 작업을 제출한다. 엔진을 Action 이미지에 포함하지 않는다.
2. GitHub OIDC 토큰의 서명, issuer, audience, 만료, repository와 workflow 클레임을 서버에서 검증하고 단기 AdaptOrch 토큰으로 교환한다. 이 교환 경로는 아직 구현하지 않았다.
3. 외부 fork 코드에 서비스나 모델 자격증명을 제공하지 않는다. 사용자가 고정한 Action 전체 커밋 SHA와 서버의 저장소 권한을 분리해 검증한다.
4. 실행은 비공개 엔진 및 운영 키가 없는 제한된 worker에서 수행하고, 검증된 최소 결과만 Job Summary나 Check로 복귀한다.
5. GitHub App의 설치 기반 PR 이벤트 경로는 Action 이후 별도 결정이다. 첫 구현에서 두 진입점을 동시에 만들지 않는다.

## 현재 모델과 BYOK의 경계

기본 경로는 **현재 에이전트가 생성하고 AdaptOrch가 검증하는 방식**이다. 원격 MCP 연결 자체가 현재 모델의 호출 권한, 같은 모델 고정, 병렬 호출 또는 무과금 실행을 의미하지 않는다. 클라이언트가 공식적인 model callback을 선언하고 승인한 경우에만 그 능력을 사용한다. 명시적 BYOK와 플랫폼 제공 모델은 각각 별도 선택과 비용 정책이 필요하며 자동 전환하지 않는다.

독립 GitHub Action에는 대화 중인 현재 모델이 없다. 이미 생성된 패치를 검증하거나 사용자가 명시적으로 구성한 생성 경로만 사용한다.

첫 인수 경로는 서비스에 승인 저장소가 등록된 tenant에게만 추가되는 `adaptorch_verify_candidate`와 `adaptorch_get_verification_report`다. 기존 후보 commit을 서비스 인증만으로 제출하고 승인 비모델 검사를 실행하여 revision, 후보 해시, verifier version/bundle과 측정 환경 digest에 묶인 tenant별 보고서를 조회한다. thin client는 선택적 도구를 전달하고 closed report만 투영하며 BYOK를 보내지 않는다. `adaptorch_run`은 생성 경로로 유지한다. model callback과 플랫폼 모델 fallback은 사용하지 않는다.

OMK native MCP manager의 실제 초기화/발견→제출→sandbox PASS→저장 보고서 조회→동일 키 replay가 통과했고 실행 attempt는 1개, generation 진입은 0개였다. 실패, 환경 오류, timeout, 저장 실패와 tenant 거절은 별도 회귀 테스트로 확인했다. harness는 후보와 같은 pytest 프로세스이므로 독립 correctness oracle이 아니며 production의 엔진 비밀성/최소 worker image 인수도 아니다. 운영자는 private engine과 운영 자격증명이 없는 별도 verifier runtime을 구성해야 한다. 단일 프로세스 운영만 지원하며 HTTPS 배포, OAuth와 다른 플랫폼 인수는 남아 있다.

## 공개 및 운영 보안 조건

- 엔진, CSE/NCMH 계산, 선택 정책, 임계값, 전체 프롬프트와 남은 작업 상태는 비공개 서버에 둔다.
- 고객 저장소 코드를 엔진 소스나 운영 자격증명이 있는 동일한 실행 환경에서 실행하지 않는다. worker에는 필요한 입력과 제한된 결과 전달 경로만 부여한다.
- 호스트 Docker 소켓, 운영 API 키, 엔진 소스와 갱신 토큰을 worker에 제공하지 않는다.
- 도구 설명, 클라이언트 JavaScript, 응답, SKILL과 로그를 비밀 저장소로 사용하지 않는다. 응답에는 실행한 검사와 그 한계를 표시하되 남은 정책 상태나 남은 디버그 정보를 넣지 않는다.
- 검증 PASS는 해당 verifier 범위의 결과이며 정답 증명, 독립 모델 합의, 또는 출시 승인이 아니다.
- 클라이언트 토큰을 다른 서비스의 토큰으로 passthrough하지 않고 audience와 권한을 분리한다. 보존, 삭제, 사용량 및 청구 정책은 hosted 출시 전에 확정한다.

## 검증

아래 875/1, wheel 설치 및 import 차단은 앞서 전달한 실행 기록이며 이번 서버 경계 보완에서 독립 재실행한 결과가 아니다. 커밋, 배포, PyPI 반영의 증거로 사용하지 않는다. 당시 wheel 해시와 정확한 skip 사유는 원본 로그 확인 전 미확인이다.


- 공개 thin-client 테스트: 원격 tool projection, BYOK 범위, 비공개 엔진 import 차단, stdio framing, 인증된 HTTP, CLI 생성 경로
- 공개 패키지 통합 테스트: **875개 통과, 1개 skipped**
- 새 thin 모듈 Ruff와 mypy: 통과
- `uv build`: client와 MCP wheel 성공
- 새 임시 virtualenv에 wheel 두 개만 설치한 후 비공개 `adaptorch` import를 차단한 상태에서 CLI import와 `--help`: 통과

아직 실제 ChatGPT, Grok, GitHub 호스트, 원격 production 서비스, OAuth/OIDC, 유료 모델 호출은 검증하지 않았다. 전체 엔진 `pytest -q`는 22,338개 통과, 13개 실패였다. assurance와 WP03 영역 실패 및 기존 문서 링크를 남은 작업으로 두고, 이를 thin-client 전체 통과나 제품 출시 승인으로 표현하지 않는다.
