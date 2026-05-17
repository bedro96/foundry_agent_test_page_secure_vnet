# 🔍 GenAI 텔레메트리 트레이싱 가이드

## 목차

1. [개요](#개요)
2. [텔레메트리란?](#텔레메트리란)
3. [아키텍처](#아키텍처)
4. [활성화 방법](#활성화-방법)
5. [비활성화 방법](#비활성화-방법)
6. [환경변수 설명](#환경변수-설명)
7. [Application Insights에서 확인할 수 있는 데이터](#application-insights에서-확인할-수-있는-데이터)
8. [트레이스 확인 방법](#트레이스-확인-방법)
9. [문제 해결](#문제-해결)
10. [보안 고려사항](#보안-고려사항)

---

## 개요

이 문서는 AI 채팅 포털 백엔드에 구현된 **GenAI 텔레메트리 트레이싱** 기능에 대해 설명합니다.

이 기능은 [OpenTelemetry](https://opentelemetry.io/) 표준을 기반으로 하며, Azure AI Foundry 에이전트의 실행 과정을 자동으로 추적하여 **Azure Application Insights**에 트레이스 데이터를 전송합니다.

이를 통해 다음과 같은 질문에 답할 수 있습니다:
- 에이전트가 LLM 모델을 몇 번 호출했는가?
- 각 LLM 호출에 걸린 시간은 얼마인가?
- 어떤 도구(MCP, Bing 그라운딩 등)가 호출되었는가?
- 사용자의 프롬프트와 에이전트의 응답 내용은 무엇인가?
- 에러가 발생한 경우 어느 단계에서 실패했는가?

---

## 텔레메트리란?

**텔레메트리(Telemetry)**는 원격 시스템의 상태와 동작을 자동으로 측정하고 수집하여 분석하는 기술입니다.

### 텔레메트리의 3가지 핵심 데이터 유형

| 유형 | 설명 | 예시 |
|------|------|------|
| **트레이스 (Traces)** | 요청의 전체 실행 경로를 추적 | 채팅 요청 → 에이전트 호출 → LLM 응답 → 도구 실행 |
| **메트릭 (Metrics)** | 수치적 측정값 | 응답 시간, 토큰 사용량, 에러율 |
| **로그 (Logs)** | 구조화된 이벤트 기록 | 에러 메시지, 경고, 디버그 정보 |

이 프로젝트에서는 주로 **트레이스**를 활용하여 AI 에이전트의 실행 흐름을 추적합니다.

### OpenTelemetry란?

[OpenTelemetry](https://opentelemetry.io/)는 텔레메트리 데이터 수집을 위한 오픈 소스 표준 프레임워크입니다. 벤더에 종속되지 않으며, 다양한 모니터링 시스템(Application Insights, Jaeger, Zipkin 등)과 연동할 수 있습니다.

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI 백엔드                                 │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐ │
│  │ telemetry.py │───▶│ AIProject        │───▶│ Application   │ │
│  │ (초기화)      │    │ Instrumentor     │    │ Insights      │ │
│  └──────────────┘    └──────────────────┘    │ 연결 문자열    │ │
│                                              └───────┬───────┘ │
│  ┌──────────────┐    ┌──────────────────┐            │         │
│  │ agent.py     │───▶│ OpenTelemetry    │            │         │
│  │ (스팬 생성)   │    │ Tracer           │            │         │
│  └──────────────┘    └──────────────────┘            │         │
│                              │                       │         │
│                              ▼                       │         │
│                   ┌──────────────────┐               │         │
│                   │ Azure Monitor    │───────────────▶│         │
│                   │ Exporter         │               │         │
│                   └──────────────────┘               │         │
└─────────────────────────────────────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────┐
                                          │ Azure Application  │
                                          │ Insights           │
                                          │                    │
                                          │ - 트레이스 뷰어    │
                                          │ - 실시간 메트릭    │
                                          │ - 장애 진단       │
                                          └────────────────────┘
```

### 데이터 흐름

1. **앱 시작**: `telemetry.py`가 Foundry 프로젝트에서 Application Insights 연결 문자열을 가져옴
2. **Azure Monitor 구성**: `configure_azure_monitor()`로 트레이스 익스포터 설정
3. **자동 계측**: `AIProjectInstrumentor()`가 Azure AI SDK 호출을 자동으로 트레이싱
4. **수동 스팬**: `agent.py`에서 `invoke_agent {agent_name}` 스팬과 하위 스팬(`resolve-agent`, `ensure-conversation`, `tool-call:*`)으로 각 채팅 요청을 추적
5. **데이터 전송**: 수집된 트레이스가 Application Insights로 비동기 전송

---

## 활성화 방법

### 1단계: 환경변수 설정

`backend/.env` 파일에 다음 두 변수를 추가합니다:

```env
# GenAI 트레이싱 활성화
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true

# 메시지 내용 캡처 (디버깅용; 프로덕션에서는 false 권장)
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
```

### 2단계: 의존성 확인

`pyproject.toml`에 다음 패키지가 포함되어 있는지 확인합니다 (이미 설치되어 있음):

```toml
"opentelemetry-sdk>=1.40,<1.41",
"azure-core-tracing-opentelemetry>=1.0.0b12",
"azure-monitor-opentelemetry>=1.8.7",
```

### 3단계: 배포

환경변수 변경 후 Docker 이미지를 재빌드하고 배포합니다:

```bash
cd backend
bash update.sh
```

### 4단계: 확인

서버 로그에 다음 메시지가 표시되면 성공적으로 활성화된 것입니다:

```
INFO: GenAI 텔레메트리 트레이싱이 활성화되었습니다
INFO: Application Insights 연결 문자열을 성공적으로 가져왔습니다
INFO: Azure Monitor가 Application Insights에 연결되었습니다
INFO: AIProjectInstrumentor 계측이 활성화되었습니다
```

---

## 비활성화 방법

텔레메트리를 비활성화하려면 `backend/.env`에서 다음과 같이 변경합니다:

```env
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=false
```

변경 후 재배포가 필요합니다.

> **참고**: 비활성화해도 기존에 수집된 Application Insights 데이터는 유지됩니다.

---

## 환경변수 설명

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING` | `true` | `config.py`의 기본값은 `true`입니다. `true`로 설정하면 Azure SDK가 LLM 호출에 대한 OpenTelemetry 스팬을 자동 생성합니다. |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `true` | `config.py`의 기본값은 `true`입니다. 실제 메시지 내용이 트레이스에 포함되므로, 프로덕션에서는 명시적으로 `false`를 설정하는 것을 권장합니다. |

### 내부적으로 사용되는 설정

| 설정 | 위치 | 설명 |
|------|------|------|
| `azure.core.settings.tracing_implementation` | `telemetry.py` | `"opentelemetry"`로 설정하여 Azure Core SDK가 OpenTelemetry를 추적 백엔드로 사용하도록 합니다. |
| Application Insights 연결 문자열 | Foundry 프로젝트 | `project_client.telemetry.get_application_insights_connection_string()`을 통해 동적으로 가져옵니다. 별도의 환경변수 설정이 필요 없습니다. |

---

## Application Insights에서 확인할 수 있는 데이터

### 자동 수집 데이터 (AIProjectInstrumentor)

| 데이터 | 설명 |
|--------|------|
| **LLM 호출 스팬** | 각 모델 호출의 시작/종료 시간, 소요 시간 |
| **토큰 사용량** | 입력/출력 토큰 수 |
| **모델 정보** | 사용된 모델 배포 이름 |
| **도구 호출** | MCP 도구, Bing 그라운딩 등의 호출 정보 |
| **에러 정보** | 실패한 호출의 오류 메시지 및 스택 트레이스 |

### 수동 스팬 데이터 (agent.py)

| 속성 | 설명 |
|------|------|
| `gen_ai.operation.name` | 에이전트 호출 작업명 (`invoke_agent`) |
| `gen_ai.agent.name` | Foundry 에이전트 표시 이름 |
| `gen_ai.request.model` | 사용 중인 모델 배포 이름 |
| `gen_ai.conversation.id` | 채팅 대화 식별자 |
| `gen_ai.completion_state` | 완료 상태 (`complete` 또는 `failed`) |
| `message_count` | 요청에 포함된 메시지 수 |

### 메시지 내용 캡처 시 추가 데이터

`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`일 때:

| 데이터 | 설명 |
|--------|------|
| **사용자 프롬프트** | 사용자가 보낸 실제 메시지 내용 |
| **시스템 프롬프트** | 에이전트에 설정된 지침 |
| **어시스턴트 응답** | AI가 생성한 응답 내용 |
| **도구 입출력** | 도구 호출의 매개변수 및 결과 |

---

## 트레이스 확인 방법

### Azure Portal에서 확인

1. [Azure Portal](https://portal.azure.com)에 로그인합니다.
2. AI Foundry 프로젝트에 연결된 **Application Insights** 리소스로 이동합니다.
3. 왼쪽 메뉴에서 **조사** → **트랜잭션 검색**을 클릭합니다.
4. 시간 범위를 설정하고 이벤트 유형을 **추적**으로 필터링합니다.

### 트레이스 맵 사용

1. Application Insights에서 **성능** → **작업** 탭으로 이동합니다.
2. `invoke_agent <agent-name>` 작업을 클릭하면 전체 실행 흐름을 시각적으로 확인할 수 있습니다.
3. 각 스팬을 클릭하면 상세 속성(소요 시간, 상태, 커스텀 속성 등)을 볼 수 있습니다.

### Azure AI Foundry 포털에서 확인

1. [Azure AI Foundry](https://ai.azure.com)에 로그인합니다.
2. 프로젝트의 **Tracing** 탭으로 이동합니다.
3. 에이전트 호출별 트레이스를 시각적으로 확인할 수 있습니다.

### KQL 쿼리 예시

Application Insights의 **로그** 메뉴에서 Kusto Query Language(KQL)를 사용하여 상세 분석이 가능합니다:

```kql
// 최근 24시간 동안의 에이전트 호출 트레이스
traces
| where timestamp > ago(24h)
| where operation_Name startswith "invoke_agent"
| project timestamp, duration, customDimensions
| order by timestamp desc

// LLM 호출 평균 응답 시간
dependencies
| where timestamp > ago(24h)
| where type == "Azure.AI"
| summarize avg(duration), count() by name
| order by avg_duration desc

// 실패한 요청 분석
traces
| where timestamp > ago(24h)
| where tostring(customDimensions["gen_ai.completion_state"]) == "failed"
| project timestamp, tostring(customDimensions["gen_ai.conversation.id"]), message
```

---

## 문제 해결

### 텔레메트리가 활성화되지 않는 경우

1. **환경변수 확인**: `.env` 파일에 `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true`가 설정되어 있는지 확인합니다.
2. **재빌드 필요**: `.env` 변경 후 Docker 이미지를 재빌드해야 합니다 (`.env`가 이미지에 포함됨).
3. **로그 확인**: 서버 시작 로그에서 텔레메트리 초기화 관련 메시지를 확인합니다.

### Application Insights에 데이터가 표시되지 않는 경우

1. **지연**: 데이터가 Application Insights에 표시되기까지 최대 5분이 걸릴 수 있습니다.
2. **연결 문자열**: Foundry 프로젝트에 Application Insights가 올바르게 연결되어 있는지 확인합니다.
3. **네트워크**: 백엔드에서 Application Insights 인제스트 엔드포인트로의 아웃바운드 네트워크가 열려 있는지 확인합니다.

### 일반적인 에러 메시지

| 로그 메시지 | 원인 | 해결 방법 |
|------------|------|-----------|
| `Application Insights 연결 문자열 가져오기 실패` | Foundry 프로젝트 인증 실패 또는 App Insights 미연결 | Azure 자격 증명 및 Foundry 프로젝트 설정 확인 |
| `azure.core.settings 설정 실패` | `azure-core-tracing-opentelemetry` 미설치 | `uv sync` 실행하여 의존성 설치 |
| `AIProjectInstrumentor 계측 실패` | `azure-ai-projects` 버전 불일치 | `pyproject.toml`의 버전 확인 |

---

## 보안 고려사항

### 메시지 내용 캡처

`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`로 설정하면 다음 데이터가 Application Insights에 기록됩니다:

- 사용자가 입력한 프롬프트 텍스트
- AI 에이전트의 응답 내용
- 도구 호출의 매개변수 및 결과

⚠️ **주의**: 이 데이터에는 **개인정보**, **비밀 정보**, **민감한 업무 데이터**가 포함될 수 있습니다.

### 프로덕션 환경 권장 설정

```env
# 트레이싱은 활성화하되, 메시지 내용은 캡처하지 않음
AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false
```

이 설정으로 성능 메트릭과 실행 흐름은 추적하면서, 민감한 메시지 내용은 보호할 수 있습니다.

### 데이터 보존

Application Insights의 데이터 보존 기간은 Azure Portal에서 설정할 수 있습니다.
규정 준수 요구사항에 따라 적절한 보존 기간을 설정하세요.

---

## 관련 문서

- [Azure SDK 텔레메트리 샘플 (콘솔)](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/agents/telemetry/sample_agent_basic_with_console_tracing.py)
- [Azure SDK 텔레메트리 샘플 (Azure Monitor)](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/ai/azure-ai-projects/samples/agents/telemetry/sample_agent_basic_with_azure_monitor_tracing.py)
- [MS Learn: 에이전트 SDK 트레이싱](https://learn.microsoft.com/ko-kr/azure/ai-foundry/how-to/develop/trace-agents-sdk)
- [OpenTelemetry Python 문서](https://opentelemetry.io/docs/languages/python/)
- [Azure Monitor OpenTelemetry 문서](https://learn.microsoft.com/ko-kr/azure/azure-monitor/app/opentelemetry-enable)
