"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AppShell, { isStaff } from "@/components/AppShell";
import { fetchMe, User } from "@/lib/auth";
import { api, ApiError, formatTime } from "@/lib/support";

type Entry = {
  id: number;
  created_at: string;
  actor_email: string | null;
  actor_name: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
};

const ACTIONS: { code: string; label: string }[] = [
  { code: "", label: "Semua" },
  { code: "login", label: "Login admin/staf" },
  { code: "login_gagal", label: "Login gagal" },
  { code: "bantuan_balas", label: "Balas bantuan" },
  { code: "bantuan_tutup", label: "Tutup bantuan" },
  { code: "status_online", label: "Online" },
  { code: "status_offline", label: "Offline" },
];
const label = (code: string) => ACTIONS.find((a) => a.code === code)?.label ?? code;

/** Log audit (F-15): hanya baca, untuk admin/staf. */
export default function AuditPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [action, setAction] = useState("");
  const [rows, setRows] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe().then((me) => {
      if (!me) return router.replace("/login");
      if (!isStaff(me)) return router.replace("/");
      setUser(me);
    });
  }, [router]);

  const load = useCallback(async (before?: number) => {
    try {
      const qs = new URLSearchParams({ limit: "100" });
      if (action) qs.set("action", action);
      if (before) qs.set("before", String(before));
      const data = await api<Entry[]>(`/api/admin/audit?${qs}`);
      setRows((prev) => (before ? [...prev, ...data] : data));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return router.replace("/login");
      setError((e as Error).message);
    }
  }, [action, router]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <AppShell user={user} active="audit">
      <main className="flex min-h-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3 md:px-6">
          <div>
            <h1 className="text-lg font-semibold">Log Audit</h1>
            <p className="text-xs text-gray-500">Aktivitas admin/staf dan upaya login gagal. Catatan tidak bisa diubah atau dihapus.</p>
          </div>
          <select value={action} onChange={(e) => setAction(e.target.value)} className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm">
            {ACTIONS.map((a) => <option key={a.code} value={a.code}>{a.label}</option>)}
          </select>
        </header>
        {error && <p className="px-4 py-2 text-xs text-red-700 md:px-6">{error}</p>}
        <div className="min-h-0 flex-1 overflow-auto px-4 py-4 md:px-6">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr><th className="py-2 pr-3">Waktu</th><th className="pr-3">Pelaku</th><th className="pr-3">Aksi</th><th className="pr-3">Objek</th><th>Detail</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={5} className="py-6 text-gray-500">Belum ada catatan.</td></tr>}
              {rows.map((r) => (
                <tr key={r.id} className="align-top">
                  <td className="whitespace-nowrap py-2 pr-3 text-gray-600">{formatTime(r.created_at)}</td>
                  <td className="pr-3">{r.actor_name ?? "-"}<div className="text-xs text-gray-500">{r.actor_email}</div></td>
                  <td className="pr-3"><span className={`rounded px-1.5 py-0.5 text-xs ${r.action === "login_gagal" ? "bg-red-100 text-red-800" : "bg-gray-100"}`}>{label(r.action)}</span></td>
                  <td className="pr-3 text-xs text-gray-600">{r.target_id ? `${r.target_type} ${r.target_id.slice(0, 8)}` : "-"}</td>
                  <td className="text-xs text-gray-600">{Object.entries(r.detail).map(([k, v]) => `${k}: ${v}`).join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length >= 100 && rows.length % 100 === 0 && (
            <button onClick={() => load(rows[rows.length - 1].id)} className="mt-3 rounded border border-gray-300 px-3 py-1 text-xs">Muat lebih lama</button>
          )}
        </div>
      </main>
    </AppShell>
  );
}
