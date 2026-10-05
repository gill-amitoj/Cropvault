import { Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { AdminPage } from './pages/AdminPage'
import { GalleryPage } from './pages/GalleryPage'
import { ImageDetailPage } from './pages/ImageDetailPage'
import { LoginPage } from './pages/LoginPage'
import { UploadPage } from './pages/UploadPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<GalleryPage />} />
        <Route path="images/:id" element={<ImageDetailPage />} />
        <Route
          path="upload"
          element={
            <RequireAuth roles={['admin', 'researcher']}>
              <UploadPage />
            </RequireAuth>
          }
        />
        <Route
          path="admin"
          element={
            <RequireAuth roles={['admin']}>
              <AdminPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<p className="muted">Page not found.</p>} />
      </Route>
    </Routes>
  )
}
