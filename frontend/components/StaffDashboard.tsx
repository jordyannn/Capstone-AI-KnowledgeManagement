"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, categoryLabel } from "@/lib/support";

type Stats = {
  days: number;
  questions: number;
  students: number;
  answered: number;
  escalated: number;
  escalated_pct: number;
  feedback_up: number;
  feedback_down: number;
  support_waiting: number;
  support_active: number;
  support_closed: number;
  support_livechat: number;
  support_ticket: number;
  first_reply_median_minutes: number | null;
  by_category: Record<string, number>;
  per_day: { date: string; questions: number; escalated: number }[];
};

function Card({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-0.5 text-xs text-gray-500">{note}</p>}
    </div>
  );
}

/** Ringkasan pemakaian untuk admin/staf (UC-07). Data dari percakapan mahasiswa saja. */
export default function StaffDashboard() {
  const [days, setDays] = useState(30);
  const [s, setS] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Stats>(`/api/admin/stats?days=${days}`).then(setS).catch((e) => setError((e as Error).message));
  }, [days]);

  if (error) return <p className="mt-6 text-sm text-red-700">{error}</p>;
  if (!s) return <p className="mt-6 text-sm text-gray-500">Memuat ringkasan...</p>;

  const max = Math.max(1, ...s.per_day.map((d) => d.questions));
  const minutes = s.first_reply_median_minutes;

  return (
    <section className="mt-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Ringkasan pemakaian</h2>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-gray-300 bg-white px-2 py-1 text-sm">
          <option value={7}>7 hari terakhir</option>
          <option value={30}>30 hari terakhir</option>
          <option value={90}>90 hari terakhir</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card label="Pertanyaan ke asisten" value={s.questions} note={`dari ${s.students} mahasiswa`} />
        <Card label="Dieskalasi" value={`${s.escalated_pct}%`} note={`${s.escalated} dari ${s.answered + s.escalated} jawaban`} />
        <Card
          label="Bantuan staf terbuka"
          value={s.support_waiting + s.support_active}
          note={`${s.support_waiting} menunggu · ${s.support_closed} selesai`}
        />
        <Card
          label="Balasan staf pertama"
          value={minutes === null ? "-" : minutes < 60 ? `${minutes} mnt` : `${(minutes / 60).toFixed(1)} jam`}
          note={`median · ${s.support_livechat} livechat, ${s.support_ticket} tiket`}
        />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-600">Pertanyaan per hari (merah = dieskalasi)</p>
          {s.per_day.length === 0 && <p className="mt-2 text-sm text-gray-400">Belum ada data.</p>}
          <ul className="mt-2 space-y-1">
            {s.per_day.slice(-14).map((d) => (
              <li key={d.date} className="flex items-center gap-2 text-xs">
                <span className="w-16 shrink-0 text-gray-500">{new Date(d.date).toLocaleDateString("id-ID", { day: "numeric", month: "short" })}</span>
                <span className="flex h-3 flex-1 overflow-hidden rounded bg-gray-100">
                  <span className="bg-gray-700" style={{ width: `${(100 * (d.questions - d.escalated)) / max}%` }} />
                  <span className="bg-red-500" style={{ width: `${(100 * d.escalated) / max}%` }} />
                </span>
                <span className="w-6 text-right tabular-nums">{d.questions}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-600">Kategori bantuan staf</p>
          {Object.keys(s.by_category).length === 0 && <p className="mt-2 text-sm text-gray-400">Belum ada permintaan bantuan.</p>}
          <ul className="mt-2 space-y-1 text-sm">
            {Object.entries(s.by_category).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span>{categoryLabel(k)}</span><span className="tabular-nums">{v}</span></li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-gray-500">
            Umpan balik jawaban: 👍 {s.feedback_up} · 👎 {s.feedback_down}
          </p>
          <Link href="/admin" className="mt-3 inline-block text-xs underline">Buka antrean bantuan</Link>
        </div>
      </div>
      <p className="text-xs text-gray-400">Dihitung dari percakapan mahasiswa saja; uji coba oleh akun admin/staf tidak ikut dihitung.</p>
    </section>
  );
}
