import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Header, Sidebar } from "./components/Shell";
import { WorldPage } from "./pages/WorldPage";
import { PeoplePage } from "./pages/PeoplePage";
import { GuidePage } from "./pages/GuidePage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { LaunchListPage, StudioPage } from "./pages/LaunchPages";
import { GlobeIntro, hasWebGL, introSeen } from "./globe/GlobeIntro";
import { isVisualTest, withMode } from "./lib/visualTest";
import { useLiveHooks } from "./hooks/ll";

/** `/` → globe on the first visit of a browser session (and only with WebGL), else the World. */
function Root() {
  const first = !isVisualTest && !introSeen() && hasWebGL();
  return <Navigate to={withMode(first ? "/globe" : "/world")} replace />;
}

export function App() {
  useLiveHooks();
  const loc = useLocation();
  const onGlobe = loc.pathname === "/globe";
  return (
    <>
      <div className="shell">
        <Header />
        <Sidebar />
        <main data-testid="app-main">
          <Routes>
            <Route path="/" element={<Root />} />
            <Route path="/globe" element={<WorldPage />} />
            <Route path="/world" element={<WorldPage />} />
            <Route path="/launch" element={<LaunchListPage />} />
            <Route path="/launch/:productId/:step" element={<StudioPage />} />
            <Route path="/launch/:productId" element={<StudioPage />} />
            <Route path="/insights/:tab" element={<PlaceholderPage title="Insights" phase={5}
              sub="Ask anything about the world, plus dashboards over everything it has logged." />} />
            <Route path="/insights" element={<Navigate to={withMode("/insights/ask")} replace />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/guide" element={<GuidePage />} />
            <Route path="*" element={<Navigate to={withMode("/world")} replace />} />
          </Routes>
        </main>
      </div>
      {onGlobe && <GlobeIntro />}
    </>
  );
}
