import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { useWebSocket, type WsMessage } from "@/hooks/useWebSocket";
import { Dashboard } from "@/pages/Dashboard";
import { Jobs } from "@/pages/Jobs";
import { JobDetail } from "@/pages/JobDetail";

export default function App() {
  // Realtime nudge: any server push bumps `version`, which pages depend on to
  // refetch (PLAN.md §5.5 — WS keeps the dashboard in sync with the DB).
  const [version, setVersion] = useState(0);
  const { connected } = useWebSocket((msg: WsMessage) => {
    if (msg.type === "job_updated") setVersion((v) => v + 1);
  });

  return (
    <BrowserRouter>
      <Layout live={connected}>
        <Routes>
          <Route path="/" element={<Dashboard version={version} />} />
          <Route path="/jobs" element={<Jobs version={version} />} />
          <Route path="/jobs/:id" element={<JobDetail version={version} />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
