/** Visual-test mode (?visualTest=1, INTERFACES §6.4): fixtures, frozen clock, no animations. */
export const isVisualTest: boolean =
  typeof window !== "undefined" && new URLSearchParams(window.location.search).has("visualTest");

/** Freeze CSS animations/transitions exactly like the mockup's freeze mode. */
export function applyFreeze(): void {
  if (!isVisualTest) return;
  const st = document.createElement("style");
  st.textContent = "*{animation:none!important;transition:none!important}";
  document.head.appendChild(st);
}

/** Append the visualTest query to internal links so navigation stays in fixture mode. */
export function withMode(path: string): string {
  return isVisualTest ? `${path}${path.includes("?") ? "&" : "?"}visualTest=1` : path;
}
