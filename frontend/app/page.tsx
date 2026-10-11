"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchMe, logout, User } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe()
      .then((me) => (me ? setUser(me) : router.replace("/login")))
      .catch(() => setError("Gagal memuat sesi. Muat ulang halaman."));
  }, [router]);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  if (error) return <p className="p-8 text-sm text-red-700">{error}</p>;
  if (!user) return <p className="p-8 text-sm text-gray-500">Memuat...</p>;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-64 flex-col justify-between border-r border-gray-200 bg-white p-4">
        <div className="text-sm font-semibold">Knowledge Management</div>
        <div className="space-y-3">
          <div className="text-sm">
            <div className="font-medium">{user.full_name}</div>
            <div className="text-gray-500">{user.role.name}</div>
          </div>
          <button
            onClick={onLogout}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100"
          >
            Keluar
          </button>
        </div>
      </aside>
      <main className="flex-1 p-8">
        <h1 className="text-xl font-semibold">Beranda</h1>
        <p className="mt-2 text-sm text-gray-500">
          Anda masuk sebagai {user.role.name}.
        </p>
      </main>
    </div>
  );
}
