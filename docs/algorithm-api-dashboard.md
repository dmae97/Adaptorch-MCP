# AdaptOrch API ↔ Dashboard 연결 알고리즘

## 1. 아키텍처 개요

```text
┌──────────────┐     MCP stdio/HTTP     ┌──────────────────┐
│  AI Agents   │ ◄────────────────────► │  adaptorch_mcp   │
│ (Claude etc) │     tools/resources    │  (public repo)   │
└──────┬───────┘                        └────────┬─────────┘
       │                                        │ delegates
       │  ADAPTORCH_CONTROL_PLANE_TOKEN          │
       ▼                                        ▼
┌──────────────────────────────────────────────────────────┐
│             adaptorch.com hosted control plane              │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Auth     │  │ Runs API │  │Dashboard │  │ Billing │ │
│  │ JWT+API  │  │ CRUD     │  │ KPI/Chart│  │ Paddle  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │             │             │             │       │
└───────┼─────────────┼─────────────┼─────────────┼───────┘
        │             │             │             │
        ▼             ▼             ▼             ▼
┌──────────────────────────────────────────────────────────┐
│                    Supabase + Redis                       │
│  runs │ cloud_api_keys │ ensemble_snapshots │ telemetry  │
└──────────────────────────────────────────────────────────┘
```

## 2. Skills 할당

아래 표는 실제 라이브 OMK 허브 스킬 이름을 사용하는 예시 매핑이다.

| Phase | Skill | 담당 컴포넌트 | 역할 |
|-------|-------|--------------|------|
| **Plan** | `omk-plan` | 전체 아키텍처 | API↔Dashboard 연결 설계, DAG 분석 |
| **API** | `omk-backend-data` | `/v1/*` 엔드포인트 | REST contract 검증, error handling, pagination |
| **Auth** | `omk-security` | `authMiddleware`, `authenticateApiKey` | JWT/API Key 이중인증, 토큰 탈취 방어 |
| **Secret** | `omk-security` | `.env`, token 전달 | 키 노출 방지, 로그 sanitization |
| **Code** | `omk-engineering` | hosted API, MCP wrapper 구현 | 코드 품질, 타입 안전성 |
| **Test** | `omk-research-docs` | 통합 테스트 | API → Dashboard end-to-end 증거 |
| **QA** | `omk-engineering` | CI/CD | lint, typecheck, test, build 게이트 |
| **Debug** | `omk-engineering` | 장애 대응 | 실패한 테스트/배포 디버깅 |

## 3. MCP Tools 할당

| Tool | 용도 | 적용 지점 |
|------|------|----------|
| `context7` | Supabase/Express/Redis 문서 조회 | API 구현 시 라이브러리 usage 확인 |
| `filesystem` | repo docs/config/frontend 코드 읽기/쓰기 | 파일 수정 |
| `github` | PR, CI 상태 확인 | 배포 전 검증 |
| `memory` | 세션 간 컨텍스트 유지 | 장기 작업 시 checkpoint |

## 4. Hooks 구성

| Hook | 적용 시점 | 목적 |
|------|----------|------|
| `pre-shell-guard.sh` | 모든 `bash` 실행 전 | `rm -rf`, `sudo`, `curl` 차단 |
| `protect-secrets.sh` | `bash`/`read`/`edit`/`write` 입력 전 | `.env`, token, key 문자열 필터링 |
| `stop-verify.sh` | 작업 완료 선언 전 | test/lint/build 통과 확인 강제 |

## 5. 핵심 알고리즘: Run 제출 → Dashboard 반영

### Algorithm 1: POST /v1/runs (hosted backend contract)

```python
def submit_run(request: RunRequest, auth: AuthContext) -> RunResponse:
    """
    Skills: omk-backend-data (contract), omk-security (auth)
    MCP: context7 (Supabase insert patterns)
    Hooks: protect-secrets.sh (token never logged)
    """
    # ── Phase 0: Validate (omk-backend-data) ──
    if not request.subtasks or len(request.subtasks) == 0:
        raise APIError(400, "SUBTASKS_REQUIRED")
    if len(request.subtasks) > 50:
        raise APIError(400, "TOO_MANY_SUBTASKS")
    
    # ── Phase 1: DAG Analysis (Algorithm 1 from router.py) ──
    node_count = len(request.subtasks)
    edge_count = len(request.dependencies or [])
    max_possible = node_count * (node_count - 1) / 2
    coupling_density = edge_count / max_possible if max_possible > 0 else 0
    
    # Topology routing (AdaptOrch TopologyRouter mirror)
    topology = route_topology(node_count, edge_count, coupling_density)
    
    # ── Phase 2: Auth resolution (omk-security) ──
    # Priority: x-api-key header → Bearer ado_/ak_ token → JWT
    tenant_id = auth.tenant_id  # server-authoritative, never from body
    
    # ── Phase 3: Supabase insert (context7 docs) ──
    run = insert_run_row({
        "run_id": generate_run_id(),
        "tenant_id": tenant_id,
        "status": "QUEUED",
        "topology": topology,
        "origin": resolve_origin(auth),  # api|mcp|ui|n8n
        "diagnostics": collect_diagnostics(request, node_count, edge_count)
    })
    
    # ── Phase 4: Telemetry (fire-and-forget) ──
    async_write_ensemble_snapshot(run, request.model)
    async_write_telemetry_event(run, "run_submitted")
    async_increment_redis_counters(tenant_id, request.model, auth.origin)
    
    # ── Phase 5: Control-plane dispatch (opt-in, 5s timeout) ──
    if ADAPTORCH_CONTROL_PLANE_BASE_URL:
        cp_result = dispatch_to_control_plane(run, request, timeout=5.0)
        if cp_result.is_error:
            raise APIError(502, "CONTROL_PLANE_DISPATCH_FAILED")
    
    return RunResponse(run_id=run.run_id, status="QUEUED", topology=topology)
```

### Algorithm 2: Dashboard KPI 집계 (GET /v1/dashboard/kpi)

```python
def get_dashboard_kpi(tenant_id: str, window: str = "7d") -> KPIResponse:
    """
    Skills: omk-backend-data (response contract)
    MCP: context7 (Supabase aggregate queries)
    """
    since = now() - parse_window(window)
    
    # ── Parallel Supabase queries ──
    total_runs = supabase.from_("runs") \
        .select("count", count="exact") \
        .eq("tenant_id", tenant_id) \
        .gte("created_at", since.isoformat())
    
    by_status = supabase.from_("runs") \
        .select("status", "count") \
        .eq("tenant_id", tenant_id) \
        .gte("created_at", since.isoformat())
    
    # Redis fallback for real-time counters
    model_usage = redis.hgetall(f"model_usage:{tenant_id}") or {}
    
    return KPIResponse(
        total_runs=total_runs.count,
        completed=count_by_status(by_status, "COMPLETED"),
        failed=count_by_status(by_status, "FAILED"),
        queued=count_by_status(by_status, "QUEUED"),
        model_distribution=normalize_model_usage(model_usage),
        window=window
    )
```

### Algorithm 3: API Key 발급 → 인증 흐름

```python
def issue_api_key(user_id: str, tenant_id: str) -> APIKeyResponse:
    """
    Skills: omk-security (key management)
    Hooks: protect-secrets.sh (key never in logs/response after creation)
    """
    # ── Generate cryptographically random key ──
    raw_key = f"ado_{secrets.token_urlsafe(32)}"  # ado_ prefix = canonical
    
    # ── Store only sha256 hash (zero-knowledge) ──
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    
    supabase.from_("cloud_api_keys").insert({
        "key_hash": key_hash,
        "tenant_id": tenant_id,
        "owner_user_id": user_id,
        "key_hint": f"ado_...{raw_key[-4:]}",  # last 4 chars only
        "revoked": False
    })
    
    # ⚠️ Return raw key ONCE only — never stored, never logged
    return APIKeyResponse(api_key=raw_key, key_hint=f"ado_...{raw_key[-4:]}")
```

### Algorithm 4: MCP Tool → API Gateway

```python
# adaptorch_mcp/server.py delegates to adaptorch.mcp_server
# adaptorch.mcp_server → adaptorch.com/v1/runs

def mcp_tool_adaptorch_run(payload: dict) -> dict:
    """
    Skills: omk-security (token in env, never in args)
    MCP: context7 (httpx patterns)
    """
    # ── Token from env only, never from MCP tool params ──
    token = os.environ["ADAPTORCH_CONTROL_PLANE_TOKEN"]
    base_url = os.environ.get("ADAPTORCH_CONTROL_PLANE_BASE_URL", 
                               "https://adaptorch.com")
    
    # ── Call upstream API with timeout ──
    response = httpx.post(
        f"{base_url}/v1/runs",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=30.0
    )
    
    if response.status_code == 401:
        raise MCPToolError("INVALID_TOKEN — regenerate at adaptorch.com/app/signup")
    
    return response.json()
```

## 6. Dashboard 연결 파이프라인

```text
User Action              Frontend                    Backend                   Database
─────────────────────────────────────────────────────────────────────────────────────
Sign Up          →  /app/signup (React)    →  Supabase Auth          →  auth.users
Create API Key   →  Dashboard > Settings   →  POST /v1/settings      →  cloud_api_keys
                                                        │
                                              sha256(key) only, raw key shown once
                                                        │
Submit Run       →  (AI Agent via MCP)      →  POST /v1/runs          →  runs
                                │                           │              │
                    ADAPTORCH_CONTROL       requireSupabase()    ensemble_snapshots
                    _PLANE_TOKEN            topology route       run_telemetry_events
                                │                           │              │
Dashboard View   →  React KPI cards         →  GET /v1/dashboard/kpi  →  runs (agg)
                   React charts             →  GET /v1/dashboard/run-series
                   React model-usage        →  GET /v1/dashboard/model-usage
                                                                      →  Redis counters
```

## 7. 품질 게이트 (omk-engineering)

```bash
# 각 변경 후 필수 검증 파이프라인
uv run ruff check .                    # lint
uv run mypy src/adaptorch/             # typecheck
uv run pytest tests/ -q                # unit tests
curl -s https://adaptorch.com/health # smoke test
node -e "require('./adaptor-page/server.test.js')"  # API integration
```

## 8. 보안 경계 (omk-security)

| 경계 | 규칙 |
|------|------|
| API Key raw 값 | 발급 시 1회만 노출, sha256 해시만 저장 |
| JWT secret | `SUPABASE_JWT_SECRET` env only, never in code |
| 로그 | 키 원문/해시/토큰 미로깅 |
| MCP args | 토큰은 env에서만 주입, CLI args 금지 |
| HTTP auth | `hmac.compare_digest()` 상수시간 비교 |
| Control plane | 5s timeout + abort, 실패 시 502 반환 |
