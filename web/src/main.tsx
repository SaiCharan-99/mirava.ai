import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "./styles/tokens.css";
import "./styles/mockup.css";
import "./styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { applyFreeze, isVisualTest } from "./lib/visualTest";
import { startLive } from "./lib/liveSync";
import { useWatch } from "./state/watch";
import { simClock } from "./world/tracks";
import { loadFixtures } from "./visual-fixtures/types";
import { useWorld } from "./state/world";

applyFreeze();
// Phase 1: world stats, ticker and products come from the mockup fixtures until world-engine streams /live (phase 2).
// Fixtures render until world-engine's /live `hello` arrives (and always in visual-test mode).
const fx = await loadFixtures();
useWorld.getState().loadFixtures(fx);
if (!isVisualTest) useWorld.setState({ budget: { used_usd: 0, cap_usd: 15 } });   // never show the mockup's $6.40 as real spend
simClock.set(fx.t);
simClock.frozen = isVisualTest;
if (isVisualTest) useWatch.getState().seed(fx.agents.filter((a) => a.watch).map((a) => a.id), true);
if (!isVisualTest) startLive();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
