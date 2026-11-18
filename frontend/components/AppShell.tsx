"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ReactNode, useState } from "react";
import { logout, User } from "@/lib/auth";

type Props = {
  user: User;
  active: "home" | "chat" | "bantuan" | "admin";
  /** Isi tambahan di bawah menu, mis. daftar riwayat percakapan. Menerima fungsi penutup drawer ponsel. */
  sidebarExtra?: (close: () => void) => ReactNode;
  children: ReactNode;
};

const STAFF_ROLES = ["admin", "staf"];
export const isStaff = (user: User) => STAFF_ROLES.includes(user.role.code);

function navFor(user: User) {
  const nav = [
    { key: "home", href: "/", label: "Beranda" },
    { key: "chat", href: "/chat", label: "Chat Asisten" },
    { key: "bantuan", href: "/bantuan", label: "Bantuan Staf" },
  ];
  // Staf melayani antrean; menu "Bantuan Staf" (permintaan milik sendiri) tidak relevan bagi mereka.
  return isStaff(user) ? [...nav.slice(0, 2), { key: "admin", href: "/admin", label: "Antrean Bantuan" }] : nav;
}

/**
 * Kerangka halaman: sidebar tetap di layar lebar (md ke atas), dan bilah atas + menu geser di ponsel
 * (NFR kegunaan: dapat dipakai di lebar 360 px tanpa gulir horizontal).
 */
export default function AppShell({ user, active, sidebarExtra, children }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  const sidebar = (
    <div className="flex h-full flex-col justify-between gap-4">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        <div className="text-sm font-semibold">Knowledge Management</div>
        <nav className="space-y-1 text-sm">
          {navFor(user).map((n) => (
            <Link
              key={n.key}
              href={n.href}
              onClick={close}
              className={`block rounded px-2 py-1 ${active === n.key ? "bg-gray-100 font-medium" : "hover:bg-gray-100"}`}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        {sidebarExtra?.(close)}
      </div>
      <div className="space-y-3">
        <div className="text-sm">
          <div className="truncate font-medium">{user.full_name}</div>
          <div className="text-gray-500">{user.role.name}</div>
        </div>
        <button
          onClick={async () => { await logout(); router.replace("/login"); }}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100"
        >
          Keluar
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-64 shrink-0 border-r border-gray-200 bg-white p-4 md:block">{sidebar}</aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button aria-label="Tutup menu" className="absolute inset-0 bg-black/30" onClick={close} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-white p-4 shadow-xl">{sidebar}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2 md:hidden">
          <button
            aria-label="Buka menu"
            onClick={() => setOpen(true)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            ☰
          </button>
          <span className="truncate text-sm font-semibold">Knowledge Management</span>
        </div>
        {children}
      </div>
    </div>
  );
}
