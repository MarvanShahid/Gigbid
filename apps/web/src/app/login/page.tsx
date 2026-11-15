"use client";
import { useState } from "react";
import { api, errorText, TOKEN_KEY } from "@/lib/client";
import { ErrorBox } from "@/components/States";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    const res = mode === "login"
      ? await api.POST("/api/auth/login", { body: { email, password } })
      : await api.POST("/api/auth/register", { body: { email, password, name } });
    setBusy(false);
    if (res.error || !res.data) return setErr(errorText(res.error) || "sign-in failed");
    localStorage.setItem(TOKEN_KEY, res.data.token);
    location.href = mode === "register" ? "/onboarding" : "/inbox";
  }
  return (
    <div className="panel" style={{ maxWidth: 420, margin: "60px auto" }}>
      <h1>GigBid</h1>
      <p className="muted">Finds jobs worth your Connects, writes proposals grounded in your portfolio, and never
        sends anything without your approval.</p>
      <ErrorBox msg={err} />
      <form onSubmit={submit}>
        {mode === "register" && (<><label htmlFor="name">Name</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%" }} /></>)}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: "100%" }} />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" required minLength={8} value={password}
          onChange={(e) => setPassword(e.target.value)} style={{ width: "100%" }} />
        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" type="submit" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
          <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create an account" : "I have an account"}
          </button>
        </div>
      </form>
    </div>
  );
}
