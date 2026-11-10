"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { fetchMe, logout, User } from "@/lib/auth";

type Source = { number: number; title: string; page: number; url: string; score: number; snippet: string };
type Reply = { answer: string; sources: Source[]; escalate: boolean; reason?: string | null };
type Message = { role: "user" | "assistant"; text: string; reply?: Reply; ms?: number; firstMs?: number };

const EXAMPLES = [
  "Apa syarat mendaftar seminar proposal?",
  "Berapa poin TAK minimal untuk lulus S1?",
  "Bagaimana alur penundaan pembayaran BPP?",
];

export default function ChatPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchMe().then((me) => (me ? setUser(me) : router.replace("/login")));
  }, [router]);

  // Pakai blok: di Chromium terbaru scrollIntoView mengembalikan Promise, dan nilai kembalian
  // useEffect yang bukan fungsi membuat React gagal saat cleanup ("i is not a function").
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // Ubah pesan asisten terakhir (yang sedang ditulis).
  function updateLast(change: (m: Message) => Message) {
    setMessages((all) => [...all.slice(0, -1), change(all[all.length - 1])]);
  }

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", text: question }, { role: "assistant", text: "" }]);
    setInput("");
    setBusy(true);
    const started = performance.now();
    try {
      // Server-Sent Events lewat fetch (EventSource tidak mendukung POST).
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (res.status === 401) return router.replace("/login");
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? "Terjadi kesalahan.");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const event = /^event: (.*)$/m.exec(block)?.[1];
          const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "{}");
          if (event === "token") {
            updateLast((m) => ({ ...m, text: m.text + data.text, firstMs: m.firstMs ?? performance.now() - started }));
          } else if (event === "done") {
            // Teks final dari server: sama dengan yang di-stream, atau pesan eskalasi.
            updateLast((m) => ({ ...m, text: data.answer, reply: data, ms: performance.now() - started }));
          } else if (event === "error") {
            throw new Error(data.detail ?? "Terjadi kesalahan.");
          }
        }
      }
    } catch (e) {
      updateLast((m) => ({ ...m, text: (e as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-64 flex-col justify-between border-r border-gray-200 bg-white p-4 md:flex">
        <div className="space-y-4">
          <div className="text-sm font-semibold">Knowledge Management</div>
          <nav className="space-y-1 text-sm">
            <Link href="/" className="block rounded px-2 py-1 hover:bg-gray-100">Beranda</Link>
            <Link href="/chat" className="block rounded bg-gray-100 px-2 py-1 font-medium">Chat Asisten</Link>
          </nav>
        </div>
        <div className="space-y-3">
          <div className="text-sm">
            <div className="font-medium">{user.full_name}</div>
            <div className="text-gray-500">{user.role.name}</div>
          </div>
          <button
            onClick={async () => { await logout(); router.replace("/login"); }}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100"
          >
            Keluar
          </button>
        </div>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="border-b border-gray-200 bg-white px-4 py-3 md:px-8">
          <h1 className="text-lg font-semibold">Chat Asisten</h1>
          <p className="text-xs text-gray-500">
            Jawaban disusun dari dokumen resmi program studi dan kampus, beserta sumber dan halamannya.
          </p>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-6 md:px-8">
          {messages.length === 0 && (
            <div className="space-y-2">
              <p className="text-sm text-gray-500">Contoh pertanyaan:</p>
              {EXAMPLES.map((q) => (
                <button key={q} onClick={() => ask(q)} className="block rounded border border-gray-200 bg-white px-3 py-2 text-left text-sm hover:bg-gray-50">
                  {q}
                </button>
              ))}
            </div>
          )}
          {messages.filter((m) => m.role === "user" || m.text).map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-2xl rounded-lg px-4 py-3 text-sm ${m.role === "user" ? "bg-red-600 text-white" : "border border-gray-200 bg-white"}`}>
                <p className="whitespace-pre-wrap">{m.text}</p>
                {m.reply && m.reply.sources.length > 0 && (
                  <div className="mt-3 border-t border-gray-100 pt-2">
                    <p className="text-xs font-semibold text-gray-600">Sumber</p>
                    <ul className="mt-1 space-y-1">
                      {m.reply.sources.map((s) => (
                        <li key={s.number} className="text-xs text-gray-600">
                          [{s.number}] {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="underline">{s.title}</a> : s.title}, halaman {s.page}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {m.reply?.escalate && (
                  <button disabled className="mt-3 rounded border border-gray-300 px-3 py-1 text-xs text-gray-500" title="Livechat dikembangkan pada sprint berikutnya">
                    Hubungi Admin (segera hadir)
                  </button>
                )}
                {m.ms !== undefined && (
                  <p className="mt-2 text-[10px] text-gray-400">
                    {m.firstMs !== undefined && `mulai ${(m.firstMs / 1000).toFixed(1)} detik · `}selesai {(m.ms / 1000).toFixed(1)} detik
                  </p>
                )}
              </div>
            </div>
          ))}
          {busy && !messages[messages.length - 1]?.text && <p className="text-sm text-gray-500">Asisten sedang mencari jawaban...</p>}
          <div ref={bottom} />
        </div>

        <form onSubmit={onSubmit} className="flex gap-2 border-t border-gray-200 bg-white px-4 py-3 md:px-8">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Tulis pertanyaan tentang akademik atau administrasi..."
            className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
            maxLength={1000}
          />
          <button disabled={busy} className="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            Kirim
          </button>
        </form>
      </main>
    </div>
  );
}
