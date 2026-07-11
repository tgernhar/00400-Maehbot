import { useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import { fetchStatus, Status } from "./api";
import { Nav, StatusBanner } from "./components/Layout";
import DrivePage from "./pages/DrivePage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import SprayPage from "./pages/SprayPage";
import TrainingPage from "./pages/TrainingPage";

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => undefined);
    const t = setInterval(() => fetchStatus().then(setStatus).catch(() => undefined), 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="app">
      <Nav />
      <StatusBanner status={status} />
      <main>
        <Routes>
          <Route path="/" element={<ReviewPage />} />
          <Route path="/drive" element={<DrivePage />} />
          <Route path="/spray" element={<SprayPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/training" element={<TrainingPage />} />
        </Routes>
      </main>
    </div>
  );
}
