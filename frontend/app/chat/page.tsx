"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { fetchMe, User } from "@/lib/auth";

type Source = { number: number; title: string; page: number; url: string; score: number; snippet: string };
type Reply = {
  answer: string;
  sources: Source[];
  escalate: boolean;
  reason?: string | null;
  conversation_id?: string;
  message_id?: string;
};
type Message = { role: "user" | "assistant"; text: string; reply?: Reply; ms?: number; firstMs?: number };
type ConversationSummary = { id: string; title: string; updated_at: string };
type StoredMessage = {
  id: string;
  sender: "mahasiswa" | "asisten";
  content: string;
  sources: Source[];
  escalated: boolean;
  reason: string | null;
};

const EXAMPLES = [
  "Apa syarat mendaftar sidang tugas akhir?",
  "Berapa poin TAK minimal untuk lulus S1?",
  "Bagaimana cara mengajukan cuti akademik?",
];

function fromStored(m: StoredMessage): Message {
  if (m.sender === "mahasiswa") return { role: "user", text: m.content };
  return {
    role: "assistant",
    text: m.content,
    reply: { answer: m.content, sources: m.sources, escalate: m.escalated, reason: m.reason, message_id: m.id },
  };
}

export default function ChatPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async () => {
    const res = await fetch("/api/chat/conversations", { credentials: "same-origin" });
    if (res.ok) setHistory(await res.json());
  }, []);

  useEffect(() => {
    fetchMe().then((me) => (me ? setUser(me) : router.replace("/login")));
    loadHistory();
  }, [router, loadHistory]);

  // Pakai blok: di Chromium terbaru scrollIntoView mengembalikan Promise, dan nilai kembalian
  // useEffect yang bukan fungsi membuat React gagal saat cleanup ("i is not a function").
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function openConversation(id: string) {
    if (busy) return;
    const res = await fetch(`/api/chat/conversations/${id}`, { credentials: "same-origin" });
    if (res.status === 401) return router.replace("/login");
    if (!res.ok) return;
    const data = await res.json();
    setConversationId(id);
    setMessages((data.messages as StoredMessage[]).map(fromStored));
  }

  function newConversation() {
    if (busy) return;
    setConversationId(null);
    setMessages([]);
  }

  async function deleteConversation(id: string) {
    if (busy || !confirm("Hapus percakapan ini dari riwayat?")) return;
    const res = await fetch(`/api/chat/conversations/${id}`, { method: "DELETE", credentials: "same-origin" });
    if (res.ok || res.status === 404) {
      if (id === conversationId) newConversation();
      loadHistory();
    }
  }

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
        body: JSON.stringify({ question, conversation_id: conversationId }),
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
            if (data.conversation_id) setConversationId(data.conversation_id);
          } else if (event === "error") {
            throw new Error(data.detail ?? "Terjadi kesalahan.");
          }
        }
      }
    } catch (e) {
      updateLast((m) => ({ ...m, text: (e as Error).message }));
    } finally {
      setBusy(false);
      loadHistory();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  const historyPanel = (close: () => void) => (
    <div className="space-y-2 border-t border-gray-100 pt-4">
      <button
        onClick={() => { newConversation(); close(); }}
        className="w-full rounded border border-gray-300 px-3 py-1.5 text-left text-sm hover:bg-gray-100"
      >
        + Percakapan baru
      </button>
      <p className="px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">Riwayat</p>
      {history.length === 0 && <p className="px-2 text-xs text-gray-400">Belum ada percakapan.</p>}
      <ul className="space-y-0.5">
        {history.map((c) => (
          <li key={c.id} className="group flex items-center gap-1">
            <button
              onClick={() => { openConversation(c.id); close(); }}
              title={c.title}
              className={`min-w-0 flex-1 truncate rounded px-2 py-1 text-left text-sm ${c.id === conversationId ? "bg-gray-100 font-medium" : "hover:bg-gray-100"}`}
            >
              {c.title}
            </button>
            <button
              onClick={() => deleteConversation(c.id)}
              aria-label={`Hapus percakapan ${c.title}`}
              className="shrink-0 rounded px-1 text-xs text-gray-400 hover:bg-gray-100 hover:text-red-600 md:opacity-0 md:group-hover:opacity-100"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <AppShell user={user} active="chat" sidebarExtra={historyPanel}>
      <main className="flex min-h-0 flex-1 flex-col">
        <header className="border-b border-gray-200 bg-white px-4 py-3 md:px-8">
          <h1 className="text-lg font-semibold">Chat Asisten</h1>
          <p className="text-xs text-gray-500">
            Jawaban disusun dari dokumen resmi program studi dan kampus, beserta sumber dan halamannya.
          </p>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 md:px-8">
          {messages.length === 0 && (
            <div className="space-y-2">
              <p className="text-sm text-gray-500">Contoh pertanyaan:</p>
              {EXAMPLES.map((q) => (
                <button key={q} onClick={() => ask(q)} className="block w-full rounded border border-gray-200 bg-white px-3 py-2 text-left text-sm hover:bg-gray-50 sm:w-auto">
                  {q}
                </button>
              ))}
            </div>
          )}
          {messages.filter((m) => m.role === "user" || m.text).map((m, i) => (
            <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[90%] break-words rounded-lg px-4 py-3 text-sm md:max-w-2xl ${m.role === "user" ? "bg-red-600 text-white" : "border border-gray-200 bg-white"}`}>
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
            className="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
            maxLength={1000}
          />
          <button disabled={busy} className="shrink-0 rounded bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            Kirim
          </button>
        </form>
      </main>
    </AppShell>
  );
}
