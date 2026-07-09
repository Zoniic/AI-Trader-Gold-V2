import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import { decrypt, getSessionCookieValue } from "@/lib/session";

export const verifySession = cache(async (): Promise<boolean> => {
  const token = await getSessionCookieValue();
  return decrypt(token);
});

export async function requireSession(): Promise<void> {
  const authenticated = await verifySession();
  if (!authenticated) {
    redirect("/login");
  }
}
