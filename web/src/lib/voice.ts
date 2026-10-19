import { useEffect, useRef } from "react";
import type { Alert } from "../api/types";

const KEY = "d2bg.voice";

export function voiceUnlocked(): boolean {
  try {
    return localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

export function setVoice(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // private window: the choice lasts for this page only
  }
  if (on && "speechSynthesis" in window) {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance("Voice on"));
  }
}

/** Speaks each new alert's short line once, if he switched voice on (browsers need a click first). */
export function useSpeakAlerts(alerts: Alert[] | undefined, enabled: boolean): void {
  const spoken = useRef<number>(0);
  useEffect(() => {
    if (!alerts?.length) return;
    const newest = Math.max(...alerts.map((a) => a.id));
    if (spoken.current === 0) {
      spoken.current = newest; // never read out a backlog when the page opens
      return;
    }
    if (!enabled || !("speechSynthesis" in window) || !voiceUnlocked()) {
      spoken.current = newest;
      return;
    }
    for (const a of [...alerts].reverse()) {
      if (a.id > spoken.current && a.speak) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(a.speak));
      }
    }
    spoken.current = newest;
  }, [alerts, enabled]);
}
