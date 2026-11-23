export type Role = { code: string; name: string };
export type User = { id: number; email: string; full_name: string; role: Role };

// Same-origin lewat Nginx, jadi cookie httpOnly ikut terkirim tanpa konfigurasi CORS.
async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, { credentials: "same-origin", ...init });
}

export async function fetchMe(): Promise<User | null> {
  const res = await request("/api/auth/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new Error("Gagal memuat sesi.");
  return res.json();
}

// Gagal diam-diam menjadi "mati": tombol SSO hanya perlu tampil bila server memastikan SSO aktif.
export async function fetchSsoEnabled(): Promise<boolean> {
  try {
    const res = await request("/api/auth/sso/status");
    if (!res.ok) return false;
    return (await res.json()).enabled === true;
  } catch {
    return false;
  }
}

export async function login(email: string, password: string): Promise<User> {
  const res = await request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (res.status === 401) throw new Error("Email atau kata sandi salah.");
  if (!res.ok) throw new Error("Terjadi kesalahan pada server. Coba lagi.");
  return res.json();
}

export async function logout(): Promise<void> {
  await request("/api/auth/logout", { method: "POST" });
}
