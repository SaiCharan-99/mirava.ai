import raw from "./pollPresets.json";
import { MAX_OPTIONS, MAX_PRODUCTS, type QuestionDef } from "./survey";

/** A ready-made poll: title, topic, whether it uses live products, and 4–5 complete questions. */
export interface PollPreset { id: string; label: string; hint: string; title: string; topic: string; use_products: boolean; questions: Partial<QuestionDef>[] }
export const POLL_PRESETS = raw as PollPreset[];

/** Fill a preset with live products: product questions list their names (padded so there are always ≥ 2 options). */
export function applyPreset(p: PollPreset, live: { product_id: string; name: string }[]) {
  const prods = p.use_products ? live.slice(0, MAX_PRODUCTS) : [];
  const names = prods.map((x) => x.name).slice(0, MAX_OPTIONS);
  const pad = ["My current phone", "Another brand", "Not sure"];
  const opts = names.length >= 2 ? names : [...names, ...pad].slice(0, Math.max(2, names.length + 1));
  const questions = p.questions.map((q, i): QuestionDef => {
    const isProd = q.option_source === "products";
    const options = isProd ? opts : q.options ?? null;
    return {
      question_id: `q${i + 1}`, text: q.text ?? "", type: q.type ?? "single", discuss: q.discuss ?? true,
      option_source: isProd && names.length >= 2 ? "products" : "custom", options,
      max_select: q.type === "multi" ? Math.min(q.max_select ?? 2, options?.length ?? 2) : null,
      scale: q.type === "scale" ? { min: 1, max: q.scale?.max ?? 5, low_label: q.scale?.low_label ?? "", high_label: q.scale?.high_label ?? "" } : null,
    } as QuestionDef;
  });
  return { title: p.title, topic: p.topic, product_ids: prods.map((x) => x.product_id), questions };
}
