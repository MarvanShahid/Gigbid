"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/client";

/** Shows "marketplace unavailable" whenever the marketplace MCP server is down; work is queued meanwhile. */
export default function DegradedBanner() {
  const [down, setDown] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    const check = async () => {
      const { data } = await api.GET("/api/status");
      if (alive && data) setDown(data.degraded);
    };
    check();
    const id = setInterval(check, 8000);
    const onDeg = () => check();
    window.addEventListener("gigbid:degraded", onDeg);
    return () => { alive = false; clearInterval(id); window.removeEventListener("gigbid:degraded", onDeg); };
  }, []);
  if (!down.length) return null;
  return (
    <div className="banner bad" role="alert" data-testid="degraded-banner">
      <strong>Marketplace unavailable.</strong> {down.join(", ")} is not responding. New work is queued and will
      resume automatically; nothing is lost and nothing is sent twice.
    </div>
  );
}
