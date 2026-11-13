"use client";

import { useEffect, useState } from "react";

/** Seconds since `running` turned true, ticking once a second; 0 when it is not running. */
export function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [running]);
  return seconds;
}
