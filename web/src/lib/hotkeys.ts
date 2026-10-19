import { useEffect } from "react";

/** Page-level shortcuts. Ignored while typing in a field; nothing here reaches outside the browser tab. */
export function useHotkeys(map: Record<string, (e: KeyboardEvent) => void>): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (typing && e.key !== "Escape") return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const fn = map[e.key];
      if (fn) {
        e.preventDefault();
        fn(e);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [map]);
}
