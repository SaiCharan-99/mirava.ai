import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Header, Sidebar } from "./components/Shell";
import { WorldPage } from "./pages/WorldPage";
import { PeoplePage } from "./pages/PeoplePage";
import { GuidePage } from "./pages/GuidePage";
import { InsightsPage } from "./pages/InsightsPage";
import { FocusWaitPage } from "./pages/focus/FocusWaitPage";
import { FocusRoomPage } from "./pages/focus/FocusRoomPage";
import { FocusResultsPage } from "./pages/focus/FocusResultsPage";
import { SurveyBanner } from "./components/SurveyBanner";
import { LaunchListPage, StudioPage } from "./pages/LaunchPages";
import { GlobeIntro, hasWebGL, introSeen } from "./globe/GlobeIntro";
import { isVisualTest, withMode } from "./lib/visualTest";
import { useLiveHooks } from "./hooks/ll";

/** Old Polls / Survey Room links → the Focus groups tab and its pages. */
function OldSurveyRedirect() {
  const { surveyId } = useParams();
  return <Navigate to={withMode(surveyId && surveyId !== "new" ? `/insights/focus/${surveyId}/room` : "/insights/focus")} replace />;
}

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
          <SurveyBanner />
          <Routes>
            <Route path="/" element={<Root />} />
            <Route path="/globe" element={<WorldPage />} />
            <Route path="/world" element={<WorldPage />} />
            <Route path="/launch" element={<LaunchListPage />} />
            <Route path="/launch/:productId/:step" element={<StudioPage />} />
            <Route path="/launch/:productId" element={<StudioPage />} />
            <Route path="/insights/polls/survey/:surveyId" element={<OldSurveyRedirect />} />
            <Route path="/insights/polls" element={<Navigate to={withMode("/insights/focus")} replace />} />
            <Route path="/insights/focus/:surveyId/wait" element={<FocusWaitPage />} />
            <Route path="/insights/focus/:surveyId/room" element={<FocusRoomPage />} />
            <Route path="/insights/focus/:surveyId/results" element={<FocusResultsPage />} />
            <Route path="/insights/:tab" element={<InsightsPage />} />
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
