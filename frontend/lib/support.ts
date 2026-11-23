// Eskalasi ke staf (F-10): livechat bila ada staf online, tiket bila tidak.

export type SupportStatus = "menunggu" | "aktif" | "selesai";
export type SupportKind = "livechat" | "tiket";

export type SupportMessage = {
  id: string;
  sender_role: "mahasiswa" | "staf";
  sender_name: string;
  content: string;
  created_at: string;
};

export type RequestSummary = {
  id: string;
  kind: SupportKind;
  category: string;
  subject: string;
  status: SupportStatus;
  created_at: string;
  updated_at: string;
  last_message: string | null;
  last_sender_role: "mahasiswa" | "staf" | null;
};

export type StudentInfo = { id: number; full_name: string; email: string };

export type RequestDetail = RequestSummary & {
  conversation_id: string | null;
  closed_at: string | null;
  assigned_staff_name: string | null;
  staff_online: boolean;
  messages: SupportMessage[];
};

export type AdminRequestSummary = RequestSummary & { student: StudentInfo; assigned_staff_name: string | null };
export type TranscriptMessage = { sender: "mahasiswa" | "asisten"; content: string; escalated: boolean; created_at: string };
export type AdminRequestDetail = RequestDetail & { student: StudentInfo; ai_transcript: TranscriptMessage[] };

export const CATEGORIES: { code: string; label: string }[] = [
  { code: "akademik", label: "Akademik (perkuliahan, nilai, kalender)" },
  { code: "tugas_akhir_kppm", label: "Tugas Akhir / KPPM" },
  { code: "administrasi", label: "Administrasi (surat, cuti, registrasi)" },
  { code: "keuangan", label: "Keuangan (BPP, beasiswa)" },
  { code: "lainnya", label: "Lainnya" },
];

export const categoryLabel = (code: string) => CATEGORIES.find((c) => c.code === code)?.label.split(" (")[0] ?? code;

export const STATUS_LABEL: Record<SupportStatus, string> = {
  menunggu: "Menunggu staf",
  aktif: "Dibalas staf",
  selesai: "Selesai",
};

export const STATUS_STYLE: Record<SupportStatus, string> = {
  menunggu: "bg-amber-100 text-amber-800",
  aktif: "bg-green-100 text-green-800",
  selesai: "bg-gray-100 text-gray-600",
};

/** Interval polling (ms). Target NFR: pesan livechat tampil < 2 detik di sisi penerima. */
export const POLL_MS = 1500;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : "Terjadi kesalahan. Coba lagi.";
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const formatTime = (iso: string) =>
  new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString("id-ID", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
