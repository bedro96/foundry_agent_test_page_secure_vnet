---
name: three-tier-architecture
description: 'Repository-specific guide for the 3-tier TypeScript/Python architecture. Use when adding pages, APIs, auth, database models, MCP validation, Azure AI Foundry chat, speech transcription, telemetry, deployment, folder-structure decisions, or deciding whether code belongs in frontend/, backend/, utils/, or .github/.'
---

# Three-Tier Architecture

## When to use

이 저장소에서 **frontend/backend 분리**, **Next.js 16 + TypeScript**, **FastAPI + Python**, **API 소유권**, **SQLAlchemy/MySQL**, **MCP**, **Azure AI Foundry**, **Speech**, **Container Apps 배포**와 관련된 변경을 할 때 사용한다.

## Architecture overview

이 프로젝트는 3-tier 구조다.

1. **Presentation tier — `frontend/`**: 사용자 UI, 세션 쿠키, 화면 상태, 브라우저 기능.
2. **Application/API tier — `backend/`**: 비즈니스 API, 인증/인가, AI orchestration, MCP/Speech, DB 접근.
3. **Data/Cloud tier**: MySQL(SQLAlchemy ORM), Azure AI Foundry, Azure Speech, Azure Monitor/OpenTelemetry, Azure Container Apps.

핵심 규칙: **프론트엔드는 새로운 비즈니스 API를 만들지 않는다.** Next.js route handler는 필요한 경우 백엔드 프록시/헬스체크/이미지 전처리 같은 UI 지원 용도로만 둔다. CRUD, 인증 로직, 관리자 기능, 대화 저장, MCP 실행, Speech 변환 등은 `backend/`가 소유한다.

## Folder responsibilities

### `frontend/` — Next.js 16 / TypeScript / React

주요 역할:

- `src/app/`: App Router 페이지와 라우트 단위 UI.
  - `page.tsx`, `login/`, `signup/`, `admin/`, `chat/`, `mcp-test/` 등 화면.
  - `src/app/api/**/route.ts`는 백엔드 프록시 또는 UI 보조 엔드포인트로 제한한다.
- `src/components/`: 재사용 UI 컴포넌트.
  - `components/chat/`: 채팅 입력, 메시지, 패널.
  - `components/ui/`: shadcn/base UI primitives.
- `src/lib/`: 프론트엔드 헬퍼.
  - `backend.ts`: 서버 측 백엔드 fetch/SSE/Speech 클라이언트.
  - `config.ts`: `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_BACKEND_API_KEY`.
  - `useAuthGuard.ts`, `auth.ts`: 클라이언트 인증 가드/세션 UI 헬퍼.
  - `sse-client.ts`, `chat-types.ts`, `chat-helpers.ts`, `images.ts`: UI 데이터 변환.

Frontend concerns:

- 로그인/회원가입/관리자/채팅/MCP 검증 화면 구성.
- JWT 세션 쿠키 존재 여부 및 화면 접근 제어.
- 채팅 스트림 렌더링, 이미지 첨부, 마이크 녹음 UX.
- 백엔드 URL/API key를 환경 변수로 주입하고 백엔드 API를 호출.

Common commands:

```bash
cd frontend
npm run dev
npm run build
npm run lint
```

### `backend/` — FastAPI / Python

주요 역할:

- `app/main.py`: FastAPI 앱, CORS, 미들웨어, HTTP API 라우트.
  - `/api/auth/signup`, `/api/auth/login`
  - `/api/admin/users`
  - `/api/chat/stream`
  - `/api/mcp/connect`, `/api/mcp/execute`
  - `/api/conversations`
  - `/api/speech/transcribe`
  - `/health/live`, `/health/ready`
- `app/models.py`: Pydantic request/response schema.
- `app/db_models.py`: SQLAlchemy ORM tables (`users`, `conversations`, `messages`, `sources`, `audit_logs`).
- `app/database.py`: MySQL SQLAlchemy engine/session, SSL, connection health check.
- `app/setup_db.py`: MySQL table creation/verification script.
- `app/auth.py`, `app/auth_service.py`: API key middleware, JWT, password hashing, user service.
- `app/agent.py`, `app/agent_framework/`: Azure AI Foundry agent orchestration and streaming.
- `app/mcp_service.py`: Streamable HTTP MCP tool listing/execution validation.
- `app/speech.py`: Azure Speech transcription and audio handling.
- `app/logging.py`, `app/telemetry.py`: structured logging, access logs, OpenTelemetry/Azure Monitor.
- `tests/`: ongoing backend quality tests.

Backend concerns:

- 모든 비즈니스 API와 DB 접근을 소유한다.
- MySQL 설정은 `backend/.env`/환경 변수에서 읽되, secrets를 코드에 커밋하지 않는다.
- 콘텐츠 안전 로깅 원칙을 유지한다. 사용자 프롬프트/응답 본문 대신 길이, 카운트, 상태 같은 메타데이터를 로그로 남긴다.

Common commands:

```bash
cd backend
uv run uvicorn app.main:app --reload
uv run python -m app.setup_db --verify
uv run python -m pytest
uv run ruff check .
uv run mypy app tests
```

### `utils/`

공통 운영 스크립트, 실험용 보조 도구, repo-level utility를 둔다. 런타임 비즈니스 로직은 가능한 `backend/app` 또는 `frontend/src`에 둔다.

### `.github/`

- `.github/skills/`: 이 저장소 전용 Agent Skills.
- `.github/workflows/`: frontend/backend Docker build 및 Azure Container Apps 배포.
- `.github/instructions/`: Copilot 작업 지침.

## Deployment split

프론트엔드와 백엔드는 별도 Container App으로 배포된다.

- Frontend image/app: `lgit-chat-frontend`
- Backend image/app: `lgit-chat-backend`
- ACR: `iotacr`
- Resource group: `aks-rg`
- Container Apps environment: `lgitappenv`

`frontend/update.sh`와 `backend/update.sh`는 각각:

1. `vYYYYMMDD-HHMMSS` 태그를 생성해 ACA 이미지 캐시 문제를 피한다.
2. `az acr build --registry iotacr --image <image>:<tag> .`로 현재 폴더를 빌드/푸시한다.
3. `az containerapp update --name <app> --resource-group aks-rg --image iotacr.azurecr.io/<image>:<tag>`로 해당 앱만 업데이트한다.

GitHub Actions도 build/deploy workflow를 frontend/backend로 분리한다.

## Where should new code go?

- 새 화면, 레이아웃, UI 상태, React 컴포넌트 → `frontend/src/app`, `frontend/src/components`, `frontend/src/lib`.
- 백엔드 API 계약 타입만 필요한 프론트 헬퍼 → `frontend/src/lib`, 단 실제 업무 로직은 백엔드.
- 새 CRUD/API/인증/권한/대화 저장/MCP/Speech/AI orchestration → `backend/app`.
- 새 DB table/column → `backend/app/db_models.py`, 관련 service/API/Pydantic schema, `app/setup_db.py` 검증 대상 업데이트.
- 새 테스트 → 백엔드는 `backend/tests`; 프론트는 기존 테스트 체계가 있을 때 해당 위치.
- 배포/CI 변경 → `.github/workflows` 또는 각 tier의 `Dockerfile`/`update.sh`.
- repo-specific agent guidance → `.github/skills/<skill-name>/SKILL.md`.

## Guardrails

- Browser에 secret을 노출하지 않는다. `NEXT_PUBLIC_*`는 공개 가능 값만 사용한다.
- 백엔드 호출 API key는 서버 측 `BACKEND_API_KEY`를 우선 사용한다.
- Next.js route handler를 추가할 때 먼저 “이것이 비즈니스 API인가?”를 묻는다. 그렇다면 FastAPI에 구현하고 프론트에서는 호출만 한다.
- SQLAlchemy 세션은 `SessionLocal()` 범위 내에서 열고 닫는다.
- Azure AI/Speech/MCP 변경 시 timeout, error response, telemetry/logging을 함께 점검한다.
