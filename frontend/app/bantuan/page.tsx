"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import SupportThread from "@/components/SupportThread";
import { fetchMe, User } from "@/lib/auth";
import {
  api,
  ApiError,
  categoryLabel,
  formatTime,
  POLL_MS,
  RequestDetail,
  RequestSummary,
  STATUS_LABEL,
  STATUS_STYLE,
} from "@/lib/support";

/** Halaman mahasiswa: daftar livechat/tiket milik sendiri dan percakapannya dengan staf. */
export default function BantuanPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [list, setList] = useState<RequestSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    try {
      setList(await api<RequestSummary[]>("/api/support/requests"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
    }
  }, [router]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api<RequestDetail>(`/api/support/requests/${id}`));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return router.replace("/login");
      setError((e as Error).message);
    }
  }, [router]);

  useEffect(() => {
    fetchMe().then((me) => (me ? setUser(me) : router.replace("/login")));
    loadList();
    // Dibuka dari chat: /bantuan?id=...
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) setSelected(id);
  }, [router, loadList]);

  // Polling: percakapan terbuka tiap POLL_MS, daftar tiap 10 detik.
  useEffect(() => {
    if (!selected) return;
    loadDetail(selected);
    const t = setInterval(() => loadDetail(selected), POLL_MS);
    return () => clearInterval(t);
  }, [selected, loadDetail]);

  useEffect(() => {
    const t = setInterval(loadList, 10_000);
    return () => clearInterval(t);
  }, [loadList]);

  function open(id: string) {
    setDetail(null);
    setSelected(id);
    window.history.replaceState(null, "", `/bantuan?id=${id}`);
  }

  async function send(text: string) {
    if (!selected) return;
    setDetail(await api<RequestDetail>(`/api/support/requests/${selected}/messages`, { method: "POST", body: JSON.stringify({ content: text }) }));
    loadList();
  }

  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <AppShell user={user} active="bantuan">
      <main className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className={`${selected ? "hidden md:flex" : "flex"} min-h-0 flex-col border-gray-200 bg-white md:w-80 md:shrink-0 md:border-r`}>
          <header className="border-b border-gray-200 px-4 py-3">
            <h1 className="text-lg font-semibold">Bantuan Staf</h1>
            <p className="text-xs text-gray-500">Livechat dan tiket Anda. Untuk membuat yang baru, gunakan tombol &quot;Hubungi Admin&quot; di Chat Asisten.</p>
          </header>
          <ul className="min-h-0 flex-1 divide-y divide-gray-100 overflow-y-auto">
            {list.length === 0 && (
              <li className="px-4 py-6 text-sm text-gray-500">
                Belum ada permintaan bantuan. <Link href="/chat" className="underline">Tanya asisten dulu</Link>.
              </li>
            )}
            {list.map((r) => (
              <li key={r.id}>
                <button onClick={() => open(r.id)} className={`block w-full px-4 py-3 text-left hover:bg-gray-50 ${r.id === selected ? "bg-gray-100" : ""}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{r.subject}</span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {r.kind === "livechat" ? "Livechat" : "Tiket"} · {categoryLabel(r.category)} · {formatTime(r.updated_at)}
                  </p>
                  {r.last_sender_role === "staf" && r.status !== "selesai" && <p className="mt-0.5 text-xs font-medium text-green-700">Ada balasan staf</p>}
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className={`${selected ? "flex" : "hidden md:flex"} min-h-0 min-w-0 flex-1 flex-col`}>
          {!selected && <p className="m-auto text-sm text-gray-400">Pilih percakapan di sebelah kiri.</p>}
          {selected && error && <p className="p-4 text-sm text-red-700">{error}</p>}
          {selected && !detail && !error && <p className="p-4 text-sm text-gray-500">Memuat...</p>}
          {detail && (
            <>
              <header className="border-b border-gray-200 bg-white px-4 py-3 md:px-6">
                <button onClick={() => setSelected(null)} className="mb-1 text-xs text-gray-500 underline md:hidden">← Kembali</button>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="min-w-0 truncate font-semibold">{detail.subject}</h2>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[detail.status]}`}>{STATUS_LABEL[detail.status]}</span>
                </div>
                <p className="text-xs text-gray-500">
                  {detail.kind === "livechat" ? "Livechat" : "Tiket"} · {categoryLabel(detail.category)}
                  {detail.assigned_staff_name && ` · ditangani ${detail.assigned_staff_name}`}
                  {detail.status !== "selesai" && (detail.staff_online ? " · staf online" : " · staf sedang offline, pesan menunggu di antrean")}
                </p>
              </header>
              <SupportThread
                messages={detail.messages}
                viewer="mahasiswa"
                closed={detail.status === "selesai"}
                closedNote="Percakapan ini sudah ditutup oleh staf. Bila masih ada pertanyaan, tanyakan lagi di Chat Asisten."
                onSend={send}
              />
            </>
          )}
        </section>
      </main>
    </AppShell>
  );
}
