"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { fetchMe, fetchSsoEnabled, login } from "@/lib/auth";

// Kode `?error=` dari alur SSO. Yang ditampilkan hanya teks di sini, tidak pernah teks dari URL,
// sehingga tautan buatan orang lain tidak bisa memunculkan pesan sembarang di halaman ini.
const SSO_ERRORS: Record<string, string> = {
  dibatalkan: "Login dengan akun Telkom University dibatalkan.",
  sesi_kedaluwarsa: "Sesi login kedaluwarsa. Silakan coba lagi.",
  akun_tidak_diizinkan:
    "Akun ini tidak diizinkan. Gunakan akun Telkom University (@telkomuniversity.ac.id atau @student.telkomuniversity.ac.id).",
  belum_terdaftar: "Akun belum terdaftar, hubungi admin prodi.",
  akun_nonaktif: "Akun Anda dinonaktifkan. Hubungi admin prodi.",
  gagal: "Login dengan akun Telkom University gagal. Coba lagi, atau masuk dengan email dan kata sandi.",
};

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    // Sudah punya sesi aktif: tidak perlu login lagi.
    fetchMe()
      .then((user) => user && router.replace("/"))
      .catch(() => {});
    fetchSsoEnabled().then(setSsoEnabled);

    const code = new URLSearchParams(window.location.search).get("error");
    if (code) {
      setError(SSO_ERRORS[code] ?? SSO_ERRORS.gagal);
      window.history.replaceState(null, "", "/login"); // muat ulang halaman tidak menampilkan error lagi
    }
  }, [router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Terjadi kesalahan.");
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-gray-200 bg-white p-8 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold">Masuk</h1>
          <p className="mt-1 text-sm text-gray-500">AI Knowledge Management System</p>
        </div>

        {error && (
          <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        {ssoEnabled && (
          <>
            {/* Tautan biasa, bukan fetch: alur OIDC memakai redirect browser penuh ke Microsoft. */}
            <a
              href="/api/auth/sso/login"
              className="block w-full rounded border border-gray-300 bg-white px-4 py-2 text-center text-sm font-medium hover:bg-gray-50"
            >
              Masuk dengan akun Telkom University
            </a>
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span className="h-px flex-1 bg-gray-200" />
              atau
              <span className="h-px flex-1 bg-gray-200" />
            </div>
          </>
        )}

        <label className="block text-sm font-medium">
          Email
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-red-600 focus:outline-none"
          />
        </label>

        <label className="block text-sm font-medium">
          Kata sandi
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-red-600 focus:outline-none"
          />
        </label>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-60"
        >
          {submitting ? "Memproses..." : "Masuk"}
        </button>
      </form>
    </main>
  );
}
