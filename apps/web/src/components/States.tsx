export const Loading = ({ what = "Loading" }: { what?: string }) => (
  <p className="muted" role="status"><span className="spinner" /> {what}…</p>
);
export const Empty = ({ children }: { children: React.ReactNode }) => <div className="empty">{children}</div>;
export const ErrorBox = ({ msg }: { msg: string }) => (msg ? <div className="banner bad" role="alert">{msg}</div> : null);
