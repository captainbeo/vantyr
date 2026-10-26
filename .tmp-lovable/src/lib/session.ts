// Frontend-only session stub. Replace signIn/signOut with calls to the Vantyr backend.
const KEY = "vantyr_session";

export type Session = { email: string };

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "null");
  } catch {
    return null;
  }
}

export async function signIn(email: string, _password: string): Promise<Session> {
  // TODO: POST to your backend's login endpoint and store its token instead.
  const s = { email };
  localStorage.setItem(KEY, JSON.stringify(s));
  return s;
}

export function signOut() {
  localStorage.removeItem(KEY);
}
