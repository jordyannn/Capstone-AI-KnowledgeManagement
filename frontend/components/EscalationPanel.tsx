"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, CATEGORIES, RequestDetail } from "@/lib/support";

type Props = {
  question: string;
  answer: string;
  conversationId: string | null;
  onCancel: () => void;
};

/**
 * Muncul di bawah jawaban asisten yang dieskalasi. Bila ada staf online, mahasiswa memulai livechat.
 * Bila tidak, form yang sama dikirim sebagai tiket dan menunggu di antrean.
 * Isi awal: pertanyaan mahasiswa dan jawaban asisten terakhir, supaya staf tidak perlu bertanya ulang.
 */
export default function EscalationPanel({ question, answer, conversationId, onCancel }: Props) {
  const router = useRouter();
  const [online, setOnline] = useState<boolean | null>(null);
  const [category, setCategory] = useState("");
  const [message, setMessage] = useState(`${question}\n\nJawaban asisten: ${answer}`);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ staff_online: boolean }>("/api/support/status")
      .then((s) => setOnline(s.staff_online))
      .catch(() => setOnline(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!category) return setError("Pilih kategori terlebih dahulu.");
    setSending(true);
    setError(null);
    try {
      const req = await api<RequestDetail>("/api/support/requests", {
        method: "POST",
        body: JSON.stringify({ category, message, conversation_id: conversationId }),
      });
      router.push(`/bantuan?id=${req.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSending(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 space-y-3 rounded border border-gray-200 bg-gray-50 p-3 text-gray-800">
      {online === null ? (
        <p className="text-xs text-gray-500">Memeriksa ketersediaan staf...</p>
      ) : online ? (
        <p className="text-xs">
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />
          Staf sedang online. Pesan Anda dibuka sebagai <b>livechat</b>.
        </p>
      ) : (
        <p className="text-xs">
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-gray-400" />
          Tidak ada staf yang online. Pesan Anda dikirim sebagai <b>tiket</b> dan dibalas saat staf tersedia
          (jam kerja). Balasan dapat dilihat di menu <b>Bantuan Staf</b>.
        </p>
      )}
      <label className="block text-xs font-medium">
        Kategori
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="mt-1 block w-full rounded border border-gray-300 bg-white px-2 py-1.5 text-sm font-normal"
        >
          <option value="">Pilih kategori...</option>
          {CATEGORIES.map((c) => (
            <option key={c.code} value={c.code}>{c.label}</option>
          ))}
        </select>
      </label>
      <label className="block text-xs font-medium">
        Pesan untuk staf (boleh diubah)
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={5}
          maxLength={4000}
          className="mt-1 block w-full rounded border border-gray-300 bg-white px-2 py-1.5 text-sm font-normal"
        />
      </label>
      {error && <p className="text-xs text-red-700">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button disabled={sending || online === null || message.trim().length < 2} className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
          {online ? "Mulai livechat" : "Kirim tiket"}
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-gray-300 bg-white px-3 py-1.5 text-xs">
          Batal
        </button>
      </div>
    </form>
  );
}
