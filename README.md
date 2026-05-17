# AI Chat Portal — Azure AI Foundry × Next.js

공장 이상 감지, 진단 및 조치 권고를 위한 프로덕션 수준의 AI 채팅 포털입니다.
**Azure AI Foundry** 에이전트와 실시간으로 대화하며, Bing 그라운딩, MCP 도구 호출,
음성 입력, 이미지 첨부 등 다양한 기능을 지원합니다.

📎 고객 설명용 PowerPoint 자료: [`AI-Chat-Portal-Architecture-KO.pptx`](./AI-Chat-Portal-Architecture-KO.pptx)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [주요 기능](#3-주요-기능)
4. [네트워크 흐름](#4-네트워크-흐름)
5. [인증 흐름](#5-인증-흐름)
6. [API 엔드포인트](#6-api-엔드포인트)
7. [프로젝트 구조](#7-프로젝트-구조)
8. [배포 방법](#8-배포-방법)
9. [로컬 개발](#9-로컬-개발)
10. [테스트](#10-테스트)
11. [텔레메트리 및 모니터링](#11-텔레메트리-및-모니터링)
12. [알려진 제한 사항](#12-알려진-제한-사항)
13. [라이선스](#13-라이선스)

---

## 1. 프로젝트 개요

AI Chat Portal은 **Azure AI Foundry 에이전트**와 실시간으로 대화할 수 있는 3-tier 웹 포털입니다.
공장 공정의 이상 징후를 감지하고, 진단하며, 조치를 권고하는 산업용 AI 채팅 시스템으로 설계되었습니다.

| 계층 | 기술 스택 | 역할 |
|------|-----------|------|
| **프론트엔드** | Next.js 16, React 19, shadcn/ui, Tailwind CSS v4 | 사용자 인터페이스 — 채팅, 관리자, MCP 테스트, 로그인/회원가입 |
| **백엔드** | FastAPI (Python 3.12), SQLAlchemy, Pydantic v2 | REST API, SSE 스트리밍, JWT 인증/인가, 에이전트 오케스트레이션 |
| **데이터/AI** | Azure MySQL Flexible Server, Azure AI Foundry, Azure Speech, Application Insights | 사용자/대화 데이터 저장, AI 에이전트 실행, 음성 전사, 텔레메트리 수집 |

**배포 환경**: Azure Container Apps (ACA) 위에 프론트엔드와 백엔드를 각각 독립 컨테이너로 운영합니다.

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              사용자 (브라우저)                                    │
│                                    │                                            │
│                           HTTPS (포트 443)                                       │
│                                    ▼                                            │
│  ┌─────────────────────────────────────────────────────────┐                    │
│  │            프론트엔드 — Next.js 16 (ACA)                  │                    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │                    │
│  │  │ 채팅     │ │ 관리자   │ │ MCP 테스트│ │ 로그인     │ │                    │
│  │  │ 페이지   │ │ 페이지   │ │ 페이지   │ │ /회원가입  │ │                    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │                    │
│  └──────────────────────────┬──────────────────────────────┘                    │
│                             │ REST API + SSE (x-api-key 인증)                   │
│                             ▼                                                   │
│  ┌─────────────────────────────────────────────────────────┐                    │
│  │            백엔드 — FastAPI (ACA, 포트 8000)              │                    │
│  │  ┌──────────────────┐  ┌────────────────────────────┐  │                    │
│  │  │ 에이전트          │  │  미들웨어                    │  │                    │
│  │  │ 오케스트레이터    │  │  (CORS, API Key, 액세스로그) │  │                    │
│  │  └────────┬─────────┘  └────────────────────────────┘  │                    │
│  │           │                                             │                    │
│  │  ┌────────▼─────────┐  ┌──────────────┐  ┌───────────┐│                    │
│  │  │ Azure AI Foundry │  │ MCP 클라이언트│  │ Speech    ││                    │
│  │  │ Agent (SSE)      │  │ (JSON-RPC)   │  │ 전사기    ││                    │
│  │  └────────┬─────────┘  └──────┬───────┘  └─────┬─────┘│                    │
│  └───────────┼───────────────────┼────────────────┼──────┘                    │
│              │                   │                │                            │
│              ▼                   ▼                ▼                            │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐                     │
│  │ Azure AI Foundry │  │ 외부 MCP     │  │ Azure Speech │                     │
│  │ (GPT 모델,       │  │ 서버         │  │ Services     │                     │
│  │  Bing 그라운딩)   │  │              │  │              │                     │
│  └──────────────────┘  └──────────────┘  └──────────────┘                     │
│                                                                                │
│  ┌──────────────────┐  ┌──────────────────────────┐                           │
│  │ Azure MySQL      │  │ Azure Application        │                           │
│  │ Flexible Server  │  │ Insights (텔레메트리)     │                           │
│  │ (사용자, 대화)    │  │                          │                           │
│  └──────────────────┘  └──────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 컴포넌트 설명

| 컴포넌트 | 기술 | 설명 |
|----------|------|------|
| **프론트엔드** | Next.js 16 + React 19 + shadcn/ui | App Router 기반 SPA. 채팅, 관리자, MCP 테스트, 인증 페이지 제공 |
| **백엔드** | FastAPI + uvicorn | REST API 서버. SSE 스트리밍, JWT 인증, 에이전트 오케스트레이션 |
| **AI 에이전트** | Azure AI Foundry (Prompt Agent) | GPT 모델 + Bing 그라운딩 + 웹 검색 도구를 사용하는 AI 에이전트 |
| **MCP 클라이언트** | httpx (JSON-RPC 2.0) | 외부 MCP 서버 연결, 도구 탐색 및 실행 프록시 |
| **음성 전사** | Azure Speech Services | 오디오 → 텍스트 변환 (배치 전사 API) |
| **데이터베이스** | Azure MySQL Flexible Server + SQLAlchemy | 사용자 계정, 대화 기록, 메시지 저장 |
| **텔레메트리** | OpenTelemetry + Azure Monitor | AI 에이전트 실행 추적, LLM 호출 계측, Application Insights 전송 |

---

## 3. 주요 기능

- 🤖 **실시간 SSE 채팅 스트리밍**: Azure AI Foundry 에이전트 기반의 Server-Sent Events 스트리밍 응답. 대화 컨텍스트를 유지하며 멀티턴 대화 지원
- 🔧 **MCP 도구 테스트 페이지**: Model Context Protocol (Streamable HTTP) 서버에 연결하여 도구 목록 조회 및 실행 검증. 인증 방식 선택 (None / x-api-key) 및 소요 시간 측정 포함
- 🎙️ **음성 입력**: Azure Speech API를 통한 음성→텍스트 변환. 마이크 아이콘으로 녹음 후 자동 전사
- 🖼️ **이미지 첨부**: 멀티모달 입력 지원 — base64 인코딩된 이미지를 LLM에 전달
- 👥 **사용자 관리 (Admin)**: 회원가입, 로그인, JWT 인증. 관리자 페이지에서 사용자 CRUD, 역할 변경, 계정 활성화/비활성화
- 📊 **OpenTelemetry + Azure Monitor 텔레메트리**: GenAI semantic conventions 기반 에이전트 실행 추적. LLM 호출, 도구 사용, 토큰 소비량을 Application Insights에서 분석
- 🔍 **Bing 그라운딩 / 웹 검색**: 실시간 웹 데이터를 기반으로 사실적 응답 생성
- 🌙 **다크 모드 지원**: 시스템 / 라이트 / 다크 테마 전환
- 💾 **대화 기록 관리**: 대화 저장, 조회, 숨기기 (아카이브). 페이지네이션 및 날짜 필터 지원

---

## 4. 네트워크 흐름

### 4.1 프론트엔드 ↔ 백엔드 API 흐름

이 저장소의 프론트엔드-백엔드 통신은 **두 가지 패턴**을 사용합니다.

1. **브라우저가 백엔드에 직접 호출**
   - 사용처: 실시간 채팅 스트리밍, MCP 테스트 페이지
   - 사용 변수: `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_BACKEND_API_KEY`
   - 예: `frontend/src/lib/backend.ts`, `frontend/src/app/mcp-test/page.tsx`

2. **Next.js Route Handler가 백엔드에 서버 사이드 프록시**
   - 사용처: 로그인/회원가입, 관리자 사용자 관리, 대화 기록, 음성 전사
   - 사용 변수: `NEXT_PUBLIC_BACKEND_URL`, `BACKEND_API_KEY`
   - 예: `frontend/src/app/api/auth/*`, `frontend/src/app/api/admin/*`, `frontend/src/app/api/conversations/*`

```
브라우저
  │
  ├──▶ 직접 호출 → FastAPI 백엔드 (/api/chat/stream, /api/mcp/*)
  │
  └──▶ Next.js Route Handlers → FastAPI 백엔드
                              (세션 쿠키/JWT + x-api-key 프록시)
```

- 프로덕션에서 `x-api-key`가 필요한 백엔드 경로는 `/api/auth/*`, `/api/mcp/*`를 제외한 보호된 `/api/**` 엔드포인트입니다.
- 관리자/대화 기록 API는 추가로 JWT Bearer 토큰이 필요합니다.
- `.env` 파일이 Docker 이미지에 번들됨 (ACA에서 별도 환경변수 설정 없음)

### 4.2 SSE 스트리밍 흐름

```
브라우저                               FastAPI 백엔드
  │                                         │
  │  POST {NEXT_PUBLIC_BACKEND_URL}/api/chat/stream
  │ ─────────────────────────────────────▶   │
  │                                         │ → AgentOrchestrator
  │                                         │ → AzureAIFoundryAgent.stream()
  │  event: status                          │ → Azure AI Foundry API
  │ ◀─────────────────────────────────────  │
  │  event: message                         │
  │ ◀─────────────────────────────────────  │
  │  event: done                            │
  │ ◀─────────────────────────────────────  │
```

### 4.3 MCP JSON-RPC 흐름

```
프론트엔드 → POST /api/mcp/connect
  → 백엔드 McpClient
    → JSON-RPC initialize → 외부 MCP 서버
    → JSON-RPC notifications/initialized
    → JSON-RPC tools/list
  ← { tools: [...], timing: { total_ms, initialize_ms, list_tools_ms } }
```

### 4.4 음성 전사 흐름

```
브라우저 (마이크 녹음)
  → base64 인코딩 → POST /api/speech/transcribe
  → 백엔드: 오디오 디코딩 → 인메모리 볼트 저장 → /audio/{token} 노출
  → Azure Speech 배치 전사 API v3.2 호출 → 폴링 → 결과 반환
  ← { text: "인식된 텍스트", language: "ko-KR" }
```

---

## 5. 인증 흐름

```
1. 회원가입 (/signup)
   사용자 → POST /api/auth/signup (username, email, password)
   → bcrypt 해싱 → MySQL users 테이블 저장
   → is_active = 0 (비활성 상태)
   ※ 최초 가입자만 admin 역할 + is_active = 1 자동 부여

2. 관리자 활성화 (/admin)
   관리자 → PUT /api/admin/users/{id} { is_active: 1 }
   → 사용자 계정 활성화

3. 로그인 (/login)
   사용자 → POST /api/auth/login (email, password)
   → bcrypt 검증 → is_active 확인
   → JWT 토큰 발급 (응답 본문)

4. API 호출
   이후 모든 인증 필요 API 요청에 Authorization 헤더 포함
   + x-api-key 헤더 (프로덕션 환경)

5. 로그아웃
   클라이언트에서 JWT 토큰 삭제
```

### 역할 기반 접근 제어

| 역할 | 권한 |
|------|------|
| `user` | 채팅, 대화 기록 조회/저장, 음성 전사 |
| `admin` | 위 모든 권한 + 사용자 CRUD, 계정 활성화/비활성화 |

---

## 6. API 엔드포인트

프로덕션 환경에서는 `/api/auth/*`, `/api/mcp/*`를 제외한 보호된 백엔드 `/api/**` 엔드포인트에 `x-api-key` 헤더가 필요합니다.

### 헬스 체크

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/` | 앱 이름 및 환경 정보 반환 |
| `GET` | `/health/ready` | 준비 상태 프로브 (ACA용) |
| `GET` | `/health/live` | 생존 상태 프로브 (ACA용) |

### 인증 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/auth/signup` | 회원가입 — username, email, password |
| `POST` | `/api/auth/login` | 로그인 → JWT 토큰 발급 |

### 관리자 API (admin 역할 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/admin/users` | 전체 사용자 목록 조회 |
| `PUT` | `/api/admin/users/{user_id}` | 사용자 정보 수정 (email, password, role, is_active) |
| `DELETE` | `/api/admin/users/{user_id}` | 사용자 삭제 (자기 자신 삭제 불가) |

### 채팅 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/chat/stream` | SSE 스트리밍 채팅 응답. `text/event-stream` 반환 |

### MCP API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/mcp/connect` | MCP 서버 연결 + 도구 목록 조회 (타이밍 포함) |
| `POST` | `/api/mcp/execute` | MCP 도구 실행 + 결과 반환 (타이밍 포함) |

### 대화 기록 API (JWT 인증 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/conversations` | 대화 목록 조회 (페이지네이션, 날짜 필터) |
| `GET` | `/api/conversations/{id}/messages` | 대화 메시지 기록 조회 |
| `POST` | `/api/conversations` | 대화 저장 (upsert — azure_conversation_id 기준) |
| `PATCH` | `/api/conversations/{id}/hide` | 대화 아카이브 (숨기기) |

### 음성 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/speech/transcribe` | 음성→텍스트 변환 (Azure Speech 배치 전사) |

---

## 7. 프로젝트 구조

```
foundry_agent_test_page/
├── backend/                          # FastAPI 백엔드
│   ├── app/
│   │   ├── main.py                   # FastAPI 앱 진입점, 전체 라우트 정의
│   │   ├── agent.py                  # AzureAIFoundryAgent — AI 에이전트 SSE 스트리밍
│   │   ├── agent_framework/          # 에이전트 추상화 프레임워크
│   │   │   ├── __init__.py           # AgentOrchestrator
│   │   │   └── base.py              # BaseAgent (추상), AgentEvent
│   │   ├── auth.py                   # APIKeyAuthMiddleware (x-api-key 검증)
│   │   ├── auth_service.py           # JWT 발급/검증, bcrypt 해싱, 사용자 CRUD
│   │   ├── config.py                 # Pydantic Settings (.env → lru_cache)
│   │   ├── database.py               # SQLAlchemy 엔진/세션 팩토리 (MySQL)
│   │   ├── db_models.py              # ORM 모델 (User, Conversation, Message)
│   │   ├── logging.py                # 구조화된 로깅 + AccessLogMiddleware
│   │   ├── mcp_service.py            # MCP 프록시 클라이언트 (JSON-RPC, 타이밍 측정)
│   │   ├── models.py                 # Pydantic 요청/응답 스키마
│   │   ├── setup_db.py               # MySQL 테이블 생성/검증 CLI
│   │   ├── speech.py                 # Azure Speech 배치 전사 v3.2
│   │   └── telemetry.py              # OpenTelemetry + Application Insights 초기화
│   ├── tests/                        # pytest 테스트
│   ├── pyproject.toml                # uv 프로젝트 (Python ≥ 3.12)
│   ├── Dockerfile                    # 멀티스테이지 Docker 빌드
│   ├── update.sh                     # ACA 배포 스크립트
│   ├── TELEMETRY.md                  # 텔레메트리 상세 가이드
│   └── .env.example                  # 환경변수 템플릿
│
├── frontend/                         # Next.js 16 프론트엔드
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx              # 메인 페이지 (공장 배경)
│   │   │   ├── chat/page.tsx         # 채팅 페이지 (SSE 스트리밍)
│   │   │   ├── admin/page.tsx        # 관리자 페이지 (사용자 CRUD)
│   │   │   ├── login/page.tsx        # 로그인 페이지
│   │   │   ├── signup/page.tsx       # 회원가입 페이지
│   │   │   ├── mcp-test/page.tsx     # MCP 도구 테스트 페이지
│   │   │   ├── health/route.ts       # ACA 프런트엔드 헬스 체크 엔드포인트
│   │   │   ├── layout.tsx            # 루트 레이아웃 (AppNavbar)
│   │   │   └── api/                  # Next.js Route Handlers (백엔드 프록시)
│   │   │       ├── auth/*            # login, signup, logout, me
│   │   │       ├── admin/users*      # 관리자 사용자 프록시
│   │   │       ├── conversations*    # 대화 기록 프록시
│   │   │       ├── speech/transcribe # 음성 전사 프록시
│   │   │       └── chat/prepare-image# 이미지 업로드 전처리
│   │   ├── components/               # React 컴포넌트
│   │   │   ├── chat/                 # ChatPanel, ChatMessage, ChatInput
│   │   │   ├── ui/                   # shadcn/ui 컴포넌트
│   │   │   └── app-navbar.tsx        # 네비게이션 바
│   │   └── lib/                      # 유틸리티 모듈
│   │       ├── sse-client.ts         # SSE 프레임 파서
│   │       ├── auth.ts               # 인증 유틸리티
│   │       ├── backend.ts            # 서버/클라이언트용 백엔드 API 헬퍼
│   │       └── config.ts             # 클라이언트 런타임 구성
│   ├── package.json                  # Next.js 16 + React 19
│   ├── Dockerfile                    # 멀티스테이지 Docker 빌드
│   ├── update.sh                     # ACA 배포 스크립트
│   └── .env.example                  # 환경변수 템플릿
│
├── utils/
│   └── base64url_encoded.py          # 보조 유틸리티
│
└── .github/
    ├── workflows/                    # CI/CD GitHub Actions
    │   ├── build-backend.yml         # 백엔드 빌드
    │   ├── build-frontend.yml        # 프론트엔드 빌드
    │   ├── deploy-backend.yml        # 백엔드 배포
    │   └── deploy-frontend.yml       # 프론트엔드 배포
    ├── skills/                       # Copilot 스킬 정의
    └── copilot-instructions.md       # Copilot 코딩 가이드라인
```

---

## 8. 배포 방법

### 사전 준비

| 리소스 | 설명 |
|--------|------|
| Azure CLI | `az login`으로 인증 |
| Azure Container Registry (ACR) | Docker 이미지 저장소 |
| Azure Container Apps (ACA) | 프론트엔드/백엔드 각각 1개 컨테이너 앱 |
| Azure MySQL Flexible Server | 사용자/대화 데이터 저장 |
| Azure AI Foundry 프로젝트 | AI 에이전트 및 모델 배포 |

### 환경변수 설정

```bash
# 백엔드
cd backend
cp .env.example .env
# .env 편집: Azure 자격증명, MySQL 연결 정보, API 키 등 입력

# 프론트엔드
cd frontend
cp .env.example .env
# .env 편집: NEXT_PUBLIC_BACKEND_URL, NEXT_PUBLIC_BACKEND_API_KEY, BACKEND_API_KEY 입력
```

### 배포 실행

```bash
# 백엔드 배포 (ACR 빌드 + ACA 업데이트)
cd backend && bash update.sh

# 프론트엔드 배포 (ACR 빌드 + ACA 업데이트)
cd frontend && bash update.sh
```

현재 저장소의 `update.sh` 스크립트는 다음 고정 명령을 수행합니다:

```bash
# backend/update.sh
az acr build --registry iotacr --image lgit-chat-backend:latest .
az containerapp update --name lgit-chat-backend --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-backend:latest

# frontend/update.sh
az acr build --registry iotacr --image lgit-chat-frontend:latest .
az containerapp update --name lgit-chat-frontend --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-frontend:latest
```

### MySQL 데이터베이스 설정

앱 시작 시 SQLAlchemy `create_all()`로 테이블이 자동 생성됩니다. 수동 설정이 필요하면 저장소에 포함된 CLI를 사용하세요:

```bash
cd backend && uv run python -m app.setup_db
```

> 현재 저장소에는 별도의 `utils/setup_mysql.sql` 파일이 없습니다.

### ⚠️ 이미지 태그 주의사항

`:latest` 태그만 사용할 경우 ACA가 이전 이미지를 캐시하여 재사용할 수 있습니다.
변경이 반영되지 않으면 리비전을 재시작하거나, **고유 태그** (예: git commit hash) 사용을 권장합니다:

```bash
# 고유 태그 사용 예시
TAG=$(git rev-parse --short HEAD)
az acr build --registry iotacr --image lgit-chat-backend:$TAG .
az containerapp update --name lgit-chat-backend --resource-group aks-rg \
  --image iotacr.azurecr.io/lgit-chat-backend:$TAG
```

---

## 9. 로컬 개발

### 백엔드

```bash
cd backend

# uv 설치 (미설치 시)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 의존성 설치
uv sync

# 환경변수 설정
cp .env.example .env
# .env 편집

# 개발 서버 실행 (핫 리로드)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

백엔드가 **http://localhost:8000** 에서 시작됩니다. Swagger 문서: **http://localhost:8000/docs**

### 프론트엔드

```bash
cd frontend

# 의존성 설치
npm ci

# 환경변수 설정
cp .env.example .env
# .env 편집: NEXT_PUBLIC_BACKEND_URL=http://localhost:8000

# 개발 서버 실행 (Turbopack)
npm run dev
```

프론트엔드가 **http://localhost:3000** 에서 시작됩니다.

### 개발 vs 프로덕션 비교

| 항목 | 개발 (Development) | 프로덕션 (Production) |
|------|-------------------|---------------------|
| 백엔드 서버 | `uv run uvicorn ... --reload` | Docker + ACA |
| 프론트엔드 서버 | `npm run dev` (Turbopack) | `npm run build && npm start` (Docker) |
| API 인증 | `APP_ENV=Development` → API 키 검증 비활성 | `APP_ENV=Production` → `x-api-key` 필수 |
| Azure 인증 | `az login` → DefaultAzureCredential | 서비스 주체 (ClientSecretCredential) |
| 로깅 레벨 | DEBUG | INFO |

---

## 10. 테스트

### 백엔드 정적 분석

```bash
cd backend

# 코드 스타일 검사 (ruff)
uv run ruff check .

# 포맷 검사 (ruff format)
uv run ruff format --check .

# 타입 검사 (mypy)
uv run mypy . --ignore-missing-imports

# 보안 검사 (bandit)
uv run bandit -r app/ -c pyproject.toml

# flake8 (설치된 경우)
uv run flake8 app/
```

### 프론트엔드 검증

```bash
cd frontend

# ESLint 검사
npm run lint

# 프로덕션 빌드 검증
npm run build
```

### 프로덕션 스모크 테스트 체크리스트

```bash
BACKEND_URL="https://lgit-chat-backend.mangofield-57a3b9f0.koreacentral.azurecontainerapps.io"
API_KEY="your-api-key"

# 헬스 체크
curl -s "$BACKEND_URL/health/ready" | jq .

# 앱 메타데이터
curl -s "$BACKEND_URL/" | jq .

# 회원가입
curl -s -X POST "$BACKEND_URL/api/auth/signup" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"username":"testuser","email":"test@example.com","password":"Test1234!"}' | jq .

# 로그인
curl -s -X POST "$BACKEND_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"email":"test@example.com","password":"Test1234!"}' | jq .

# MCP 연결 테스트
curl -s -X POST "$BACKEND_URL/api/mcp/connect" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"server_url":"https://your-mcp-server/mcp","auth_type":"none"}' | jq .
```

### 검증 대상

| 검증 항목 | 확인 방법 |
|----------|-----------|
| 백엔드 헬스 체크 | `/health/ready`, `/health/live` 호출 |
| 프론트엔드 접속 | ACA 프론트엔드 URL 200 응답 확인 |
| 회원가입 / 로그인 | `/api/auth/signup`, `/api/auth/login` 호출 |
| 관리자 사용자 관리 | `/api/admin/users` 조회/수정/삭제 |
| AI 채팅 SSE 스트리밍 | `/api/chat/stream` 이벤트 흐름 확인 |
| MCP 도구 연결/실행 | `/api/mcp/connect`, `/api/mcp/execute` 호출 |
| 텔레메트리 전송 | Application Insights / Foundry Tracing 화면 확인 |

---

## 11. 텔레메트리 및 모니터링

### 개요

이 프로젝트는 **OpenTelemetry** 표준 기반의 GenAI 텔레메트리 트레이싱을 구현하여,
Azure AI Foundry 에이전트의 실행 경로를 **Azure Application Insights**로 자동 전송합니다.

### 주요 기능

- **LLM 호출 자동 계측**: `AIProjectInstrumentor`가 에이전트의 모든 SDK 호출에 span을 자동 삽입
- **GenAI Semantic Conventions**: `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.total_tokens` 등 표준 속성 사용
- **커스텀 스팬 계층**: `invoke_agent {agent_name}` → `resolve-agent` → `ensure-conversation` → `tool-call:*`
- **도구 호출 추적**: Bing 검색, 웹 브라우징, MCP 도구별 지연 시간 및 성공/실패 추적

### 초기화 흐름

```
앱 시작 → telemetry.py::configure_telemetry(settings)
  ├── 1. os.environ에 트레이싱 환경변수 설정
  ├── 2. azure.core.settings.tracing_implementation = "opentelemetry"
  ├── 3. Foundry 프로젝트에서 Application Insights 연결 문자열 동적 조회
  ├── 4. configure_azure_monitor(connection_string=...)
  ├── 5. AIProjectInstrumentor().instrument()
  └── 6. NonRecordingSpan.attributes 패치 (SDK 버그 우회)
```

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING` | `true` | GenAI 트레이싱 활성화/비활성화 |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `true` | 메시지 내용 캡처 여부. **프로덕션에서는 `false` 권장** |

> 📚 상세 가이드: [`backend/TELEMETRY.md`](backend/TELEMETRY.md) — 환경변수 설명, KQL 쿼리 예시, 문제 해결, 보안 고려사항 포함

---

## 12. 알려진 제한 사항

### 1. NonRecordingSpan AttributeError

Azure AI Projects SDK의 `_responses_instrumentor.py`에서 `span.span_instance.attributes`에 접근할 때 `AttributeError`가 발생합니다. SDK가 `is_recording`을 메서드가 아닌 프로퍼티처럼 괄호 없이 호출하는 버그로 인해, 녹화하지 않는 `NonRecordingSpan`에서도 `.attributes` 접근 경로가 실행됩니다. 현재 `telemetry.py`에서 클래스 레벨 패치(`NonRecordingSpan.attributes = property(lambda self: {})`)로 우회 중입니다.

### 2. 첫 번째 사용자만 자동 활성화

최초 가입 사용자는 `admin` 역할과 함께 `is_active=1`로 자동 활성화됩니다. 이후 모든 가입자는 `is_active=0`(비활성)으로 생성되며, 관리자가 `/admin` 페이지에서 수동으로 활성화해야 로그인이 가능합니다.

### 3. Health Endpoint 부재

백엔드에는 `/health/ready`와 `/health/live` 엔드포인트가 있지만, 루트 레벨의 `/health` 엔드포인트는 없습니다. ACA 상태 확인 프로브는 `/health/ready` 또는 `/health/live`를 사용해야 합니다.

### 4. MCP 서버 실행 시간 미측정

MCP 서버가 응답 헤더에 `x-execution-time`, `x-response-time`, 또는 `server-timing` 헤더를 제공하지 않는 한, `server_execution_ms` 필드는 `null`로 반환됩니다. 이는 MCP 프로토콜 자체의 제약이 아닌, 개별 MCP 서버 구현에 따른 차이입니다.

### 5. 이미지 태그 캐싱

`update.sh`에서 `:latest` 태그만 사용할 경우 ACA가 이전 이미지를 캐시하여 재사용할 수 있습니다. 변경이 반영되지 않는 경우 리비전 재시작이 필요합니다. **고유 태그** (예: git commit hash, 타임스탬프) 사용을 권장합니다.

### 6. Azure AI Foundry 500 에러

Azure AI Foundry 서비스가 간헐적으로 `500 Internal Server Error`를 반환하는 서비스 측 이슈가 발생할 수 있습니다. 이는 Azure 인프라 측의 일시적 장애로, 에이전트 코드에서는 에러 이벤트를 SSE `error` 프레임으로 전달하여 프론트엔드에서 사용자에게 안내합니다.

---

## 13. 라이선스

MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
