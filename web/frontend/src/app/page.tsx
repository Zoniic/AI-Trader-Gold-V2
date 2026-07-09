import { requireSession } from "@/lib/dal";
import { Dashboard } from "@/components/Dashboard";

export default async function Home() {
  await requireSession();
  return <Dashboard />;
}
