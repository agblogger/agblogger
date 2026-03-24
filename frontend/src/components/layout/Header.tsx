import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Search, LogIn, LogOut, PenLine, Settings, Menu, X, Sun, Moon, Filter } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSiteStore } from '@/stores/siteStore'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { useFilterPanelStore } from '@/stores/filterPanelStore'
import { searchPosts } from '@/api/posts'
import type { SearchResult } from '@/api/client'
import SearchDropdown from '@/components/search/SearchDropdown'

export default function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const config = useSiteStore((s) => s.config)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const isLoggingOut = useAuthStore((s) => s.isLoggingOut)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const panelState = useFilterPanelStore((s) => s.panelState)
  const activeFilterCount = useFilterPanelStore((s) => s.activeFilterCount)
  const togglePanel = useFilterPanelStore((s) => s.togglePanel)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const closeSearchRef = useRef<HTMLButtonElement>(null)
  const [dropdownResults, setDropdownResults] = useState<SearchResult[]>([])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(-1)
  const [dropdownError, setDropdownError] = useState<string | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable

      if ((e.key === '/' && !isInput) || ((e.metaKey || e.ctrlKey) && e.key === 'k')) {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const doSearch = useCallback((query: string) => {
    if (debounceRef.current !== null) clearTimeout(debounceRef.current)
    if (abortRef.current !== null) abortRef.current.abort()

    if (query.trim().length < 2) {
      setDropdownResults([])
      setDropdownOpen(false)
      setDropdownError(null)
      setSearchLoading(false)
      setHighlightIndex(-1)
      return
    }

    setSearchLoading(true)
    setDropdownOpen(true)
    setDropdownError(null)
    setDropdownResults([])
    debounceRef.current = setTimeout(() => {
      const controller = new AbortController()
      abortRef.current = controller
      searchPosts(query.trim(), 5, controller.signal)
        .then((results) => {
          if (!controller.signal.aborted) {
            setDropdownResults(results)
            setDropdownError(null)
            setSearchLoading(false)
            setDropdownOpen(true)
            setHighlightIndex(-1)
          }
        })
        .catch((err: unknown) => {
          if (err instanceof Error && err.name === 'AbortError') return
          if (err instanceof DOMException && err.name === 'AbortError') return
          console.error('Search dropdown error:', err)
          setDropdownError('Search failed')
          setDropdownResults([])
          setSearchLoading(false)
          setDropdownOpen(true)
        })
    }, 300)
  }, [])

  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) clearTimeout(debounceRef.current)
      if (abortRef.current !== null) abortRef.current.abort()
    }
  }, [])

  function closeMobileMenu() {
    setMobileMenuOpen(false)
  }

  function cancelPendingSearch() {
    if (debounceRef.current !== null) clearTimeout(debounceRef.current)
    if (abortRef.current !== null) abortRef.current.abort()
  }

  function dismissDropdown() {
    cancelPendingSearch()
    setDropdownOpen(false)
    setDropdownError(null)
    setSearchLoading(false)
    setHighlightIndex(-1)
  }

  function closeSearch() {
    setSearchOpen(false)
    setSearchQuery('')
    setDropdownResults([])
    setDropdownError(null)
    setSearchLoading(false)
    dismissDropdown()
  }

  const pages = config?.pages ?? []
  const siteTitle = config?.title ?? 'AgBlogger'
  const ThemeIcon = theme === 'dark' ? Moon : Sun
  const isTimeline = location.pathname === '/'

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (searchQuery.trim()) {
      void navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
      closeSearch()
    }
  }

  async function handleLogout() {
    await logout()
  }

  return (
    <header className="border-b border-border bg-paper/80 backdrop-blur-sm sticky top-0 z-50">
      {/* Top bar */}
      <div className="max-w-5xl mx-auto px-6">
        <div className="flex items-center justify-between h-16">
          <Link
            to="/"
            className={`font-display text-2xl tracking-tight text-ink hover:text-accent transition-colors ${searchOpen ? 'hidden sm:block' : ''}`}
          >
            {siteTitle}
          </Link>

          <div className={`flex items-center gap-3 ${searchOpen ? 'flex-1 sm:flex-initial' : ''}`}>
            {searchOpen ? (
              <div className="relative flex-1 sm:flex-initial">
                <form onSubmit={handleSearch} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value)
                      setHighlightIndex(-1)
                      doSearch(e.target.value)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') {
                        if (dropdownOpen) {
                          dismissDropdown()
                        } else {
                          closeSearch()
                        }
                        return
                      }
                      if (!dropdownOpen || dropdownResults.length === 0) return

                      if (e.key === 'ArrowDown') {
                        e.preventDefault()
                        setHighlightIndex((prev) =>
                          prev >= dropdownResults.length - 1 ? -1 : prev + 1
                        )
                      } else if (e.key === 'ArrowUp') {
                        e.preventDefault()
                        setHighlightIndex((prev) =>
                          prev <= -1 ? -1 : prev - 1
                        )
                      } else if (e.key === 'Enter' && highlightIndex >= 0) {
                        e.preventDefault()
                        const result = dropdownResults[highlightIndex]
                        if (result) {
                          void navigate(`/post/${result.file_path}`)
                          closeSearch()
                        }
                      }
                    }}
                    placeholder="Search posts..."
                    aria-label="Search posts"
                    autoFocus
                    role="combobox"
                    aria-expanded={dropdownOpen}
                    aria-controls="search-results-listbox"
                    aria-activedescendant={highlightIndex >= 0 ? `search-result-${highlightIndex}` : undefined}
                    aria-autocomplete="list"
                    className="flex-1 min-w-0 sm:w-72 md:w-96 sm:flex-none px-3 py-1.5 text-sm bg-paper-warm border border-border rounded-lg
                             focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                             font-body placeholder:text-muted"
                    onBlur={(e) => {
                      if (e.relatedTarget === closeSearchRef.current) return
                      if (!searchQuery) {
                        closeSearch()
                      } else {
                        dismissDropdown()
                      }
                    }}
                  />
                  <button
                    ref={closeSearchRef}
                    type="button"
                    onClick={() => {
                      closeSearch()
                    }}
                    className="p-1.5 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                    aria-label="Close search"
                  >
                    <X size={16} />
                  </button>
                </form>
                {dropdownOpen && (
                  <SearchDropdown
                    results={dropdownResults}
                    query={searchQuery}
                    highlightIndex={highlightIndex}
                    error={dropdownError}
                    loading={searchLoading}
                    onSelect={(filePath) => {
                      void navigate(`/post/${filePath}`)
                      closeSearch()
                    }}
                    onFooterClick={() => {
                      if (searchQuery.trim()) {
                        void navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
                      }
                      closeSearch()
                    }}
                  />
                )}
              </div>
            ) : (
              <button
                onClick={() => setSearchOpen(true)}
                className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                aria-label="Search"
                title="Search (/)"
              >
                <Search size={18} />
              </button>
            )}

            {isTimeline && (
              <button
                onClick={togglePanel}
                className={`p-2 rounded-lg transition-colors ${
                  panelState === 'open'
                    ? 'text-accent bg-accent/10'
                    : 'text-muted hover:text-ink hover:bg-paper-warm'
                } ${searchOpen ? 'hidden sm:block' : ''}`}
                aria-label="Toggle filters"
                title="Filters"
              >
                <div className="relative">
                  <Filter size={18} />
                  {activeFilterCount > 0 && (
                    <span className="absolute -top-1.5 -right-2 bg-accent text-white text-[9px] font-mono min-w-[16px] h-4 flex items-center justify-center px-1 rounded-full leading-none">
                      {activeFilterCount}
                    </span>
                  )}
                </div>
              </button>
            )}

            <button
              onClick={toggleTheme}
              className={`p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm ${searchOpen ? 'hidden sm:block' : ''}`}
              title={`Theme: ${theme}`}
              aria-label="Toggle theme"
            >
              <ThemeIcon size={18} />
            </button>

            <div className="hidden md:flex items-center gap-3">
              {user ? (
                <>
                  <Link
                    to="/editor/new"
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                             bg-accent text-white rounded-lg hover:bg-accent-light transition-colors"
                  >
                    <PenLine size={14} />
                    <span>Write</span>
                  </Link>
                  {user.is_admin && (
                    <Link
                      to="/admin"
                      className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                      aria-label="Admin"
                      title="Admin panel"
                    >
                      <Settings size={18} />
                    </Link>
                  )}
                  <button
                    onClick={() => void handleLogout()}
                    disabled={isLoggingOut}
                    className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm disabled:opacity-50 disabled:cursor-not-allowed"
                    aria-label="Logout"
                    title="Log out"
                  >
                    <LogOut size={18} />
                  </button>
                </>
              ) : (
                <Link
                  to="/login"
                  className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                  aria-label="Login"
                >
                  <LogIn size={18} />
                </Link>
              )}
            </div>

            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className={`md:hidden p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm ${searchOpen ? 'hidden' : ''}`}
              aria-label="Menu"
            >
              {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>

        {/* Navigation tabs (desktop) */}
        <nav className="hidden md:flex gap-1 -mb-px">
          {pages.map((page) => {
            const path =
              page.id === 'timeline'
                ? '/'
                : page.id === 'labels'
                  ? '/labels'
                  : `/page/${page.id}`
            const isActive =
              page.id === 'timeline'
                ? location.pathname === '/'
                : page.id === 'labels'
                  ? location.pathname === '/labels' ||
                    location.pathname.startsWith('/labels/')
                  : location.pathname === path

            return (
              <Link
                key={page.id}
                to={path}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  isActive
                    ? 'border-accent text-accent'
                    : 'border-transparent text-muted hover:text-ink hover:border-border-dark'
                }`}
              >
                {page.title}
              </Link>
            )
          })}
        </nav>
      </div>

      {/* Mobile menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-border bg-paper px-6 py-4 space-y-3 animate-fade-in">
          <nav className="flex flex-col gap-1">
            {pages.map((page) => {
              const path =
                page.id === 'timeline'
                  ? '/'
                  : page.id === 'labels'
                    ? '/labels'
                    : `/page/${page.id}`
              const isActive =
                page.id === 'timeline'
                  ? location.pathname === '/'
                  : page.id === 'labels'
                    ? location.pathname === '/labels' ||
                      location.pathname.startsWith('/labels/')
                    : location.pathname === path

              return (
                <Link
                  key={page.id}
                  to={path}
                  onClick={closeMobileMenu}
                  className={`px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                    isActive
                      ? 'bg-accent/10 text-accent'
                      : 'text-muted hover:text-ink hover:bg-paper-warm'
                  }`}
                >
                  {page.title}
                </Link>
              )
            })}
          </nav>

          <div className="flex items-center gap-3 pt-2 border-t border-border/50">
            {isTimeline && (
              <button
                onClick={() => { closeMobileMenu(); togglePanel() }}
                className={`p-2 rounded-lg transition-colors ${
                  panelState === 'open'
                    ? 'text-accent bg-accent/10'
                    : 'text-muted hover:text-ink hover:bg-paper-warm'
                }`}
                aria-label="Toggle filters"
                title="Filters"
              >
                <div className="relative">
                  <Filter size={18} />
                  {activeFilterCount > 0 && (
                    <span className="absolute -top-1.5 -right-2 bg-accent text-white text-[9px] font-mono min-w-[16px] h-4 flex items-center justify-center px-1 rounded-full leading-none">
                      {activeFilterCount}
                    </span>
                  )}
                </div>
              </button>
            )}
            <button
              onClick={toggleTheme}
              className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
              title={`Theme: ${theme}`}
              aria-label="Toggle theme"
            >
              <ThemeIcon size={18} />
            </button>
            {user ? (
              <>
                <Link
                  to="/editor/new"
                  onClick={closeMobileMenu}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                           bg-accent text-white rounded-lg hover:bg-accent-light transition-colors"
                >
                  <PenLine size={14} />
                  <span>Write</span>
                </Link>
                {user.is_admin && (
                  <Link
                    to="/admin"
                    onClick={closeMobileMenu}
                    className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                    aria-label="Admin"
                  >
                    <Settings size={18} />
                  </Link>
                )}
                <button
                  onClick={() => { closeMobileMenu(); void handleLogout() }}
                  disabled={isLoggingOut}
                  className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm disabled:opacity-50"
                  aria-label="Logout"
                  title="Log out"
                >
                  <LogOut size={18} />
                </button>
              </>
            ) : (
              <Link
                to="/login"
                onClick={closeMobileMenu}
                className="p-2 text-muted hover:text-ink transition-colors rounded-lg hover:bg-paper-warm"
                aria-label="Login"
              >
                <LogIn size={18} />
              </Link>
            )}
          </div>
        </div>
      )}
    </header>
  )
}
