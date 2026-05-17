"use client";

/**
 * MCP 도구 탐색기 페이지.
 *
 * Streamable HTTP를 통해 원격 MCP 서버에 연결하고,
 * 사용 가능한 도구를 나열하며, 동적 폼 입력 또는
 * 원시 JSON 인수로 도구 호출을 실행하는 UI를 제공합니다.
 * @module mcp-test/page
 */
import { type ChangeEvent, useMemo, useState } from "react";
import { Play, PlugZap, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useAuthGuard } from "@/lib/useAuthGuard";

/** MCP 프록시 호출을 위한 백엔드 기본 URL. */
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

/** MCP 서버 연결을 위한 인증 모드. */
type AuthType = "none" | "api_key";

/** JSON Schema의 단일 속성 정의. */
type SchemaProperty = {
  /** JSON Schema 타입 (예: `"string"`, `"number"`, `["string", "null"]`). */
  type?: string | string[];
  /** 사람이 읽을 수 있는 속성 설명. */
  description?: string;
};

/** `/api/mcp/connect` 엔드포인트에서 반환되는 MCP 도구 기술자. */
interface McpTool {
  /** 고유 도구 이름. */
  name: string;
  /** 사람이 읽을 수 있는 도구 목적 설명. */
  description?: string;
  /** 도구의 입력 매개변수를 설명하는 JSON Schema. */
  inputSchema?: {
    /** 스키마 타입 — 일반적으로 `"object"`. */
    type?: string;
    /** 타입과 설명을 포함하는 명명된 속성. */
    properties?: Record<string, SchemaProperty>;
    /** 필수 속성 이름 목록. */
    required?: string[];
  };
}

/** 백엔드 MCP 프록시에서 반환된 타이밍 상세 내역. */
interface McpTiming {
  total_ms: number;
  initialize_ms?: number;
  list_tools_ms?: number;
  tool_call_ms?: number;
  server_execution_ms?: number | null;
}

/** 결과 패널에 표시되는 기록된 도구 실행 결과. */
interface ExecutionResult {
  /** 고유 결과 ID. */
  id: string;
  /** 실행된 도구의 이름. */
  tool: string;
  /** 사람이 읽을 수 있는 실행 타임스탬프. */
  timestamp: string;
  /** 성공적인 결과 페이로드. */
  result?: unknown;
  /** 실행 실패 시 오류 메시지. */
  error?: string;
  /** 백엔드에서 측정된 타이밍 상세 내역. */
  timing?: McpTiming;
}

/**
 * 속성 정의에서 유효한 JSON Schema 타입 문자열을 확인합니다.
 *
 * @param property - 검사할 스키마 속성.
 * @returns 타입 문자열 (지정되지 않은 경우 기본값 `"string"`).
 */
const getPropertyType = (property?: SchemaProperty) => {
  if (!property?.type) {
    return "string";
  }

  return Array.isArray(property.type) ? property.type[0] : property.type;
};

/**
 * 도구가 하나 이상의 속성을 가진 구조화된 입력 스키마를 가지고 있는지 확인합니다.
 *
 * @param tool - MCP 도구 기술자.
 * @returns 도구가 명명된 입력 속성을 정의하면 `true`.
 */
const isStructuredInput = (tool: McpTool | null) =>
  Boolean(tool?.inputSchema?.properties && Object.keys(tool.inputSchema.properties).length > 0);

/**
 * MCP 탐색기 페이지 컴포넌트.
 *
 * 세 개의 패널 레이아웃을 렌더링합니다: 연결 설정, 동적 인수 폼이 있는
 * 도구 선택, 그리고 실행 결과 로그.
 */
export default function McpExplorerPage() {
  // 인증 가드: 미인증 사용자는 로그인 페이지('/')로 리다이렉트
  const { loading: authLoading } = useAuthGuard();

  // MCP 서버 URL 입력 값
  const [serverUrl, setServerUrl] = useState("");
  // 인증 방식 (none 또는 api_key)
  const [authType, setAuthType] = useState<AuthType>("none");
  // 인증 헤더 이름 (기본값: x-api-key)
  const [authHeader, setAuthHeader] = useState("x-api-key");
  // 인증 헤더 값 (API 키)
  const [authValue, setAuthValue] = useState("");
  // 서버 연결 진행 중 여부
  const [connecting, setConnecting] = useState(false);
  // 서버 연결 완료 여부
  const [connected, setConnected] = useState(false);
  // 검색된 MCP 도구 목록
  const [tools, setTools] = useState<McpTool[]>([]);
  // 현재 선택된 도구
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null);
  // 구조화된 폼의 도구 인수 상태
  const [toolArgs, setToolArgs] = useState<Record<string, unknown>>({});
  // 원시 JSON 인수 입력 값
  const [rawArgs, setRawArgs] = useState("{}");
  // 도구 실행 진행 중 여부
  const [executing, setExecuting] = useState(false);
  // 도구 실행 결과 히스토리 (최신 순)
  const [results, setResults] = useState<ExecutionResult[]>([]);
  // 오류 메시지 표시 상태
  const [error, setError] = useState("");
  // 연결 시 측정된 타이밍 정보
  const [connectTiming, setConnectTiming] = useState<McpTiming | null>(null);

  // 선택된 도구의 입력 스키마 속성 (메모이제이션)
  const selectedProperties = useMemo(
    () => selectedTool?.inputSchema?.properties ?? {},
    [selectedTool],
  );
  // 필수 필드 이름 집합 (메모이제이션)
  const requiredFields = useMemo(
    () => new Set(selectedTool?.inputSchema?.required ?? []),
    [selectedTool],
  );

  /** 도구 전환 시 도구 인수 상태를 초기화합니다. */
  const resetToolState = () => {
    setToolArgs({});
    setRawArgs("{}");
  };

  /**
   * 도구 목록에서 도구를 선택하고 인수 상태를 초기화합니다.
   *
   * @param tool - 선택할 MCP 도구.
   */
  const handleSelectTool = (tool: McpTool) => {
    setSelectedTool(tool);
    resetToolState();
    setError("");
  };

  /**
   * MCP 서버에 연결하고 사용 가능한 도구 목록을 가져옵니다.
   *
   * 연결 세부 정보(URL, 인증)를 백엔드 프록시로 전송하여 Streamable HTTP
   * 세션을 설정하고 도구 카탈로그를 반환합니다.
   */
  const handleConnect = async () => {
    if (!serverUrl.trim()) {
      setError("Enter an MCP server URL before connecting.");
      return;
    }

    console.log(`[mcp-test] Connecting to MCP server: url=${serverUrl.trim()} authType=${authType}`);
    setConnecting(true);
    setError("");

    try {
      const response = await fetch(`${BACKEND_URL}/api/mcp/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server_url: serverUrl.trim(),
          auth_type: authType,
          auth_header: authHeader,
          auth_value: authValue,
        }),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || data.detail || "Failed to connect to MCP server.");
      }

      const nextTools: McpTool[] = Array.isArray(data.tools) ? data.tools : [];
      const timing: McpTiming | undefined = data.timing;
      console.log(`[mcp-test] Connected: tools_count=${nextTools.length}, timing=${JSON.stringify(timing)}`);
      setResults([]);
      setTools(nextTools);
      setConnected(true);
      setConnectTiming(timing ?? null);
      setSelectedTool(nextTools[0] ?? null);
      resetToolState();
    } catch (err) {
      console.log(`[mcp-test] Connection failed: ${err instanceof Error ? err.message : "unknown"}`);
      setConnected(false);
      setResults([]);
      setTools([]);
      setSelectedTool(null);
      setConnectTiming(null);
      resetToolState();
      setError(err instanceof Error ? err.message : "Failed to connect to MCP server.");
    } finally {
      setConnecting(false);
    }
  };

  /**
   * 도구 인수 상태에서 단일 필드를 업데이트합니다.
   *
   * @param field - 업데이트할 속성 이름.
   * @param value - 새 값.
   */
  const updateField = (field: string, value: unknown) => {
    setToolArgs((current) => ({ ...current, [field]: value }));
  };

  /**
   * 특정 폼 필드에 대한 변경 핸들러를 생성하며,
   * 필드의 JSON Schema 타입에 따라 값을 변환합니다.
   *
   * @param field - 속성 이름.
   * @param property - 이 필드의 JSON Schema 정의.
   * @returns input/textarea 변경 이벤트에 대한 이벤트 핸들러.
   */
  const handleFieldChange = (field: string, property: SchemaProperty) => (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const type = getPropertyType(property);

    if (type === "boolean" && event.target instanceof HTMLInputElement) {
      updateField(field, event.target.checked);
      return;
    }

    updateField(field, event.target.value);
  };

  /**
   * 폼 필드 또는 원시 JSON 입력에서 최종 인수 객체를 구성합니다.
   *
   * 필수 필드를 검증하고 타입(숫자, 불리언, JSON 객체)을 변환합니다.
   *
   * @returns 도구의 `arguments` 페이로드로 전송할 일반 객체.
   * @throws {Error} 필수 필드가 누락되거나 값이 유효하지 않을 때.
   */
  const buildArguments = () => {
    if (!selectedTool) {
      return {};
    }

    if (!isStructuredInput(selectedTool)) {
      const parsed = rawArgs.trim() ? JSON.parse(rawArgs) : {};
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Raw JSON arguments must be a JSON object.");
      }
      return parsed;
    }

    const entries = Object.entries(selectedProperties).reduce<Record<string, unknown>>((accumulator, [field, property]) => {
      const type = getPropertyType(property);
      const value = toolArgs[field];
      const isRequired = requiredFields.has(field);

      if (type === "boolean") {
        if (value === undefined && !isRequired) {
          return accumulator;
        }

        accumulator[field] = Boolean(value);
        return accumulator;
      }

      if (value === undefined || value === "") {
        if (isRequired) {
          throw new Error(`Field \"${field}\" is required.`);
        }
        return accumulator;
      }

      if (type === "number" || type === "integer") {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue)) {
          throw new Error(`Field \"${field}\" must be a valid number.`);
        }
        if (type === "integer" && !Number.isInteger(numericValue)) {
          throw new Error(`Field \"${field}\" must be a whole number.`);
        }
        accumulator[field] = numericValue;
        return accumulator;
      }

      if (type === "object" || type === "array") {
        accumulator[field] = typeof value === "string" ? JSON.parse(value) : value;
        return accumulator;
      }

      accumulator[field] = value;
      return accumulator;
    }, {});

    return entries;
  };

  /**
   * 현재 인수로 선택된 도구를 실행합니다.
   *
   * 도구 호출을 백엔드 MCP 프록시로 전송하고 결과
   * (또는 오류)를 실행 히스토리에 기록합니다.
   */
  const handleExecute = async () => {
    if (!selectedTool) {
      setError("Select a tool to execute.");
      return;
    }

    console.log(`[mcp-test] Executing tool: name=${selectedTool.name}`);
    let argumentsPayload: unknown;

    try {
      argumentsPayload = buildArguments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid arguments.");
      return;
    }

    setExecuting(true);
    setError("");

    try {
      const response = await fetch(`${BACKEND_URL}/api/mcp/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server_url: serverUrl.trim(),
          auth_type: authType,
          auth_header: authHeader,
          auth_value: authValue,
          tool_name: selectedTool.name,
          arguments: argumentsPayload,
        }),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || data.detail || "Tool execution failed.");
      }

      setResults((current) => [
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          tool: selectedTool.name,
          timestamp: new Date().toLocaleString(),
          result: data.result,
          timing: data.timing,
        },
        ...current,
      ]);
      console.log(`[mcp-test] Tool executed successfully: name=${selectedTool.name}, timing=${JSON.stringify(data.timing)}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Tool execution failed.";
      console.log(`[mcp-test] Tool execution failed: name=${selectedTool.name} error=${message}`);
      setError(message);
      setResults((current) => [
        {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          tool: selectedTool.name,
          timestamp: new Date().toLocaleString(),
          error: message,
        },
        ...current,
      ]);
    } finally {
      setExecuting(false);
    }
  };

  // 인증 확인 중이면 로딩 표시
  if (authLoading) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <div className="text-muted-foreground text-sm">인증 확인 중...</div>
      </main>
    );
  }

  return (
    <main className="flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top_left,_hsl(var(--primary)/0.16),_transparent_35%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.35))] text-foreground">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <section className="overflow-hidden rounded-[28px] border border-border/70 bg-background/85 shadow-[0_24px_80px_-40px_hsl(var(--foreground)/0.45)] backdrop-blur-xl">
          <div className="grid gap-0 lg:grid-cols-5">
            {/* ── 좌측 패널: 연결 설정, 도구 목록, 도구 입력 폼 ── */}
            <div className="space-y-6 border-b border-border/60 p-4 lg:col-span-3 lg:border-b-0 lg:border-r lg:p-6">
              {/* 연결 설정 카드 */}
              <div className="rounded-3xl border border-border/60 bg-muted/40 p-4 shadow-sm">
                <div className="flex flex-col gap-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <Badge variant="secondary" className="rounded-full px-3 py-1 text-xs uppercase tracking-[0.22em]">
                        MCP Tool Explorer
                      </Badge>
                      <h1 className="mt-3 font-serif text-3xl tracking-tight text-balance sm:text-4xl">
                        Connect, inspect, and execute remote MCP tools.
                      </h1>
                    </div>
                    <div className="hidden rounded-2xl border border-primary/20 bg-primary/10 p-3 text-primary sm:block">
                      <PlugZap className="h-5 w-5" />
                    </div>
                  </div>

                  {/* 서버 URL, 인증 방식, 연결 버튼 행 */}
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,2.2fr)_180px_auto]">
                    <div className="grid gap-2">
                      <Label htmlFor="server-url">MCP Server URL</Label>
                      <Input
                        id="server-url"
                        placeholder="https://mcp-server.example.com/mcp"
                        value={serverUrl}
                        onChange={(event) => setServerUrl(event.target.value)}
                      />
                    </div>

                    <div className="grid gap-2">
                      <Label htmlFor="auth-type">Authentication</Label>
                      <select
                        id="auth-type"
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                        value={authType}
                        onChange={(event) => setAuthType(event.target.value as AuthType)}
                      >
                        <option value="none">None</option>
                        <option value="api_key">API Key (x-api-key)</option>
                      </select>
                    </div>

                    <div className="flex items-end">
                      <Button className="w-full xl:w-auto" onClick={handleConnect} disabled={connecting}>
                        <PlugZap className="mr-2 h-4 w-4" />
                        {connecting ? "Connecting..." : connected ? "Reconnect" : "Connect"}
                      </Button>
                    </div>
                  </div>

                  {/* API 키 인증 선택 시 헤더 이름/값 입력 필드 */}
                  {authType === "api_key" ? (
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="grid gap-2">
                        <Label htmlFor="auth-header">Header Name</Label>
                        <Input
                          id="auth-header"
                          value={authHeader}
                          onChange={(event) => setAuthHeader(event.target.value)}
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="auth-value">Header Value</Label>
                        <Input
                          id="auth-value"
                          type="password"
                          placeholder="Enter API key"
                          value={authValue}
                          onChange={(event) => setAuthValue(event.target.value)}
                        />
                      </div>
                    </div>
                  ) : null}

                  {/* 오류 메시지 또는 백엔드 URL 표시 */}
                  {error ? (
                    <div className="rounded-2xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                      {error}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Backend target: <span className="font-medium text-foreground">{BACKEND_URL}</span>
                    </p>
                  )}

                  {/* 연결 타이밍 정보 표시 배지 */}
                  {connected && connectTiming ? (
                    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm">
                      <span className="font-medium text-foreground">Connection Timing:</span>
                      <Badge variant="secondary" className="rounded-full">Total: {connectTiming.total_ms.toFixed(0)} ms</Badge>
                      {connectTiming.initialize_ms ? (
                        <Badge variant="outline" className="rounded-full">Init: {connectTiming.initialize_ms.toFixed(0)} ms</Badge>
                      ) : null}
                      {connectTiming.list_tools_ms ? (
                        <Badge variant="outline" className="rounded-full">List Tools: {connectTiming.list_tools_ms.toFixed(0)} ms</Badge>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>

              {/* ── 사용 가능한 도구 목록 카드 ── */}
              <Card className="border-border/60 bg-background/90 shadow-none">
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <div>
                    <CardTitle className="text-xl">Available Tools</CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Choose a discovered tool to inspect its schema and prepare an invocation.
                    </p>
                  </div>
                  <Badge variant="outline" className="rounded-full px-3 py-1">
                    {tools.length} tools
                  </Badge>
                </CardHeader>
                <CardContent>
                  {connected && tools.length > 0 ? (
                    <ScrollArea className="h-[260px] pr-4">
                      <div className="grid gap-3">
                        {tools.map((tool) => {
                          const active = selectedTool?.name === tool.name;
                          return (
                            <button
                              key={tool.name}
                              type="button"
                              onClick={() => handleSelectTool(tool)}
                              className={`rounded-2xl border px-4 py-3 text-left transition hover:border-primary/50 hover:bg-primary/5 ${
                                active
                                  ? "border-primary bg-primary/10 shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.25)]"
                                  : "border-border/60 bg-card/70"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <p className="font-medium text-foreground">{tool.name}</p>
                                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                                    {tool.description || "No description provided."}
                                  </p>
                                </div>
                                {active ? <Badge className="rounded-full">Selected</Badge> : null}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </ScrollArea>
                  ) : connected ? (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                      Connected successfully, but this MCP server did not return any tools.
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                      Connect to an MCP server to discover tools.
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* ── 도구 입력 폼 카드 ── */}
              <Card className="border-border/60 bg-background/90 shadow-none">
                <CardHeader>
                  <CardTitle className="text-xl">Tool Input</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    {selectedTool
                      ? `Configure arguments for ${selectedTool.name}.`
                      : "Select a tool to generate its input form."}
                  </p>
                </CardHeader>
                <CardContent className="space-y-4">
                  {selectedTool ? (
                    <>
                      <div className="rounded-2xl border border-border/60 bg-muted/25 p-4 text-sm text-muted-foreground">
                        <p className="font-medium text-foreground">{selectedTool.name}</p>
                        <p className="mt-1 leading-6">
                          {selectedTool.description || "No description provided."}
                        </p>
                      </div>

                      {isStructuredInput(selectedTool) ? (
                        <div className="grid gap-4 md:grid-cols-2">
                          {Object.entries(selectedProperties).map(([field, property]) => {
                            const fieldType = getPropertyType(property);
                            const required = requiredFields.has(field);
                            const value = toolArgs[field];

                            return (
                              <div key={field} className={fieldType === "object" || fieldType === "array" ? "md:col-span-2" : ""}>
                                <Label htmlFor={`field-${field}`} className="mb-2 block">
                                  {field}
                                  {required ? <span className="text-destructive"> *</span> : null}
                                </Label>
                                {fieldType === "boolean" ? (
                                  <label className="flex h-10 items-center gap-3 rounded-md border border-input bg-background px-3 text-sm">
                                    <input
                                      id={`field-${field}`}
                                      type="checkbox"
                                      checked={Boolean(value)}
                                      onChange={handleFieldChange(field, property)}
                                      className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                                    />
                                    <span>{property.description || "Enable this option"}</span>
                                  </label>
                                ) : fieldType === "object" || fieldType === "array" ? (
                                  <Textarea
                                    id={`field-${field}`}
                                    value={typeof value === "string" ? value : ""}
                                    onChange={handleFieldChange(field, property)}
                                    placeholder={fieldType === "array" ? "[]" : "{}"}
                                    className="min-h-28 font-mono text-sm"
                                  />
                                ) : (
                                  <Input
                                    id={`field-${field}`}
                                    type={fieldType === "number" || fieldType === "integer" ? "number" : "text"}
                                    value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
                                    onChange={handleFieldChange(field, property)}
                                    placeholder={property.description || `Enter ${field}`}
                                  />
                                )}
                                {fieldType !== "boolean" && property.description ? (
                                  <p className="mt-2 text-xs text-muted-foreground">{property.description}</p>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <Label htmlFor="raw-args">Raw JSON arguments</Label>
                          <Textarea
                            id="raw-args"
                            value={rawArgs}
                            onChange={(event) => setRawArgs(event.target.value)}
                            placeholder="{}"
                            className="min-h-40 font-mono text-sm"
                          />
                          <p className="text-xs text-muted-foreground">
                            This tool does not expose individual schema properties. Provide a JSON object directly.
                          </p>
                        </div>
                      )}

                      <Separator />

                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <p className="text-sm text-muted-foreground">
                          Required fields are marked with an asterisk. Object and array inputs accept JSON.
                        </p>
                        <Button onClick={handleExecute} disabled={!connected || executing}>
                          <Play className="mr-2 h-4 w-4" />
                          {executing ? "Executing..." : "Execute"}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                      Select a tool from the list to generate its input form.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* ── 우측 패널: 실행 결과 히스토리 ── */}
            <div className="p-4 lg:col-span-2 lg:p-6">
              <Card className="flex h-full min-h-[720px] flex-col border-border/60 bg-background/92 shadow-none">
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <div>
                    <CardTitle className="text-xl">Execution Results</CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Recent responses are appended here with the newest execution on top.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setResults([])}
                    disabled={results.length === 0}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Clear
                  </Button>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col overflow-hidden">
                  <ScrollArea className="h-[calc(100vh-16rem)] min-h-[560px] pr-4">
                    <div className="space-y-4">
                      {executing ? (
                        <div className="rounded-2xl border border-primary/20 bg-primary/10 px-4 py-3 text-sm text-primary">
                          Executing...
                        </div>
                      ) : null}

                      {results.length === 0 ? (
                        <div className="rounded-2xl border border-dashed border-border/70 bg-muted/30 px-4 py-10 text-center text-sm text-muted-foreground">
                          Waiting for execution...
                        </div>
                      ) : null}

                      {results.map((entry) => (
                        <div key={entry.id} className="rounded-3xl border border-border/60 bg-muted/20 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <p className="font-medium text-foreground">{entry.tool}</p>
                              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                                {entry.timestamp}
                              </p>
                            </div>
                            <Badge variant={entry.error ? "destructive" : "secondary"} className="rounded-full">
                              {entry.error ? "Failed" : "Success"}
                            </Badge>
                          </div>
                          {entry.timing ? (
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <Badge variant="secondary" className="rounded-full text-xs">
                                Total: {entry.timing.total_ms.toFixed(0)} ms
                              </Badge>
                              {entry.timing.initialize_ms ? (
                                <Badge variant="outline" className="rounded-full text-xs">
                                  Init: {entry.timing.initialize_ms.toFixed(0)} ms
                                </Badge>
                              ) : null}
                              {entry.timing.tool_call_ms ? (
                                <Badge variant="outline" className="rounded-full text-xs">
                                  Tool Call: {entry.timing.tool_call_ms.toFixed(0)} ms
                                </Badge>
                              ) : null}
                              {entry.timing.server_execution_ms != null ? (
                                <Badge variant="outline" className="rounded-full text-xs font-semibold text-primary">
                                  Server Exec: {entry.timing.server_execution_ms.toFixed(0)} ms
                                </Badge>
                              ) : null}
                            </div>
                          ) : null}
                          {entry.error ? (
                            <p className="mt-3 text-sm text-destructive">{entry.error}</p>
                          ) : null}
                          <pre className="mt-4 overflow-x-auto rounded-2xl border border-border/60 bg-background/90 p-4 font-mono text-xs leading-6 text-foreground">
                            {JSON.stringify(entry.error ? { error: entry.error } : entry.result, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
