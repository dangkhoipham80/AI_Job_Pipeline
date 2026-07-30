import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";
import { Applications } from "@/pages/Applications";
import { CvReview } from "@/pages/CvReview";
import { CvStudio } from "@/pages/CvStudio";
import { Runs } from "@/pages/Runs";
import { Settings } from "@/pages/Settings";
import { Dashboard } from "@/pages/Dashboard";
import { Guide } from "@/pages/Guide";
import { Jobs } from "@/pages/Jobs";
import { JobDetail } from "@/pages/JobDetail";

export default function App() {
  // Realtime nudge: any server push bumps `version`, which pages depend on to
  // refetch (PLAN.md §5.5 — WS keeps the dashboard in sync with the DB).
  const [version, setVersion] = useState(0);
  const { connected } = useWebSocket((msg: WsMessage) => {
    if (["job_updated", "cv_updated", "tailor_done", "apply_done", "task_updated"].includes(msg.type)) {
      setVersion((v) => v + 1);
    }
  });

  return (
    <BrowserRouter>
      <Layout live={connected}>
        <Routes>
          <Route path="/" element={<Dashboard version={version} />} />
          <Route path="/jobs" element={<Jobs version={version} />} />
          <Route path="/jobs/:id" element={<JobDetail version={version} />} />
          <Route path="/jobs/:id/review" element={<CvReview version={version} />} />
          <Route path="/cv" element={<CvStudio version={version} />} />
          <Route path="/cv/:scope" element={<CvStudio version={version} />} />
          <Route path="/applications" element={<Applications version={version} />} />
          <Route path="/runs" element={<Runs version={version} />} />
          <Route path="/guide" element={<Guide version={version} />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
