import { useRouter } from "next/router";
import Link from "next/link";
import { SignalsSidebar } from "@/components/dashboard/SignalsSidebar";

export default function FilmRoom() {
  const router = useRouter();
  const taskType = String(router.query.task_type || "all");

  return (
    <main className="min-h-screen bg-slate-950 p-6 pr-80 text-slate-100">
      <nav className="mb-4 flex gap-4">
        <Link href="/dashboard">Dashboard</Link>
        <Link href="/film-room">Film Room</Link>
      </nav>
      <h1 className="mb-2 text-2xl">Film Room</h1>
      <p className="text-sm text-slate-400">Prefilter: {taskType}</p>
      <SignalsSidebar />
    </main>
  );
}
