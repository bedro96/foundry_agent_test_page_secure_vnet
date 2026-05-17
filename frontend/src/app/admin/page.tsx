"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/* ------------------------------------------------------------------ */
/*  타입 정의                                                           */
/* ------------------------------------------------------------------ */

/** 관리자 페이지에서 사용하는 사용자 정보 타입. */
interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  role: string;
  is_active: number;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  관리자 페이지                                                       */
/* ------------------------------------------------------------------ */

/**
 * 관리자 페이지 컴포넌트.
 *
 * 사용자 목록을 테이블로 표시하고, 인라인 편집, 역할 전환,
 * 활성/비활성 전환, 사용자 삭제 기능을 제공합니다.
 * 관리자 권한이 없는 사용자는 자동으로 리다이렉트됩니다.
 */
export default function AdminPage() {
  // 페이지 이동을 위한 Next.js 라우터
  const router = useRouter();
  // 사용자 목록 데이터
  const [users, setUsers] = useState<AdminUser[]>([]);
  // 사용자 목록 로딩 중 여부
  const [loading, setLoading] = useState(true);
  // API 호출 실패 시 오류 메시지
  const [error, setError] = useState("");
  // 현재 인라인 편집 중인 사용자 ID (null이면 편집 중 아님)
  const [editingId, setEditingId] = useState<string | null>(null);
  // 인라인 편집 폼 데이터 (이메일, 비밀번호, 역할)
  const [editForm, setEditForm] = useState({ email: "", password: "", role: "" });
  // 현재 액션(저장/삭제 등) 진행 중인 사용자 ID
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  /**
   * 백엔드에서 사용자 목록을 가져옵니다.
   *
   * 인증되지 않은 경우 로그인 페이지로, 권한이 없는 경우
   * 채팅 페이지로 리다이렉트합니다.
   */
  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users", { credentials: "include" });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      if (res.status === 403) {
        router.push("/chat");
        return;
      }
      if (!res.ok) throw new Error("Failed to load users");
      setUsers(await res.json());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [router]);

  /** 컴포넌트 마운트 시 사용자 목록을 불러옵니다. */
  useEffect(() => {
    void fetchUsers();
  }, [fetchUsers]);

  /**
   * 사용자 인라인 편집을 시작합니다.
   *
   * @param u - 편집할 사용자 객체.
   */
  const startEdit = (u: AdminUser) => {
    setEditingId(u.id);
    setEditForm({ email: u.email ?? "", password: "", role: u.role });
  };

  /** 인라인 편집을 취소하고 폼 상태를 초기화합니다. */
  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({ email: "", password: "", role: "" });
  };

  /**
   * 편집된 사용자 정보를 백엔드에 저장합니다.
   *
   * @param userId - 수정할 사용자 ID.
   */
  const saveEdit = async (userId: string) => {
    setActionLoading(userId);
    try {
      const body: Record<string, string> = {};
      if (editForm.email) body.email = editForm.email;
      if (editForm.password) body.password = editForm.password;
      if (editForm.role) body.role = editForm.role;

      const res = await fetch(`/api/admin/users/${userId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Update failed");
      }
      cancelEdit();
      await fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setActionLoading(null);
    }
  };

  /**
   * 사용자의 역할을 admin ↔ user로 전환합니다.
   *
   * @param u - 역할을 전환할 사용자 객체.
   */
  const toggleRole = async (u: AdminUser) => {
    const newRole = u.role === "admin" ? "user" : "admin";
    setActionLoading(u.id);
    try {
      const res = await fetch(`/api/admin/users/${u.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Role update failed");
      }
      await fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Role update failed");
    } finally {
      setActionLoading(null);
    }
  };

  /**
   * 사용자 계정을 활성화 또는 비활성화합니다.
   *
   * @param u - 상태를 전환할 사용자 객체.
   */
  const toggleActive = async (u: AdminUser) => {
    const newStatus = u.is_active ? 0 : 1;
    setActionLoading(u.id);
    try {
      const res = await fetch(`/api/admin/users/${u.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ is_active: newStatus }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Status update failed");
      }
      await fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Status update failed");
    } finally {
      setActionLoading(null);
    }
  };

  /**
   * 사용자를 삭제합니다 (확인 대화 상자 표시 후 실행).
   *
   * @param u - 삭제할 사용자 객체.
   */
  const deleteUser = async (u: AdminUser) => {
    if (!window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    setActionLoading(u.id);
    try {
      const res = await fetch(`/api/admin/users/${u.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Delete failed");
      }
      await fetchUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setActionLoading(null);
    }
  };

  /* ---- 렌더링 ---- */
  // 로딩 중 표시
  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      {/* ── 페이지 헤더: 제목 및 사용자 수 ── */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">User Management</h1>
          <p className="text-sm text-muted-foreground">
            {users.length} user{users.length !== 1 ? "s" : ""} registered
          </p>
        </div>
      </div>

      {/* ── 오류 메시지 배너 ── */}
      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
          <button className="ml-3 font-medium underline" onClick={() => setError("")}>
            dismiss
          </button>
        </div>
      )}

      {/* ── 사용자 관리 테이블 ── */}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-muted/30">
                {editingId === u.id ? (
                  /* ---- 인라인 편집 모드 ---- */
                  <>
                    <td className="px-4 py-2 font-medium">{u.username}</td>
                    <td className="px-4 py-2">
                      <Input
                        value={editForm.email}
                        onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))}
                        placeholder="email"
                        className="h-8 w-48"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <select
                        value={editForm.role}
                        onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}
                        className="h-8 rounded-md border bg-background px-2 text-sm"
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                    </td>
                    <td className="px-4 py-2">
                      <Input
                        type="password"
                        value={editForm.password}
                        onChange={(e) => setEditForm((f) => ({ ...f, password: e.target.value }))}
                        placeholder="new password (optional)"
                        className="h-8 w-40"
                      />
                    </td>
                    <td />
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="default"
                          disabled={actionLoading === u.id}
                          onClick={() => void saveEdit(u.id)}
                        >
                          Save
                        </Button>
                        <Button size="sm" variant="ghost" onClick={cancelEdit}>
                          Cancel
                        </Button>
                      </div>
                    </td>
                  </>
                ) : (
                  /* ---- 일반 행 ---- */
                  <>
                    <td className="px-4 py-2 font-medium">{u.username}</td>
                    <td className="px-4 py-2 text-muted-foreground">{u.email || "—"}</td>
                    <td className="px-4 py-2">
                      <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={u.is_active ? "outline" : "destructive"}>
                        {u.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => startEdit(u)}
                        >
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant={u.is_active ? "outline" : "default"}
                          disabled={actionLoading === u.id}
                          onClick={() => void toggleActive(u)}
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actionLoading === u.id}
                          onClick={() => void toggleRole(u)}
                        >
                          {u.role === "admin" ? "→ User" : "→ Admin"}
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={actionLoading === u.id}
                          onClick={() => void deleteUser(u)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
