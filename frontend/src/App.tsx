import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import InboxPage from "./pages/InboxPage";
import WritingStudioPage from "./pages/WritingStudioPage";
import CopilotPage from "./pages/CopilotPage";
import MeetingsPage from "./pages/MeetingsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import AutomationPage from "./pages/AutomationPage";
import SettingsPage from "./pages/SettingsPage";
import LoginPage from "./pages/LoginPage";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="inbox" element={<InboxPage folder="inbox" />} />
          <Route path="starred" element={<InboxPage folder="starred" />} />
          <Route path="sent" element={<InboxPage folder="sent" />} />
          <Route path="drafts" element={<InboxPage folder="drafts" />} />
          <Route path="writing" element={<WritingStudioPage />} />
          <Route path="copilot" element={<CopilotPage />} />
          <Route path="meetings" element={<MeetingsPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
