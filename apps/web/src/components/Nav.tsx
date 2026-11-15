"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  ["/inbox", "Job inbox"], ["/pipeline", "Pipeline"], ["/messages", "Messages"], ["/runs", "Agent runs"],
  ["/analytics", "Analytics"], ["/settings", "Settings"],
] as const;

export default function Nav() {
  const path = usePathname() || "";
  if (path.startsWith("/login")) return null;
  return (
    <nav className="side" aria-label="Main">
      <div className="logo">GigBid</div>
      {LINKS.map(([href, label]) => (
        <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined}>{label}</Link>
      ))}
    </nav>
  );
}
