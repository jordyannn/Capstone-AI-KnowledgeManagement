"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { fetchMe, User } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe()
      .then((me) => (me ? setUser(me) : router.replace("/login")))
      .catch(() => setError("Gagal memuat sesi. Muat ulang halaman."));
  }, [router]);

  if (error) return <p className="p-8 text-sm text-red-700">{error}</p>;
  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <AppShell user={user} active="home">
      <main className="flex-1 overflow-y-auto p-4 md:p-8">
        <h1 className="text-xl font-semibold">Beranda</h1>
        <p className="mt-2 text-sm text-gray-500">Anda masuk sebagai {user.role.name}.</p>
        <Link href="/chat" className="mt-6 inline-block rounded bg-red-600 px-4 py-2 text-sm font-medium text-white">
          Buka Chat Asisten
        </Link>
      </main>
    </AppShell>
  );
}
