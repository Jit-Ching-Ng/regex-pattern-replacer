import { useEffect } from "react";

/** A single toast. Success messages clear themselves; errors stay until dismissed. */
export default function Notice({ notice, onDismiss }) {
  useEffect(() => {
    if (notice?.kind !== "success") return undefined;
    const timer = window.setTimeout(onDismiss, 4500);
    return () => window.clearTimeout(timer);
  }, [notice, onDismiss]);

  return (
    <div className="notice-region" aria-live="polite">
      {notice && (
        <div key={notice.id} className={`notice notice--${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          <p>{notice.message}</p>
          <button type="button" className="notice__close" onClick={onDismiss} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
    </div>
  );
}
