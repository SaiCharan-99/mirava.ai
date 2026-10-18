/** Mockup-style toast (`.toast`), one at a time. */
let el: HTMLDivElement | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;

export function toast(msg: string): void {
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(timer);
  timer = setTimeout(() => el?.classList.remove("show"), 2600);
}
