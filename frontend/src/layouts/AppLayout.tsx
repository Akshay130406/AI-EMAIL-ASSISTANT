import {
  Activity, Bell, ChevronsUpDown, Command, FileText, Inbox, LayoutDashboard,
  LogOut, Mail, Menu, Moon,
  PanelLeftClose, PanelLeftOpen, Search, Send, Settings, ShieldCheck, Sparkles, Sun,
  WandSparkles, X, Zap, CalendarDays, Star,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import BackendStatus from "../components/BackendStatus";
import { useAuth } from "../contexts/AuthContext";
import { useTheme } from "../contexts/ThemeContext";

const navigation: { section: string; items: { label: string; path: string; icon: LucideIcon; badge?: string }[] }[] = [
  { section: "Workspace", items: [
    { label: "Dashboard", path: "/", icon: LayoutDashboard },
    { label: "Inbox", path: "/inbox", icon: Inbox },
    { label: "Starred", path: "/starred", icon: Star },
    { label: "Sent", path: "/sent", icon: Send },
    { label: "Drafts", path: "/drafts", icon: FileText },
  ] },
  { section: "Intelligence", items: [
    { label: "AI Writing Studio", path: "/writing", icon: WandSparkles, badge: "NEW" },
    { label: "Email Copilot", path: "/copilot", icon: Sparkles },
    { label: "Meeting Assistant", path: "/meetings", icon: CalendarDays },
  ] },
  { section: "Manage", items: [
    { label: "Analytics", path: "/analytics", icon: Activity },
    { label: "Automation", path: "/automation", icon: Zap },
  ] },
];

const titles: Record<string, string> = {
  "/": "Dashboard", "/inbox": "Inbox", "/starred": "Starred",
  "/sent": "Sent", "/drafts": "Drafts", "/writing": "AI Writing Studio",
  "/copilot": "Email Copilot", "/meetings": "Meeting Assistant",
  "/analytics": "Analytics", "/automation": "Automation", "/settings": "Settings",
};

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const { user, signOut } = useAuth();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const title = titles[location.pathname] ?? "Workspace";
  const displayName = user?.display_name || user?.email || "Signed-in user";
  const initials = displayName
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  async function handleSignOut() {
    setLogoutError(null);
    if (await signOut()) {
      setProfileOpen(false);
      navigate("/login", { replace: true });
    } else {
      setLogoutError("Sign-out failed. Please try again.");
    }
  }

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate(`/inbox${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ""}`);
    setMobileOpen(false);
  }

  const sidebarClass = `fixed inset-y-0 left-0 z-40 flex flex-col border-r border-line bg-sidebar transition-all duration-200 ${
    collapsed ? "w-[76px]" : "w-[252px]"
  } ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"} ${
    collapsed ? "md:w-[76px]" : "md:w-[252px]"
  }`;

  return (
    <div className="min-h-screen bg-canvas text-main">
      {mobileOpen && <button aria-label="Close navigation" className="fixed inset-0 z-30 bg-black/45 md:hidden" onClick={() => setMobileOpen(false)} />}
      <aside className={sidebarClass}>
        <div className={`flex h-[68px] shrink-0 items-center border-b border-line ${collapsed ? "justify-center px-2" : "justify-between px-5"}`}>
          <button onClick={() => navigate("/")} className="flex items-center gap-3 text-left" aria-label="Mailmind dashboard">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent text-white shadow-sm shadow-accent/20"><Mail size={18} strokeWidth={2.2} /></span>
            {!collapsed && <span><span className="block text-[15px] font-semibold tracking-tight">mailmind</span><span className="block text-[10px] font-medium tracking-wide text-muted">YOUR CALM INBOX</span></span>}
          </button>
          {!collapsed && <button onClick={() => setCollapsed(true)} className="icon-button hidden md:grid" aria-label="Collapse sidebar"><PanelLeftClose size={16} /></button>}
        </div>
        {collapsed && <button onClick={() => setCollapsed(false)} className="icon-button mx-auto mt-3 hidden md:grid" aria-label="Expand sidebar"><PanelLeftOpen size={16} /></button>}

        <div className={`px-3 pt-4 ${collapsed ? "px-2" : ""}`}>
          {!collapsed && <button onClick={() => navigate("/writing")} className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-accent text-sm font-medium text-white transition hover:bg-accent-hover"><Sparkles size={16} /> Compose with AI</button>}
          {collapsed && <button title="Compose with AI" onClick={() => navigate("/writing")} className="mx-auto grid size-10 place-items-center rounded-xl bg-accent text-white hover:bg-accent-hover"><Sparkles size={17} /></button>}
        </div>

        <nav className="scrollbar-thin mt-4 flex-1 space-y-5 overflow-y-auto px-3 pb-3">
          {navigation.map((group) => (
            <div key={group.section}>
              {!collapsed && <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.13em] text-faint">{group.section}</p>}
              <div className="space-y-0.5">
                {group.items.map(({ label, path, icon: Icon, badge }) => (
                  <NavLink key={path} to={path} end={path === "/"} aria-label={label} onClick={() => setMobileOpen(false)} title={collapsed ? label : undefined}
                    className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""} ${collapsed ? "justify-center px-0" : ""}`}>
                    <Icon size={17} strokeWidth={1.8} />
                    {!collapsed && <><span className="min-w-0 flex-1 truncate">{label}</span>{badge && <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[9px] font-semibold tracking-wide text-accent">{badge}</span>}</>}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
          <NavLink to="/settings" title={collapsed ? "Settings" : undefined} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""} ${collapsed ? "justify-center px-0" : ""}`}>
            <Settings size={17} strokeWidth={1.8} />{!collapsed && <span>Settings</span>}
          </NavLink>
        </nav>

        <div className="border-t border-line p-3">
          {!collapsed && <div className="mb-3 rounded-xl bg-soft p-3"><div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-subtle">Service status</span><ShieldCheck size={14} className="text-green-600" /></div><BackendStatus /></div>}
          <button onClick={() => setProfileOpen(!profileOpen)} className={`flex w-full items-center gap-2.5 rounded-xl p-2 text-left transition hover:bg-soft ${collapsed ? "justify-center" : ""}`}>
            {user?.picture_url ? (
              <img src={user.picture_url} alt="" className="size-8 shrink-0 rounded-full object-cover" />
            ) : (
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[#dbe7dc] text-xs font-semibold text-[#42604a]">{initials}</span>
            )}
            {!collapsed && <><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{displayName}</span><span className="block truncate text-[10px] text-muted">{user?.email}</span></span><ChevronsUpDown size={14} className="text-muted" /></>}
          </button>
          {profileOpen && <div className="absolute bottom-16 left-3 w-60 rounded-xl border border-line bg-panel p-2 shadow-xl"><p className="truncate px-2 py-1 text-[11px] text-muted">{user?.email}</p><button onClick={() => { navigate("/settings"); setProfileOpen(false); }} className="menu-item w-full"><Settings size={15} /> Preferences</button>{logoutError && <p role="alert" className="px-2 py-1 text-[10px] text-red-600">{logoutError}</p>}<button onClick={() => void handleSignOut()} className="menu-item w-full"><LogOut size={15} /> Sign out</button></div>}
        </div>
      </aside>

      <div className={`min-h-screen transition-[padding] duration-200 ${collapsed ? "md:pl-[76px]" : "md:pl-[252px]"}`}>
        <header className="sticky top-0 z-20 flex h-[68px] items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur-md sm:px-6 lg:px-8">
          <button className="icon-button md:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={19} /></button>
          <button className="icon-button hidden md:grid" aria-label="Collapse navigation" onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button>
          <div className="hidden text-sm font-medium text-main sm:block">{title}</div>
          <form onSubmit={submitSearch} className="relative ml-auto w-full max-w-[410px]">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search emails..." className="input h-9 w-full pl-9 pr-16 text-xs" aria-label="Search emails" />
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line px-1.5 py-0.5 text-[9px] text-faint"><Command size={9} className="inline" /> K</span>
          </form>
          <div className="relative">
            <button onClick={() => setNotificationOpen(!notificationOpen)} className="icon-button relative" aria-label="Notifications"><Bell size={17} /><span className="absolute right-2 top-2 size-1.5 rounded-full bg-accent" /></button>
            {notificationOpen && <div className="absolute right-0 top-12 z-30 w-72 rounded-xl border border-line bg-panel p-4 shadow-xl"><div className="flex items-center justify-between"><p className="text-sm font-semibold">Notifications</p><button onClick={() => setNotificationOpen(false)} aria-label="Close notifications"><X size={14} /></button></div><p className="mt-4 text-xs leading-5 text-muted">You’re all caught up. Notifications shown here are local demo content.</p></div>}
          </div>
          <button onClick={toggleTheme} className="icon-button" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
        </header>
        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 lg:px-9"><Outlet /></main>
      </div>
    </div>
  );
}
