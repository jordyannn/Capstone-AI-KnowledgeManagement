"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { formatTime, SupportMessage } from "@/lib/support";

type Props = {
  messages: SupportMessage[];
  /** Peran yang sedang melihat: pesannya tampil di kanan. */
  viewer: "mahasiswa" | "staf";
  closed: boolean;
  closedNote?: string;
  placeholder?: string;
  onSend: (text: string) => Promise<void>;
};

/** Daftar pesan livechat/tiket + kotak balasan. Dipakai halaman mahasiswa (/bantuan) dan admin (/admin). */
export default function SupportThread({ messages, viewer, closed, closedNote, placeholder, onSend }: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || sending) return;
    setSending(true);
    setError(null);
    try {
      await onSend(text.trim());
      setText("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 md:px-6">
        {messages.map((m) => {
          const mine = m.sender_role === viewer;
          return (
            <div key={m.id} className={mine ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[90%] break-words rounded-lg px-4 py-2 text-sm md:max-w-xl ${mine ? "bg-red-600 text-white" : "border border-gray-200 bg-white"}`}>
                <p className={`text-[11px] ${mine ? "text-red-100" : "text-gray-500"}`}>
                  {m.sender_name}
                  {m.sender_role === "staf" && " · Staf"} · {formatTime(m.created_at)}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{m.content}</p>
              </div>
            </div>
          );
        })}
        <div ref={bottom} />
      </div>
      {closed ? (
        <p className="border-t border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500 md:px-6">
          {closedNote ?? "Percakapan ini sudah ditutup."}
        </p>
      ) : (
        <form onSubmit={submit} className="border-t border-gray-200 bg-white px-4 py-3 md:px-6">
          {error && <p className="mb-2 text-xs text-red-700">{error}</p>}
          <div className="flex gap-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) submit(e);
              }}
              rows={2}
              maxLength={4000}
              placeholder={placeholder ?? "Tulis pesan... (Enter untuk kirim, Shift+Enter baris baru)"}
              className="min-w-0 flex-1 resize-none rounded border border-gray-300 px-3 py-2 text-sm"
            />
            <button disabled={sending || !text.trim()} className="shrink-0 self-end rounded bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              Kirim
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
