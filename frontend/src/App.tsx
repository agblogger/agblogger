import { useEffect } from 'react'
import { createBrowserRouter, RouterProvider, useLocation, Outlet } from 'react-router-dom'
import Header from '@/components/layout/Header'
import TimelinePage from '@/pages/TimelinePage'
import PostPage from '@/pages/PostPage'
import PageViewPage from '@/pages/PageViewPage'
import SearchPage from '@/pages/SearchPage'
import LoginPage from '@/pages/LoginPage'
import LabelPostsPage from '@/pages/LabelPostsPage'
import LabelsPage from '@/pages/LabelsPage'
import LabelSettingsPage from '@/pages/LabelSettingsPage'
import EditorPage from '@/pages/EditorPage'
import AdminPage from '@/pages/AdminPage'
import { useSiteStore } from '@/stores/siteStore'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

function Layout() {
  const location = useLocation()
  const isEditor = location.pathname.startsWith('/editor')
  const isPost = location.pathname.startsWith('/post/')
  const isWide = isEditor || location.pathname === '/admin'
  const mainClass = isPost
    ? 'max-w-3xl xl:max-w-5xl mx-auto px-6 py-10'
    : isWide
      ? 'max-w-6xl mx-auto px-6 py-10'
      : 'max-w-3xl mx-auto px-6 py-10'

  const fetchConfig = useSiteStore((s) => s.fetchConfig)
  const checkAuth = useAuthStore((s) => s.checkAuth)
  const initTheme = useThemeStore((s) => s.init)

  useEffect(() => {
    void fetchConfig()
    void checkAuth()
    initTheme()
  }, [fetchConfig, checkAuth, initTheme])

  return (
    <div className="min-h-screen bg-paper">
      <Header />
      <main className={mainClass}>
        <Outlet />
      </main>

      <footer className="border-t border-border mt-16">
        <div className="max-w-3xl mx-auto px-6 py-8">
          <p className="text-xs text-muted text-center font-mono tracking-wide">
            Powered by{' '}
            <a
              href="https://github.com/agblogger/agblogger"
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-border hover:text-accent hover:decoration-accent transition-colors"
            >
              AgBlogger
            </a>
          </p>
        </div>
      </footer>
    </div>
  )
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <TimelinePage /> },
      { path: '/post/*', element: <PostPage /> },
      { path: '/page/:pageId', element: <PageViewPage /> },
      { path: '/search', element: <SearchPage /> },
      { path: '/login', element: <LoginPage /> },
      { path: '/labels', element: <LabelsPage /> },
      { path: '/labels/:labelId/settings', element: <LabelSettingsPage /> },
      { path: '/labels/:labelId', element: <LabelPostsPage /> },
      { path: '/editor/*', element: <EditorPage /> },
      { path: '/admin', element: <AdminPage /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
