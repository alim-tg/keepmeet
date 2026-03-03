import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "@/components/Layout"
import { JobListPage } from "@/pages/JobListPage"
import { NewJobPage } from "@/pages/NewJobPage"
import { JobDetailPage } from "@/pages/JobDetailPage"

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<JobListPage />} />
          <Route path="/new" element={<NewJobPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
