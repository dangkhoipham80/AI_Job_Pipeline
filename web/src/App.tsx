import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";
import { CvReview } from "@/pages/CvReview";
import { CvStudio } from "@/pages/CvStudio";
import { Dashboard } from "@/pages/Dashboard";
import { Jobs } from "@/pages/Jobs";
import { JobDetail } from "@/pages/JobDetail";

export default function App() {
  // Realtime nudge: any server push bumps `version`, which pages depend on to
  // refetch (PLAN.md §5.5 — WS keeps the dashboard in sync with the DB).
  const [version, setVersion] = useState(0);
  const { connected } = useWebSocket((msg: WsMessage) => {
    if (["job_updated", "cv_updated", "tailor_done"].includes(msg.type)) {
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
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
