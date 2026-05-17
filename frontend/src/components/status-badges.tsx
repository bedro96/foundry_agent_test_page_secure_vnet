"use client";

/**
 * 시스템 연결 상태 표시 배지.
 *
 * 백엔드 서버와 데이터베이스 연결 상태를 우측 하단에
 * 작고 눈에 띄지 않는 점 표시기로 렌더링합니다.
 * @module status-badges
 */
import { useEffect, useState } from "react";

import { config } from "@/lib/config";

interface SystemStatus {
  backend: boolean;
  db: boolean;
}

const POLL_INTERVAL_MS = 30_000;

export function StatusBadges() {
  const [status, setStatus] = useState<SystemStatus>({
    backend: false,
    db: false,
  });

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(`${config.backendUrl}/health/status`, {
          signal: AbortSignal.timeout(5_000),
        });
        if (!cancelled && res.ok) {
          const data: SystemStatus = await res.json();
          setStatus({ backend: true, db: data.db });
        } else if (!cancelled) {
          setStatus({ backend: false, db: false });
        }
      } catch {
        if (!cancelled) setStatus({ backend: false, db: false });
      }
    }

    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-full border border-border/40 bg-background/80 px-3 py-1.5 shadow-sm backdrop-blur-sm">
      <Indicator label="Backend" ok={status.backend} />
      <Indicator label="DB" ok={status.db} />
    </div>
  );
}

function Indicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`inline-block h-2 w-2 rounded-full ${
          ok
            ? "bg-emerald-500/70 shadow-[0_0_4px_rgba(16,185,129,0.4)]"
            : "bg-red-400/60 shadow-[0_0_4px_rgba(248,113,113,0.3)]"
        }`}
      />
      <span className="text-[10px] font-medium leading-none text-muted-foreground/60">
        {label}
      </span>
    </div>
  );
}
