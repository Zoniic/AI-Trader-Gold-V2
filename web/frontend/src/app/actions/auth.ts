"use server";

import { createHash, timingSafeEqual } from "crypto";
import { redirect } from "next/navigation";
import { createSession, deleteSession } from "@/lib/session";

export type LoginState = { error?: string } | undefined;

function passwordMatches(input: string, expected: string): boolean {
  const inputHash = createHash("sha256").update(input).digest();
  const expectedHash = createHash("sha256").update(expected).digest();
  return timingSafeEqual(inputHash, expectedHash);
}

export async function login(
  _prevState: LoginState,
  formData: FormData
): Promise<LoginState> {
  const password = String(formData.get("password") ?? "").trim();
  const expected = process.env.DASHBOARD_PASSWORD?.trim();

  if (!expected) {
    return { error: "เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า DASHBOARD_PASSWORD" };
  }

  if (!password || !passwordMatches(password, expected)) {
    return { error: "รหัสผ่านไม่ถูกต้อง" };
  }

  await createSession();
  redirect("/");
}

export async function logout(): Promise<void> {
  await deleteSession();
  redirect("/login");
}
