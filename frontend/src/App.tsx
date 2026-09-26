import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Toaster } from "sonner"
import { Layout } from "@/components/Layout"
import { JobListPage } from "@/pages/JobListPage"
import { NewJobPage } from "@/pages/NewJobPage"
import { JobDetailPage } from "@/pages/JobDetailPage"
import { ProfilesPage } from "@/pages/ProfilesPage"
import { SettingsPage } from "@/pages/SettingsPage"

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<JobListPage />} />
          <Route path="/new" element={<NewJobPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Layout>
      <Toaster theme="dark" position="bottom-right" />
    </BrowserRouter>
  )
}

export default App
