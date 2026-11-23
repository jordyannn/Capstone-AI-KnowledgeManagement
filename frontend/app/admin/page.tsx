"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AppShell, { isStaff } from "@/components/AppShell";
import SupportThread from "@/components/SupportThread";
import { fetchMe, User } from "@/lib/auth";
import {
  AdminRequestDetail,
  AdminRequestSummary,
  api,
  ApiError,
  categoryLabel,
  formatTime,
  POLL_MS,
  STATUS_LABEL,
  STATUS_STYLE,
} from "@/lib/support";

type Filter = "terbuka" | "menunggu" | "aktif" | "selesai";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "terbuka", label: "Terbuka" },
  { key: "menunggu", label: "Menunggu" },
  { key: "aktif", label: "Aktif" },
  { key: "selesai", label: "Selesai" },
];

/**
 * Halaman staf: antrean livechat/tiket, balas, tutup, dan status online.
 * Polling halaman ini sekaligus menjadi heartbeat: staf dianggap online hanya selama halaman terbuka.
 */
export default function AdminPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [online, setOnline] = useState(false);
  const [filter, setFilter] = useState<Filter>("terbuka");
  const [queue, setQueue] = useState<AdminRequestSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminRequestDetail | null>(null);
  const [showTranscript, setShowTranscript] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const handle = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) return router.replace("/login");
    if (e instanceof ApiError && e.status === 403) return router.replace("/");
    setError((e as Error).message);
  }, [router]);

  useEffect(() => {
    fetchMe().then((me) => {
      if (!me) return router.replace("/login");
      if (!isStaff(me)) return router.replace("/");
      setUser(me);
      api<{ online: boolean }>("/api/admin/support/presence").then((p) => setOnline(p.online)).catch(handle);
    });
  }, [router, handle]);

  const loadQueue = useCallback(async () => {
    try {
      setQueue(await api<AdminRequestSummary[]>(`/api/admin/support/requests?status=${filter}`));
    } catch (e) {
      handle(e);
    }
  }, [filter, handle]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api<AdminRequestDetail>(`/api/admin/support/requests/${id}`));
    } catch (e) {
      handle(e);
    }
  }, [handle]);

  useEffect(() => {
    if (!user) return;
    loadQueue();
    const t = setInterval(loadQueue, 5000);
    return () => clearInterval(t);
  }, [user, loadQueue]);

  useEffect(() => {
    if (!selected) return;
    loadDetail(selected);
    const t = setInterval(() => loadDetail(selected), POLL_MS);
    return () => clearInterval(t);
  }, [selected, loadDetail]);

  async function toggleOnline() {
    try {
      const p = await api<{ online: boolean }>("/api/admin/support/presence", { method: "PUT", body: JSON.stringify({ online: !online }) });
      setOnline(p.online);
    } catch (e) {
      handle(e);
    }
  }

  async function reply(text: string) {
    if (!selected) return;
    setDetail(await api<AdminRequestDetail>(`/api/admin/support/requests/${selected}/messages`, { method: "POST", body: JSON.stringify({ content: text }) }));
    loadQueue();
  }

  async function close() {
    if (!selected || !confirm("Tutup percakapan ini? Mahasiswa tidak dapat membalas lagi.")) return;
    try {
      setDetail(await api<AdminRequestDetail>(`/api/admin/support/requests/${selected}/close`, { method: "POST" }));
      loadQueue();
    } catch (e) {
      handle(e);
    }
  }

  function open(id: string) {
    setDetail(null);
    setSelected(id);
  }

  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <AppShell user={user} active="admin">
      <main className="flex min-h-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3 md:px-6">
          <div>
            <h1 className="text-lg font-semibold">Antrean Bantuan</h1>
            <p className="text-xs text-gray-500">Livechat dan tiket dari mahasiswa. Saat Anda online, mahasiswa baru mendapat livechat; saat offline, tiket.</p>
          </div>
          <button
            onClick={toggleOnline}
            className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium ${online ? "border-green-600 bg-green-50 text-green-800" : "border-gray-300 bg-white text-gray-600"}`}
          >
            <span className={`h-2.5 w-2.5 rounded-full ${online ? "bg-green-500" : "bg-gray-400"}`} />
            {online ? "Online" : "Offline"}
          </button>
        </header>
        {error && <p className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700 md:px-6">{error}</p>}

        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <section className={`${selected ? "hidden md:flex" : "flex"} min-h-0 flex-col border-gray-200 bg-white md:w-96 md:shrink-0 md:border-r`}>
            <div className="flex gap-1 border-b border-gray-200 px-3 py-2">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={`rounded px-2 py-1 text-xs ${filter === f.key ? "bg-gray-900 text-white" : "hover:bg-gray-100"}`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <ul className="min-h-0 flex-1 divide-y divide-gray-100 overflow-y-auto">
              {queue.length === 0 && <li className="px-4 py-6 text-sm text-gray-500">Tidak ada permintaan.</li>}
              {queue.map((r) => (
                <li key={r.id}>
                  <button onClick={() => open(r.id)} className={`block w-full px-4 py-3 text-left hover:bg-gray-50 ${r.id === selected ? "bg-gray-100" : ""}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{r.student.full_name}</span>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                    </div>
                    <p className="truncate text-sm text-gray-700">{r.subject}</p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {r.kind === "livechat" ? "Livechat" : "Tiket"} · {categoryLabel(r.category)} · {formatTime(r.created_at)}
                      {r.assigned_staff_name && ` · ${r.assigned_staff_name}`}
                    </p>
                    {r.last_sender_role === "mahasiswa" && r.status !== "selesai" && <p className="mt-0.5 text-xs font-medium text-amber-700">Menunggu balasan</p>}
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className={`${selected ? "flex" : "hidden md:flex"} min-h-0 min-w-0 flex-1 flex-col`}>
            {!selected && <p className="m-auto text-sm text-gray-400">Pilih permintaan di antrean.</p>}
            {selected && !detail && <p className="p-4 text-sm text-gray-500">Memuat...</p>}
            {detail && (
              <>
                <div className="border-b border-gray-200 bg-white px-4 py-3 md:px-6">
                  <button onClick={() => setSelected(null)} className="mb-1 text-xs text-gray-500 underline md:hidden">← Kembali ke antrean</button>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="truncate font-semibold">{detail.subject}</h2>
                      <p className="text-xs text-gray-500">
                        {detail.student.full_name} ({detail.student.email}) · {detail.kind === "livechat" ? "Livechat" : "Tiket"} · {categoryLabel(detail.category)}
                      </p>
                    </div>
                    {detail.status !== "selesai" && (
                      <button onClick={close} className="shrink-0 rounded border border-gray-300 px-3 py-1 text-xs hover:bg-gray-100">Tutup</button>
                    )}
                  </div>
                  {detail.ai_transcript.length > 0 && (
                    <div className="mt-2">
                      <button onClick={() => setShowTranscript((s) => !s)} className="text-xs font-medium text-gray-600 underline">
                        {showTranscript ? "Sembunyikan" : "Tampilkan"} percakapan dengan asisten AI ({detail.ai_transcript.length} pesan)
                      </button>
                      {showTranscript && (
                        <div className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded border border-gray-200 bg-gray-50 p-2 text-xs">
                          {detail.ai_transcript.map((t, i) => (
                            <p key={i} className="whitespace-pre-wrap">
                              <b>{t.sender === "mahasiswa" ? "Mahasiswa" : "Asisten"}:</b> {t.content}
                              {t.escalated && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-800">dieskalasi</span>}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <SupportThread
                  messages={detail.messages}
                  viewer="staf"
                  closed={detail.status === "selesai"}
                  closedNote={`Ditutup ${detail.closed_at ? formatTime(detail.closed_at) : ""}${detail.assigned_staff_name ? ` · ${detail.assigned_staff_name}` : ""}.`}
                  placeholder="Tulis balasan untuk mahasiswa..."
                  onSend={reply}
                />
              </>
            )}
          </section>
        </div>
      </main>
    </AppShell>
  );
}
