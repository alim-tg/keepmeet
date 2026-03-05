import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "@/components/Layout"
import { JobListPage } from "@/pages/JobListPage"
import { NewJobPage } from "@/pages/NewJobPage"
import { JobDetailPage } from "@/pages/JobDetailPage"
import { ProfilesPage } from "@/pages/ProfilesPage"

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<JobListPage />} />
          <Route path="/new" element={<NewJobPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
