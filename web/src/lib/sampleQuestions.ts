/** Curated sample questions per Insights tab (fix-B). ASK_STARTERS mirrors agents/insights_assistant.py STARTER_QUESTIONS. */

export const ASK_STARTERS: string[] = [
  "How many people are considering each product?",
  "Where did people first hear about our products?",
  "How many purchases were of our products versus other phones?",
  "Which hoarding sites get noticed most often?",
  "How did store inquiries about our products turn out?",
  "How many people are aware of each product so far?",
  "Are people with phones older than 5 years interested in our phones, and why?",
];

export interface InterviewPersona { occupation?: string; age?: number; phone?: { age_years: number | null } }

/** 5–7 interview prompts tailored to the person (phone age, age, job). */
export function interviewPrompts(p: InterviewPersona | undefined): string[] {
  const out = ["Have you seen any new phone ads around Indiranagar lately?", "What would make you switch to a new phone?"];
  const age = p?.phone?.age_years ?? null;
  if (age !== null && age >= 3) out.push(`Your phone is about ${Math.round(age)} years old. What bothers you most about it?`);
  else out.push("What do you like most about the phone you have now?");
  if (p?.occupation) out.push(`How do you use your phone for work as a ${p.occupation.toLowerCase()}?`);
  if (p?.age && p.age < 26) out.push("Do your friends talk about phones? What do they say?");
  else out.push("Who do you ask for advice before buying something expensive?");
  out.push("How much would you be willing to spend on your next phone?", "Have you talked to anyone about a new phone recently?");
  return out.slice(0, 7);
}

/** Preset focus-group / poll titles (open the builder pre-filled). */
export const POLL_TEMPLATES: string[] = [
  "Which of our phones would you consider next?",
  "What matters most in your next phone: battery, camera or price?",
  "Did any hoarding make you curious about a phone this week?",
  "What would stop you from buying one of our phones?",
  "How much would you pay for our newest phone?",
  "Which ad did you remember, and why?",
];

/** Ask-tab link that pre-fills a question. */
export function askLink(q: string): string {
  return `/insights/ask?q=${encodeURIComponent(q)}`;
}

/** "Ask about this" question for a hoarding site. */
export const siteQuestion = (site: string) => `What did people think when they noticed the hoarding at site ${site}?`;
/** "Ask about this" question for a product's segments. */
export const segmentQuestion = (product: string) => `Which segments are likely buyers for ${product}, and why?`;
