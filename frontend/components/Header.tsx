import Link from "next/link";

export function Header() {
  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-black/10 dark:border-white/10 text-sm">
      <Link href="/" className="font-semibold hover:underline">
        Block Chat
      </Link>
      <nav className="flex gap-4 text-xs">
        <Link href="/" className="text-zinc-600 dark:text-zinc-400 hover:underline">
          Compose
        </Link>
        <Link
          href="/apps"
          className="text-zinc-600 dark:text-zinc-400 hover:underline"
        >
          Saved mini-apps
        </Link>
      </nav>
    </header>
  );
}
