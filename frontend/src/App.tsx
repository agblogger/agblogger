import { lazy, Suspense, useEffect } from "react";
import {
  createBrowserRouter,
  RouterProvider,
  useLocation,
  Outlet,
} from "react-router-dom";
import { SWRConfig } from "swr";
import api from "@/api/client";
import Header from "@/components/layout/Header";
import LoadingSpinner from "@/components/LoadingSpinner";
import TimelinePage from "@/pages/TimelinePage";
import PostPage from "@/pages/PostPage";
import PageViewPage from "@/pages/PageViewPage";
import LoginPage from "@/pages/LoginPage";
import LabelPostsPage from "@/pages/LabelPostsPage";
import LabelsPage from "@/pages/LabelsPage";
import { useSiteStore } from "@/stores/siteStore";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";

const SearchPage = lazy(() => import("@/pages/SearchPage"));
const EditorPage = lazy(() => import("@/pages/EditorPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));
const LabelSettingsPage = lazy(() => import("@/pages/LabelSettingsPage"));
const LabelCreatePage = lazy(() => import("@/pages/LabelCreatePage"));

function LazyFallback() {
  return <LoadingSpinner />;
}

const SWR_CONFIG = { fetcher: (url: string) => api.get(url).json(), dedupingInterval: 2000 };

function Layout() {
  const location = useLocation();
  const isEditor = location.pathname.startsWith("/editor");
  const isPost = location.pathname.startsWith("/post/");
  const isWide = isEditor || location.pathname === "/admin";
  const mainClass = isPost
    ? "max-w-3xl xl:max-w-5xl mx-auto px-6 py-10"
    : isWide
      ? "max-w-6xl mx-auto px-6 py-10"
      : "max-w-3xl mx-auto px-6 py-10";

  const fetchConfig = useSiteStore((s) => s.fetchConfig);
  const siteTitle = useSiteStore((s) => s.config?.title);
  const checkAuth = useAuthStore((s) => s.checkAuth);
  const initTheme = useThemeStore((s) => s.init);

  useEffect(() => {
    void fetchConfig();
    void checkAuth();
    const cleanupTheme = initTheme();
    return cleanupTheme;
  }, [fetchConfig, checkAuth, initTheme]);

  useEffect(() => {
    if (siteTitle !== undefined && siteTitle !== "") {
      document.title = siteTitle;
    }
  }, [siteTitle]);

  return (
    <SWRConfig value={SWR_CONFIG}>
      <div className="min-h-screen bg-paper">
        <Header />
        <main className={mainClass}>
          <Suspense fallback={<LazyFallback />}>
            <Outlet />
          </Suspense>
        </main>

        <footer className="border-t border-border mt-16">
          <div className="max-w-3xl mx-auto px-6 py-8">
            <p className="text-xs text-muted text-center font-mono tracking-wide">
              Powered by{" "}
              <a
                href="https://agblogger.github.io"
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
    </SWRConfig>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <TimelinePage /> },
      { path: "/post/*", element: <PostPage /> },
      { path: "/page/:pageId", element: <PageViewPage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/labels", element: <LabelsPage /> },
      { path: "/labels/new", element: <LabelCreatePage /> },
      { path: "/labels/:labelId/settings", element: <LabelSettingsPage /> },
      { path: "/labels/:labelId", element: <LabelPostsPage /> },
      { path: "/editor/*", element: <EditorPage /> },
      { path: "/admin", element: <AdminPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
