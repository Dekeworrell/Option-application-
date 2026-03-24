import React, { useEffect, useMemo, useRef, useState } from "react";
import saveIcon from "./assets/save.png";
import editIcon from "./assets/edit.png";
import {
  clearToken,
  createList,
  createTicker,
  deleteList,
  deleteTicker,
  getLists,
  getTickers,
  getWatchlistQuotes,
  isLoggedIn,
  login,
  saveToken,
  updateList,
  type TickerItem,
  type Watchlist,
  type WatchlistQuote,
} from "./lib/api";

type ActivePage = "dashboard" | "watchlists";
type ExpiryScope = "weekly" | "near" | "far" | "all" | "fixed-horizon" | "manual";
type HorizonMode = "1m" | "6m" | "1y";
type OptionSide = "calls" | "puts" | "both";
type PremiumMode = "mid" | "last" | "bid" | "ask";
type TargetMode = "delta" | "percent-otm";
type MoneynessState = "ITM" | "ATM" | "OTM" | "-";

type VisibleColumnsState = {
  symbol: boolean; price: boolean; strike: boolean; expiry: boolean;
  optionSide: boolean; premium: boolean; returnPercent: boolean;
  delta: boolean; gamma: boolean; theta: boolean; vega: boolean; rho: boolean;
  moneyness: boolean; ma20: boolean; ma30: boolean; ma50: boolean; ma200: boolean;
  change: boolean; changePercent: boolean; status: boolean; updated: boolean; note: boolean;
};
type ColumnKey = keyof VisibleColumnsState;
type WatchlistFiltersState = { minPrice: string; minChangePercent: string; status: string; };
type OptionsControlsState = {
  expiryScope: ExpiryScope; horizonMode: HorizonMode; optionSide: OptionSide;
  premiumMode: PremiumMode; manualExpiry: string; targetMode: TargetMode;
  targetDelta: string; targetPercentOtm: string;
};
type SavedView = {
  id: string; name: string; columns: VisibleColumnsState; columnOrder: ColumnKey[];
  filters: WatchlistFiltersState; sort: string; optionsControls: OptionsControlsState;
};
type WatchlistEditorMode = "idle" | "create" | "edit";
type ToolbarMenuKey = "columns" | "sort" | "filter" | "view" | null;

const defaultVisibleColumns: VisibleColumnsState = {
  symbol: true, price: true, strike: true, expiry: true, optionSide: false,
  premium: true, returnPercent: false, delta: false, gamma: false, theta: false,
  vega: false, rho: false, moneyness: true, ma20: false, ma30: false, ma50: false,
  ma200: false, change: false, changePercent: false, status: true, updated: true, note: true,
};

const defaultColumnOrder: ColumnKey[] = [
  "symbol","price","strike","expiry","optionSide","premium","returnPercent",
  "delta","gamma","theta","vega","rho","moneyness","ma20","ma30","ma50","ma200",
  "change","changePercent","status","updated","note",
];

const coreColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "symbol", label: "Symbol" }, { key: "price", label: "Price" },
  { key: "change", label: "Change" }, { key: "changePercent", label: "Change %" },
  { key: "status", label: "Status" }, { key: "updated", label: "Updated" },
  { key: "note", label: "Note" },
];
const optionsColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "strike", label: "Strike" }, { key: "expiry", label: "Expiry" },
  { key: "optionSide", label: "Option Side" }, { key: "premium", label: "Premium" },
  { key: "returnPercent", label: "Return %" }, { key: "moneyness", label: "Moneyness" },
];
const greeksColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "delta", label: "Delta" }, { key: "gamma", label: "Gamma" },
  { key: "theta", label: "Theta" }, { key: "vega", label: "Vega" }, { key: "rho", label: "Rho" },
];
const movingAverageColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "ma20", label: "MA20" }, { key: "ma30", label: "MA30" },
  { key: "ma50", label: "MA50" }, { key: "ma200", label: "MA200" },
];
const dashboardColumnOptions = [...coreColumnOptions, ...optionsColumnOptions, ...greeksColumnOptions, ...movingAverageColumnOptions];
const defaultFilters: WatchlistFiltersState = { minPrice: "", minChangePercent: "", status: "all" };
const defaultOptionsControls: OptionsControlsState = {
  expiryScope: "weekly", horizonMode: "1m", optionSide: "calls", premiumMode: "mid",
  manualExpiry: "", targetMode: "delta", targetDelta: "0.30", targetPercentOtm: "5",
};
const SAVED_VIEWS_STORAGE_KEY = "options-dashboard-saved-views";
const TOOLBAR_COLLAPSED_STORAGE_KEY = "options-dashboard-toolbar-collapsed";

function App() {
  const [authenticated, setAuthenticated] = useState(isLoggedIn());
  if (!authenticated) return <LoginScreen onLoginSuccess={() => setAuthenticated(true)} />;
  return <Shell onLogout={() => { clearToken(); setAuthenticated(false); }} />;
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [activePage, setActivePage] = useState<ActivePage>("dashboard");
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [selectedListId, setSelectedListId] = useState<number | null>(null);
  const [listsLoading, setListsLoading] = useState(true);
  const [listsError, setListsError] = useState("");

  async function loadLists() {
    try {
      setListsLoading(true); setListsError("");
      const data = await getLists();
      setLists(data);
      if (data.length === 0) { setSelectedListId(null); }
      else if (!selectedListId || !data.some((x) => x.id === selectedListId)) { setSelectedListId(data[0].id); }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setListsError(message);
      if (message.includes("Not authenticated") || message.includes("401")) { clearToken(); onLogout(); }
    } finally { setListsLoading(false); }
  }

  useEffect(() => { loadLists(); }, []);

  return (
    <div style={appShellStyle}>
      <header style={topbarStyle}>
        <div style={topbarInnerStyle}>
          <div style={topbarLeftStyle}>
            <div style={topbarLogoStyle}>Options Dashboard</div>
            <nav style={topbarNavStyle}>
              <button type="button" onClick={() => setActivePage("dashboard")} style={activePage === "dashboard" ? topbarNavButtonActiveStyle : topbarNavButtonStyle}>Dashboard</button>
              <button type="button" onClick={() => setActivePage("watchlists")} style={activePage === "watchlists" ? topbarNavButtonActiveStyle : topbarNavButtonStyle}>Watchlists</button>
            </nav>
          </div>
          <div style={topbarRightStyle}>
            <button onClick={onLogout} style={topbarLogoutButtonStyle}>Log out</button>
          </div>
        </div>
      </header>
      <main style={contentAreaStyle}>
        <div style={contentInnerStyle}>
          {activePage === "dashboard" ? (
            <WatchlistsWorkspacePage lists={lists} selectedListId={selectedListId} setSelectedListId={setSelectedListId} listsLoading={listsLoading} listsError={listsError} onOpenWatchlistsPage={() => setActivePage("watchlists")} />
          ) : (
            <WatchlistsManagerPage lists={lists} refreshLists={loadLists} listsLoading={listsLoading} listsError={listsError} />
          )}
        </div>
      </main>
    </div>
  );
}

function LoginScreen({ onLoginSuccess }: { onLoginSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      setLoading(true); setError("");
      const data = await login(username, password);
      saveToken(data.access_token);
      onLoginSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally { setLoading(false); }
  }

  return (
    <div style={loginPageStyle}>
      <div style={loginCardStyle}>
        <div style={loginBrandStyle}>Options Dashboard</div>
        <h1 style={loginTitleStyle}>Sign in</h1>
        <p style={loginSubtitleStyle}>Use your account to access live watchlists and saved layouts.</p>
        <form onSubmit={handleSubmit} style={loginFormStyle}>
          <div style={fieldGroupStyle}>
            <label style={labelStyle}>Email / Username</label>
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} style={inputStyle} placeholder="Enter your email or username" />
          </div>
          <div style={fieldGroupStyle}>
            <label style={labelStyle}>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle} placeholder="Enter your password" />
          </div>
          {error && <p style={loginErrorStyle}>Error: {error}</p>}
          <button type="submit" style={loginButtonStyle} disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}

type WatchlistsWorkspacePageProps = {
  lists: Watchlist[]; selectedListId: number | null;
  setSelectedListId: React.Dispatch<React.SetStateAction<number | null>>;
  listsLoading: boolean; listsError: string; onOpenWatchlistsPage: () => void;
};

function WatchlistsWorkspacePage({ lists, selectedListId, setSelectedListId, listsLoading, listsError, onOpenWatchlistsPage }: WatchlistsWorkspacePageProps) {
  const [quotes, setQuotes] = useState<WatchlistQuote[]>([]);
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesError, setQuotesError] = useState("");
  const [openMenu, setOpenMenu] = useState<ToolbarMenuKey>(null);
  const [visibleColumns, setVisibleColumns] = useState<VisibleColumnsState>(defaultVisibleColumns);
  const [columnOrder, setColumnOrder] = useState<ColumnKey[]>(defaultColumnOrder);
  const [filters, setFilters] = useState<WatchlistFiltersState>(defaultFilters);
  const [sortOption, setSortOption] = useState("symbol-asc");
  const [optionsControls, setOptionsControls] = useState<OptionsControlsState>(defaultOptionsControls);
  const [draggedColumnKey, setDraggedColumnKey] = useState<ColumnKey | null>(null);
  const [dragOverColumnKey, setDragOverColumnKey] = useState<ColumnKey | null>(null);
  const [toolbarCollapsed, setToolbarCollapsed] = useState<boolean>(() => {
    try { const raw = localStorage.getItem(TOOLBAR_COLLAPSED_STORAGE_KEY); return raw ? JSON.parse(raw) === true : true; }
    catch { return true; }
  });
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => {
    const defaultView: SavedView = { id: "default", name: "Default", columns: defaultVisibleColumns, columnOrder: defaultColumnOrder, filters: defaultFilters, sort: "symbol-asc", optionsControls: defaultOptionsControls };
    try {
      const raw = localStorage.getItem(SAVED_VIEWS_STORAGE_KEY);
      if (!raw) return [defaultView];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed) || parsed.length === 0) return [defaultView];
      return parsed.map((view) => ({
        id: typeof view?.id === "string" ? view.id : crypto.randomUUID(),
        name: typeof view?.name === "string" ? view.name : "Saved View",
        columns: { ...defaultVisibleColumns, ...(view?.columns ?? {}) },
        columnOrder: Array.isArray(view?.columnOrder) && view.columnOrder.length > 0 ? normalizeColumnOrder(view.columnOrder as ColumnKey[]) : defaultColumnOrder,
        filters: { ...defaultFilters, ...(view?.filters ?? {}) },
        sort: typeof view?.sort === "string" ? view.sort : "symbol-asc",
        optionsControls: { ...defaultOptionsControls, ...(view?.optionsControls ?? {}) },
      }));
    } catch { return [defaultView]; }
  });
  const [activeViewId, setActiveViewId] = useState<string>("default");
  const columnsMenuRef = useRef<HTMLDivElement | null>(null);
  const filterMenuRef = useRef<HTMLDivElement | null>(null);
  const sortMenuRef = useRef<HTMLDivElement | null>(null);
  const viewMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { localStorage.setItem(SAVED_VIEWS_STORAGE_KEY, JSON.stringify(savedViews)); }, [savedViews]);
  useEffect(() => { localStorage.setItem(TOOLBAR_COLLAPSED_STORAGE_KEY, JSON.stringify(toolbarCollapsed)); }, [toolbarCollapsed]);
  useEffect(() => {
    setVisibleColumns(defaultVisibleColumns); setColumnOrder(defaultColumnOrder); setFilters(defaultFilters);
    setSortOption("symbol-asc"); setOptionsControls(defaultOptionsControls); setQuotes([]);
    setQuotesError(""); setOpenMenu(null); setActiveViewId("default");
    setDraggedColumnKey(null); setDragOverColumnKey(null);
  }, [selectedListId]);

  useEffect(() => {
    function handleDocumentClick(event: MouseEvent) {
      const target = event.target as Node;
      const refs = [columnsMenuRef.current, filterMenuRef.current, sortMenuRef.current, viewMenuRef.current];
      if (!refs.some((ref) => ref?.contains(target))) setOpenMenu(null);
    }
    document.addEventListener("mousedown", handleDocumentClick);
    return () => document.removeEventListener("mousedown", handleDocumentClick);
  }, []);

  async function loadQuotesForList(listId: number): Promise<void> {
    setQuotesLoading(true); setQuotesError("");
    try {
      const data = await getWatchlistQuotes(listId);
      setQuotes(Array.isArray(data) ? data : []);
    } catch (err) {
      setQuotesError(err instanceof Error ? err.message : "Failed to load quotes");
      setQuotes([]);
    } finally { setQuotesLoading(false); }
  }

  useEffect(() => {
    if (!selectedListId) { setQuotes([]); setQuotesError(""); setQuotesLoading(false); return; }
    const listId = selectedListId; let cancelled = false;
    async function load() { if (cancelled) return; await loadQuotesForList(listId); }
    load();
    const id = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [selectedListId]);

  function getDisplayOptionData(quote: WatchlistQuote) {
    const strike = quote.strike ?? null;
    const expiry = quote.expiry ?? null;
    const optionSide = quote.option_side ?? null;
    const premium = quote.premium ?? null;
    const returnPercent = quote.return_percent ?? null;
    const delta = quote.delta ?? null;
    const gamma = quote.gamma ?? null;
    const theta = quote.theta ?? null;
    const vega = quote.vega ?? null;
    const moneyness: MoneynessState =
      quote.moneyness === "ITM" || quote.moneyness === "ATM" || quote.moneyness === "OTM"
        ? quote.moneyness : "-";
    const optionSideLabel: "Call" | "Put" | "Mixed" =
      optionSide === "Call" ? "Call" : optionSide === "Put" ? "Put" : "Mixed";
    const hasOption = strike !== null && expiry !== null && premium !== null;

    return {
      strike, expiry, optionSideLabel, premium, returnPercent,
      delta, gamma, theta, vega, rho: null,
      moneyness, ma20: null, ma30: null, ma50: null, ma200: null,
      underlyingPrice: quote.last_price,
      hasOption,
      note: hasOption ? "Live option loaded" :
        quote.status === "pending" ? "Cache warming up..." : "Options unavailable",
    };
  }

  const filteredAndSortedQuotes = useMemo(() => {
    const minP = toSafeNumber(filters.minPrice);
    const minC = toSafeNumber(filters.minChangePercent);
    return [...quotes].filter((q) => {
      if (minP !== null && (toSafeNumber(q.last_price) === null || (toSafeNumber(q.last_price) ?? 0) <= minP)) return false;
      if (minC !== null && (toSafeNumber(q.change_percent) === null || (toSafeNumber(q.change_percent) ?? 0) <= minC)) return false;
      if (filters.status !== "all" && String(q.status ?? "").toLowerCase() !== filters.status) return false;
      return true;
    }).sort((a, b) => {
      const [col, dir] = sortOption.split("-");
      const m = dir === "asc" ? 1 : -1;
      if (col === "symbol") return compareValues(a.symbol ?? "", b.symbol ?? "") * m;
      if (col === "price") return compareValues(toSafeNumber(a.last_price) ?? Number.NEGATIVE_INFINITY, toSafeNumber(b.last_price) ?? Number.NEGATIVE_INFINITY) * m;
      if (col === "updated") return compareValues(a.updated_at ?? "", b.updated_at ?? "") * m;
      const dA = getDisplayOptionData(a), dB = getDisplayOptionData(b);
      switch (col) {
        case "strike": return compareValues(dA.strike, dB.strike) * m;
        case "premium": return compareValues(dA.premium, dB.premium) * m;
        case "returnPercent": return compareValues(dA.returnPercent, dB.returnPercent) * m;
        case "delta": return compareValues(dA.delta, dB.delta) * m;
        case "gamma": return compareValues(dA.gamma, dB.gamma) * m;
        case "theta": return compareValues(dA.theta, dB.theta) * m;
        case "vega": return compareValues(dA.vega, dB.vega) * m;
        case "moneyness": return compareValues(getMoneynessRank(dA.moneyness), getMoneynessRank(dB.moneyness)) * m;
        default: return 0;
      }
    });
  }, [quotes, filters, sortOption, optionsControls]);

  const orderedVisibleColumns = useMemo(() => columnOrder.filter((k) => visibleColumns[k]), [columnOrder, visibleColumns]);

  function getSortKeyForColumn(k: ColumnKey): string | null {
    switch (k) {
      case "symbol": case "price": case "strike": case "expiry": case "optionSide":
      case "premium": case "returnPercent": case "delta": case "gamma": case "theta":
      case "vega": case "rho": case "moneyness": case "change": case "changePercent": case "updated": return k;
      default: return null;
    }
  }

  function getSortIndicatorForColumn(k: ColumnKey, s: string): string {
    const sk = getSortKeyForColumn(k); if (!sk) return "";
    const [ck, cd] = s.split("-"); if (ck !== sk) return "";
    return cd === "asc" ? " ▲" : " ▼";
  }

  function moveColumn(dk: ColumnKey, tk: ColumnKey) {
    if (dk === tk) return;
    setColumnOrder((prev) => {
      const next = [...prev]; const fi = next.indexOf(dk); const ti = next.indexOf(tk);
      if (fi === -1 || ti === -1) return prev;
      next.splice(fi, 1); next.splice(ti, 0, dk); return next;
    });
  }

  function renderCell(columnKey: ColumnKey, quote: WatchlistQuote, isFirst: boolean) {
    const bs = isFirst ? stickyFirstBodyCellStyle : bodyCellStyle;
    const od = getDisplayOptionData(quote);
    switch (columnKey) {
      case "symbol": return <td style={{ ...bs, fontWeight: 800 }}>{quote.symbol}</td>;
      case "price": return <td style={{ ...bs, fontWeight: 800 }}>{formatNumber(toSafeNumber(quote.last_price))}</td>;
      case "strike": return <td style={bs}><span style={{ fontWeight: 700 }}>{formatNumber(od.strike)}</span></td>;
      case "expiry": return <td style={bs}><span style={{ fontWeight: 700 }}>{od.expiry ?? "-"}</span></td>;
      case "optionSide": return <td style={bs}><span style={optionSideBadgeStyle}>{od.optionSideLabel === "Mixed" ? "-" : od.optionSideLabel}</span></td>;
      case "premium": return <td style={{ ...bs, fontWeight: 700 }}>{formatCurrency(od.premium)}</td>;
      case "returnPercent": return <td style={{ ...bs, fontWeight: 700, color: getChangeColor(od.returnPercent) }}>{formatSignedPercent(od.returnPercent)}</td>;
      case "delta": return <td style={bs}>{formatMetric(od.delta, 3)}</td>;
      case "gamma": return <td style={bs}>{formatMetric(od.gamma, 3)}</td>;
      case "theta": return <td style={{ ...bs, color: (od.theta ?? 0) < 0 ? "#991b1b" : "#0f172a" }}>{formatSignedMetric(od.theta, 3)}</td>;
      case "vega": return <td style={bs}>{formatMetric(od.vega, 3)}</td>;
      case "rho": return <td style={bs}>-</td>;
      case "moneyness": return <td style={bs}><span style={{ ...moneynessBadgeStyle, background: od.moneyness === "ITM" ? "#fee2e2" : od.moneyness === "ATM" ? "#fef3c7" : od.moneyness === "OTM" ? "#dcfce7" : "#e2e8f0", color: od.moneyness === "ITM" ? "#991b1b" : od.moneyness === "ATM" ? "#92400e" : od.moneyness === "OTM" ? "#166534" : "#475569" }}>{od.moneyness}</span></td>;
      case "ma20": case "ma30": case "ma50": case "ma200": return <td style={bs}>-</td>;
      case "change": return <td style={{ ...bs, fontWeight: 700, color: getChangeColor(toSafeNumber(quote.change)) }}>{formatSignedNumber(toSafeNumber(quote.change))}</td>;
      case "changePercent": return <td style={{ ...bs, fontWeight: 700, color: getChangeColor(toSafeNumber(quote.change_percent)) }}>{formatSignedPercent(toSafeNumber(quote.change_percent))}</td>;
      case "status": return <td style={bs}><span style={{ ...statusBadgeStyle, backgroundColor: quote.status === "ok" ? "#dcfce7" : quote.status === "pending" ? "#fef3c7" : "#fee2e2", color: quote.status === "ok" ? "#166534" : quote.status === "pending" ? "#92400e" : "#991b1b" }}>{quote.status ?? "-"}</span></td>;
      case "updated": return <td style={bs}>{formatTimeShort(quote.updated_at)}</td>;
      case "note": {
        const isPending = quote.status === "pending";
        return <td style={{ ...bs, color: isPending ? "#92400e" : bs.color }}>{od.note}</td>;
      }
      default: return <td style={bs}>-</td>;
    }
  }

  function renderColumnsMenuSection(title: string, options: Array<{ key: ColumnKey; label: string }>) {
    return (
      <div style={columnsMenuSectionStyle}>
        <div style={columnsMenuSectionTitleStyle}>{title}</div>
        <div style={columnsPanelGridStyle}>
          {options.map((col) => (
            <label key={col.key} style={columnToggleLabelStyle}>
              <input type="checkbox" checked={visibleColumns[col.key]} onChange={(e) => setVisibleColumns((prev) => ({ ...prev, [col.key]: e.target.checked }))} />
              {col.label}
            </label>
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <div style={headerRowStyle}>
        <div>
          <h1 style={pageTitleStyle}>Dashboard</h1>
          <p style={pageSubtitleStyle}>Live options workspace — data refreshes every 60 seconds</p>
        </div>
      </div>

      <Panel>
        <div style={toolbarShellStyle}>
          <div style={toolbarPrimaryRowStyle}>
            <div style={toolbarPrimaryLeftStyle}>
              <div style={toolbarControlGroupStyle}>
                <label htmlFor="watchlist-select" style={labelStyle}>Watchlist</label>
                <select id="watchlist-select" value={selectedListId ?? ""} onChange={(e) => setSelectedListId(e.target.value ? Number(e.target.value) : null)} style={compactSelectStyle} disabled={listsLoading || lists.length === 0}>
                  {lists.length === 0 ? <option value="">No watchlists found</option> : lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </div>

              <div style={toolbarMenuAnchorStyle} ref={viewMenuRef}>
                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>View</label>
                  <button type="button" style={openMenu === "view" ? { ...viewButtonStyle, ...secondaryButtonActiveStyle } : viewButtonStyle} onClick={() => setOpenMenu((p) => (p === "view" ? null : "view"))}>
                    {`View: ${savedViews.find((v) => v.id === activeViewId)?.name ?? "Default"}`} {openMenu === "view" ? "▲" : "▼"}
                  </button>
                </div>
                {openMenu === "view" && (
                  <div style={floatingMenuStyle}>
                    <div style={floatingMenuHeaderStyle}><h3 style={floatingMenuTitleStyle}>Saved Views</h3><p style={floatingMenuSubtitleStyle}>Quickly switch between dashboard layouts</p></div>
                    <div style={floatingScrollableContentStyle}><div style={sortOptionsGridStyle}>
                      {savedViews.map((v) => (
                        <button key={v.id} type="button" style={activeViewId === v.id ? sortOptionActiveStyle : sortOptionButtonStyle} onClick={() => { setVisibleColumns(v.columns); setColumnOrder(normalizeColumnOrder(v.columnOrder ?? defaultColumnOrder)); setFilters(v.filters); setSortOption(v.sort); setOptionsControls({ ...defaultOptionsControls, ...(v.optionsControls ?? {}) }); setActiveViewId(v.id); setOpenMenu(null); }}>{v.name}</button>
                      ))}
                    </div></div>
                    <div style={floatingMenuFooterStyle}><button type="button" style={secondaryButtonStyle} onClick={() => setOpenMenu(null)}>Manage Views</button></div>
                  </div>
                )}
              </div>

              <div style={toolbarPrimaryActionsStyle}>
                <button type="button" style={secondaryButtonStyle} onClick={() => { if (selectedListId) loadQuotesForList(selectedListId); }} disabled={!selectedListId || quotesLoading}>
                  {quotesLoading ? "Refreshing..." : "Refresh"}
                </button>
              </div>
            </div>

            <div style={toolbarPrimaryRightStyle}>
              <button type="button" style={secondaryButtonStyle} onClick={() => { setToolbarCollapsed((p) => !p); setOpenMenu(null); }}>
                {toolbarCollapsed ? "Expand Toolbar" : "Collapse Toolbar"}
              </button>
            </div>
          </div>

          {!toolbarCollapsed && (
            <div style={toolbarSecondaryRowStyle}>
              <div style={toolbarSecondaryGroupStyle}>
                <div style={toolbarMenuAnchorStyle} ref={columnsMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Columns</label>
                    <button type="button" style={openMenu === "columns" ? secondaryButtonActiveStyle : secondaryButtonStyle} onClick={() => setOpenMenu((p) => (p === "columns" ? null : "columns"))}>Columns {openMenu === "columns" ? "▲" : "▼"}</button>
                  </div>
                  {openMenu === "columns" && (
                    <div style={floatingMenuStyleClampedWide}>
                      <div style={floatingMenuHeaderStyle}><div><h3 style={floatingMenuTitleStyle}>Visible Columns</h3><p style={floatingMenuSubtitleStyle}>Choose which columns appear in the workspace</p></div></div>
                      <div style={floatingScrollableContentStyleWide}>
                        {renderColumnsMenuSection("Core", coreColumnOptions)}
                        {renderColumnsMenuSection("Options", optionsColumnOptions)}
                        {renderColumnsMenuSection("Greeks", greeksColumnOptions)}
                        {renderColumnsMenuSection("Moving Averages", movingAverageColumnOptions)}
                      </div>
                    </div>
                  )}
                </div>

                <div style={toolbarMenuAnchorStyle} ref={sortMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Sort</label>
                    <button type="button" style={openMenu === "sort" ? secondaryButtonActiveStyle : secondaryButtonStyle} onClick={() => setOpenMenu((p) => (p === "sort" ? null : "sort"))}>Sort {openMenu === "sort" ? "▲" : "▼"}</button>
                  </div>
                  {openMenu === "sort" && (
                    <div style={floatingMenuStyleClamped}>
                      <div style={floatingMenuHeaderStyle}><div><h3 style={floatingMenuTitleStyle}>Sort Rows</h3><p style={floatingMenuSubtitleStyle}>Choose how the workspace is ordered</p></div></div>
                      <div style={floatingScrollableContentStyle}><div style={sortOptionsGridStyle}>
                        {[["symbol-asc","Symbol A → Z"],["symbol-desc","Symbol Z → A"],["price-asc","Price Low → High"],["price-desc","Price High → Low"],["strike-asc","Strike Low → High"],["strike-desc","Strike High → Low"],["premium-asc","Premium Low → High"],["premium-desc","Premium High → Low"],["returnPercent-asc","Return % Low → High"],["returnPercent-desc","Return % High → Low"],["delta-asc","Delta Low → High"],["delta-desc","Delta High → Low"],["updated-asc","Updated Oldest → Newest"],["updated-desc","Updated Newest → Oldest"]].map(([v, l]) => (
                          <button key={v} type="button" style={sortOption === v ? sortOptionActiveStyle : sortOptionButtonStyle} onClick={() => { setSortOption(v); setOpenMenu(null); }}>{l}</button>
                        ))}
                      </div></div>
                    </div>
                  )}
                </div>

                <div style={toolbarMenuAnchorStyle} ref={filterMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Filter</label>
                    <button type="button" style={openMenu === "filter" ? secondaryButtonActiveStyle : secondaryButtonStyle} onClick={() => setOpenMenu((p) => (p === "filter" ? null : "filter"))}>Filter {openMenu === "filter" ? "▲" : "▼"}</button>
                  </div>
                  {openMenu === "filter" && (
                    <div style={floatingMenuStyleClamped}>
                      <div style={floatingMenuHeaderStyle}><div><h3 style={floatingMenuTitleStyle}>Filters</h3><p style={floatingMenuSubtitleStyle}>Narrow the workspace</p></div></div>
                      <div style={floatingScrollableContentStyle}><div style={filtersPanelGridStyle}>
                        <div style={fieldGroupFullStyle}><label style={labelStyle}>Price greater than</label><input type="number" step="0.01" value={filters.minPrice} onChange={(e) => setFilters((p) => ({ ...p, minPrice: e.target.value }))} style={inputStyle} placeholder="Example: 20" /></div>
                        <div style={fieldGroupFullStyle}><label style={labelStyle}>Status</label><select value={filters.status} onChange={(e) => setFilters((p) => ({ ...p, status: e.target.value }))} style={selectStyle}><option value="all">All</option><option value="ok">ok</option><option value="pending">pending</option><option value="error">error</option></select></div>
                      </div></div>
                      <div style={floatingMenuFooterStyle}>
                        <button type="button" style={secondaryButtonStyle} onClick={() => setFilters(defaultFilters)}>Clear Filters</button>
                        <div style={toolbarRightInfoStyle}><div style={smallMutedDarkStyle}>Matching rows</div><div style={toolbarRightValueStyle}>{filteredAndSortedQuotes.length}</div></div>
                      </div>
                    </div>
                  )}
                </div>

                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>Reset</label>
                  <button type="button" style={secondaryButtonStyle} onClick={() => { setVisibleColumns(defaultVisibleColumns); setColumnOrder(defaultColumnOrder); setFilters(defaultFilters); setSortOption("symbol-asc"); setOptionsControls(defaultOptionsControls); setActiveViewId("default"); setOpenMenu(null); }} disabled={!selectedListId}>Reset</button>
                </div>
              </div>
            </div>
          )}
        </div>
      </Panel>

      {(listsError || quotesError) && (
        <Panel><div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {listsError && <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>Error: {listsError}</p>}
          {quotesError && <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>Error: {quotesError}</p>}
        </div></Panel>
      )}

      <Panel>
        <div style={panelHeaderStyle}>
          <div><h2 style={panelTitleStyle}>Live Watchlist</h2><p style={panelSubtitleStyle}>Data pre-fetched every 60 seconds • loads instantly from cache</p></div>
          <div style={panelHeaderActionsStyle}>
            <button type="button" style={iconButtonStyle} onMouseEnter={(e) => { e.currentTarget.style.background = "#f8fafc"; e.currentTarget.style.borderColor = "#94a3b8"; }} onMouseLeave={(e) => { e.currentTarget.style.background = "#ffffff"; e.currentTarget.style.borderColor = "#e2e8f0"; }} onClick={() => {
              const rawName = window.prompt("Save view as", "New View"); const name = rawName?.trim(); if (!name) return;
              const existing = savedViews.find((v) => v.name.toLowerCase() === name.toLowerCase());
              if (existing) {
                if (!window.confirm(`A view named "${existing.name}" already exists. Overwrite it?`)) return;
                setActiveViewId(existing.id);
                setSavedViews((p) => p.map((v) => v.id === existing.id ? { ...v, name, columns: visibleColumns, columnOrder, filters, sort: sortOption, optionsControls } : v));
                return;
              }
              const nv: SavedView = { id: crypto.randomUUID(), name, columns: visibleColumns, columnOrder, filters, sort: sortOption, optionsControls };
              setActiveViewId(nv.id); setSavedViews((p) => [...p, nv]);
            }} title="Save View" aria-label="Save View"><img src={saveIcon} alt="Save View" style={iconImageStyle} /></button>
            <button type="button" style={iconButtonStyle} onMouseEnter={(e) => { e.currentTarget.style.background = "#f8fafc"; e.currentTarget.style.borderColor = "#94a3b8"; }} onMouseLeave={(e) => { e.currentTarget.style.background = "#ffffff"; e.currentTarget.style.borderColor = "#e2e8f0"; }} onClick={onOpenWatchlistsPage} title="Edit Watchlist" aria-label="Edit Watchlist"><img src={editIcon} alt="Edit Watchlist" style={iconImageStyle} /></button>
          </div>
        </div>

        <div style={{ marginBottom: "12px", color: "#64748b", fontSize: "12px", fontWeight: 700 }}>Drag column headers to reorder them.</div>

        {!selectedListId ? <p style={{ margin: 0 }}>Select a watchlist to load quotes.</p>
          : quotesLoading && quotes.length === 0 ? <p style={{ margin: 0 }}>Loading...</p>
          : !Array.isArray(quotes) || quotes.length === 0 ? <p style={{ margin: 0 }}>No quotes found for this watchlist.</p>
          : filteredAndSortedQuotes.length === 0 ? <p style={{ margin: 0 }}>No rows match the current filters.</p>
          : (
          <div style={watchlistTableShellStyle}><div style={watchlistTableWrapStyle}>
            <table style={tableStyle}>
              <thead><tr>
                {orderedVisibleColumns.map((ck, idx) => {
                  const label = dashboardColumnOptions.find((c) => c.key === ck)?.label ?? ck;
                  const hs = idx === 0 ? stickyFirstHeaderCellStyle : stickyHeaderCellStyle;
                  return (
                    <th key={ck} draggable
                      onDragStart={() => { setDraggedColumnKey(ck); setDragOverColumnKey(null); }}
                      onDragOver={(e) => { e.preventDefault(); if (draggedColumnKey && draggedColumnKey !== ck) setDragOverColumnKey(ck); }}
                      onDragLeave={() => { if (dragOverColumnKey === ck) setDragOverColumnKey(null); }}
                      onDrop={() => { if (!draggedColumnKey) return; moveColumn(draggedColumnKey, ck); setDraggedColumnKey(null); setDragOverColumnKey(null); }}
                      onDragEnd={() => { setDraggedColumnKey(null); setDragOverColumnKey(null); }}
                      onDoubleClick={() => { const sk = getSortKeyForColumn(ck); if (!sk) return; setSortOption((p) => { const [ck2, cd] = p.split("-"); return ck2 === sk ? `${sk}-${cd === "asc" ? "desc" : "asc"}` : `${sk}-asc`; }); }}
                      style={{ ...hs, cursor: "grab", opacity: draggedColumnKey === ck ? 0.55 : 1, boxShadow: draggedColumnKey === ck ? "inset 0 0 0 2px #94a3b8" : dragOverColumnKey === ck ? "inset 3px 0 0 #2563eb" : "none", background: idx === 0 ? "#f8fafc" : hs.background }}
                      title="Drag to reorder • Double-click to sort"
                    >
                      <span style={columnHeaderContentStyle}><span style={columnDragHandleStyle}>⋮⋮</span><span>{label}{getSortIndicatorForColumn(ck, sortOption)}</span></span>
                    </th>
                  );
                })}
              </tr></thead>
              <tbody>
                {filteredAndSortedQuotes.map((quote, ri) => (
                  <tr key={quote.symbol} style={{ background: ri % 2 === 0 ? "#ffffff" : "#f8fafc", transition: "background 0.15s ease" }} onMouseEnter={(e) => { e.currentTarget.style.background = "#eef2f7"; }} onMouseLeave={(e) => { e.currentTarget.style.background = ri % 2 === 0 ? "#ffffff" : "#f8fafc"; }}>
                    {orderedVisibleColumns.map((ck, ci) => <React.Fragment key={`${quote.symbol}-${ck}`}>{renderCell(ck, quote, ci === 0)}</React.Fragment>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div></div>
        )}
      </Panel>
    </>
  );
}

type WatchlistsManagerPageProps = { lists: Watchlist[]; refreshLists: () => Promise<void>; listsLoading: boolean; listsError: string; };

function WatchlistsManagerPage({ lists, refreshLists, listsLoading, listsError }: WatchlistsManagerPageProps) {
  const [editorMode, setEditorMode] = useState<WatchlistEditorMode>("idle");
  const [editingListId, setEditingListId] = useState<number | null>(null);
  const [editingListName, setEditingListName] = useState("");
  const [tickerText, setTickerText] = useState("");
  const [existingTickers, setExistingTickers] = useState<TickerItem[]>([]);
  const [tickersCache, setTickersCache] = useState<Record<number, TickerItem[]>>({});
  const [builderLoading, setBuilderLoading] = useState(false);
  const [savingBuilder, setSavingBuilder] = useState(false);
  const [deletingWatchlist, setDeletingWatchlist] = useState(false);
  const [pageError, setPageError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  function resetBuilder() { setEditorMode("idle"); setEditingListId(null); setEditingListName(""); setTickerText(""); setExistingTickers([]); }
  function openCreateBuilder() { setEditorMode("create"); setEditingListId(null); setEditingListName(""); setTickerText(""); setExistingTickers([]); setPageError(""); setSuccessMessage(""); }

  async function openEditBuilder(list: Watchlist) {
    setEditorMode("edit"); setEditingListId(list.id); setEditingListName(list.name); setPageError(""); setSuccessMessage("");
    const cached = tickersCache[list.id];
    if (cached) { setExistingTickers(cached); setTickerText(cached.map((t) => t.symbol).join("\n")); return; }
    try {
      setBuilderLoading(true);
      const tickers = await getTickers(list.id);
      setExistingTickers(tickers); setTickerText(tickers.map((t) => t.symbol).join("\n"));
      setTickersCache((p) => ({ ...p, [list.id]: tickers }));
    } catch (err) { setPageError(err instanceof Error ? err.message : "Failed to load watchlist"); }
    finally { setBuilderLoading(false); }
  }

  async function handleDeleteWatchlist() {
    if (!editingListId || editorMode !== "edit") return;
    if (!window.confirm(`Delete watchlist "${editingListName}"?\n\nThis will remove the watchlist and its tickers.`)) return;
    try {
      setDeletingWatchlist(true); setPageError(""); setSuccessMessage("");
      await deleteList(editingListId); await refreshLists();
      setTickersCache((p) => { const n = { ...p }; delete n[editingListId!]; return n; });
      const dn = editingListName; resetBuilder(); setSuccessMessage(`Deleted watchlist: ${dn}`);
    } catch (err) { setPageError(err instanceof Error ? err.message : "Failed to delete watchlist"); }
    finally { setDeletingWatchlist(false); }
  }

  async function handleSaveBuilder(e: React.FormEvent) {
    e.preventDefault();
    try {
      setSavingBuilder(true); setPageError(""); setSuccessMessage("");
      const parsed = tickerText.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
      const unique = Array.from(new Set(parsed));
      if (editorMode === "create") {
        const name = editingListName.trim(); if (!name) { setPageError("Watchlist name is required."); return; }
        const created = await createList(name);
        for (const s of unique) await createTicker(created.id, s);
        await refreshLists(); await openEditBuilder(created); setSuccessMessage(`Created watchlist: ${created.name}`); return;
      }
      if (editorMode === "edit" && editingListId) {
        const name = editingListName.trim(); if (!name) { setPageError("Watchlist name is required."); return; }
        const current = lists.find((l) => l.id === editingListId); if (!current) { setPageError("Watchlist not found."); return; }
        if (current.name !== name) await updateList(editingListId, name);
        const cs = existingTickers.map((t) => t.symbol.toUpperCase());
        const ids = new Map(existingTickers.map((t) => [t.symbol.toUpperCase(), t.id]));
        for (const s of unique.filter((s) => !cs.includes(s))) await createTicker(editingListId, s);
        for (const s of cs.filter((s) => !unique.includes(s))) { const id = ids.get(s); if (id) await deleteTicker(editingListId, id); }
        await refreshLists();
        const rt = await getTickers(editingListId);
        setTickersCache((p) => ({ ...p, [editingListId!]: rt })); setExistingTickers(rt); setTickerText(rt.map((t) => t.symbol).join("\n"));
        setSuccessMessage(`Saved watchlist: ${name}`);
      }
    } catch (err) { setPageError(err instanceof Error ? err.message : "Failed to save watchlist"); }
    finally { setSavingBuilder(false); }
  }

  return (
    <>
      <div style={headerRowStyle}><div><h1 style={pageTitleStyle}>Watchlists</h1><p style={pageSubtitleStyle}>Create and manage your watchlists</p></div></div>
      {(pageError || successMessage || listsError) && (
        <Panel><div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {pageError && <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>Error: {pageError}</p>}
          {listsError && <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>Error: {listsError}</p>}
          {successMessage && <p style={{ margin: 0, color: "#166534", fontWeight: 600 }}>{successMessage}</p>}
        </div></Panel>
      )}
      <div style={watchlistAdminGridStyle}>
        <Panel>
          <div style={panelHeaderStyle}><div>
            <h2 style={panelTitleStyle}>{editorMode === "create" ? "Create Watchlist" : editorMode === "edit" ? "Edit Watchlist" : "Watchlist Builder"}</h2>
            <p style={panelSubtitleStyle}>{editorMode === "idle" ? "Create a new watchlist or click an existing one to edit it" : editorMode === "create" ? "Enter a name and all tickers at once" : "Edit the watchlist name and tickers, then save"}</p>
          </div></div>
          {editorMode === "idle" ? (
            <button type="button" style={primaryButtonStyle} onClick={openCreateBuilder}>Create Watchlist</button>
          ) : (
            <form onSubmit={handleSaveBuilder} style={loginFormStyle}>
              <div style={fieldGroupFullStyle}><label style={labelStyle}>Watchlist Name</label><input type="text" value={editingListName} onChange={(e) => setEditingListName(e.target.value)} style={inputStyle} placeholder="Example: Wheel Strategy" disabled={savingBuilder || deletingWatchlist} /></div>
              <div style={fieldGroupFullStyle}><label style={labelStyle}>Tickers</label><textarea value={tickerText} onChange={(e) => setTickerText(e.target.value)} style={textareaStyle} placeholder={"AAPL\nMSFT\nNVDA\nTSLL"} disabled={savingBuilder || deletingWatchlist} /></div>
              <div style={editorActionsStyle}>
                <button type="submit" style={primaryButtonStyle} disabled={savingBuilder || deletingWatchlist}>{savingBuilder ? "Saving..." : "Save Watchlist"}</button>
                <button type="button" style={secondaryButtonStyle} onClick={() => { resetBuilder(); setPageError(""); }} disabled={savingBuilder || deletingWatchlist}>Cancel</button>
              </div>
              {editorMode === "edit" && editingListId && (
                <div style={editorActionsStyle}><button type="button" onClick={handleDeleteWatchlist} disabled={savingBuilder || deletingWatchlist} style={dangerButtonStyle}>{deletingWatchlist ? "Deleting..." : "Delete Watchlist"}</button></div>
              )}
            </form>
          )}
        </Panel>
        <Panel>
          <div style={panelHeaderStyle}><div><h2 style={panelTitleStyle}>Manage Watchlists</h2></div></div>
          {builderLoading ? <p style={{ margin: 0 }}>Loading watchlist...</p>
            : listsLoading ? <p style={{ margin: 0 }}>Loading watchlists...</p>
            : lists.length === 0 ? <p style={{ margin: 0 }}>No watchlists found.</p>
            : <div style={listCardsWrapStyle}>{lists.map((l) => (
              <button key={l.id} type="button" onClick={() => openEditBuilder(l)} style={{ ...watchlistCardButtonStyle, borderColor: l.id === editingListId ? "#0f172a" : "#e2e8f0", background: l.id === editingListId ? "#f8fafc" : "#ffffff" }}>
                <div><div style={watchlistNameStyle}>{l.name}</div></div>
              </button>
            ))}</div>}
        </Panel>
      </div>
    </>
  );
}

function Panel({ children }: { children: React.ReactNode }) { return <section style={panelStyle}>{children}</section>; }

function normalizeColumnOrder(order: ColumnKey[]): ColumnKey[] {
  const next = [...order];
  for (const k of defaultColumnOrder) if (!next.includes(k)) next.push(k);
  return next.filter((k, i) => next.indexOf(k) === i);
}

function compareValues(a: string | number | null | undefined, b: string | number | null | undefined): number {
  if (a == null) return b == null ? 0 : -1; if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a > b ? 1 : a < b ? -1 : 0;
  const as = String(a), bs = String(b); return as > bs ? 1 : as < bs ? -1 : 0;
}

function toSafeNumber(v: unknown): number | null {
  if (v == null) return null; if (typeof v === "number") return Number.isNaN(v) ? null : v;
  const c = String(v).replace(/[^0-9.-]/g, ""); if (!c) return null;
  const p = Number(c); return Number.isNaN(p) ? null : p;
}

function formatNumber(v: number | null | undefined): string { return v == null ? "-" : v.toFixed(2); }
function formatCurrency(v: number | null | undefined): string { return v == null ? "-" : `$${v.toFixed(2)}`; }
function formatMetric(v: number | null | undefined, d = 2): string { return v == null ? "-" : v.toFixed(d); }
function formatSignedMetric(v: number | null | undefined, d = 2): string { return v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`; }
function formatSignedNumber(v: number | null | undefined): string { return v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`; }
function formatSignedPercent(v: number | null | undefined): string { return v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`; }
function formatTimeShort(v: string | null | undefined): string { return v ? new Date(v).toLocaleTimeString() : "-"; }
function getChangeColor(v: number | null | undefined): string { return v == null ? "#64748b" : v > 0 ? "#166534" : v < 0 ? "#991b1b" : "#475569"; }
function getMoneynessRank(v: MoneynessState): number { return v === "ITM" ? 0 : v === "ATM" ? 1 : v === "OTM" ? 2 : 3; }

const loginPageStyle: React.CSSProperties = { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg, #0f172a 0%, #111827 45%, #1e293b 100%)", padding: "24px" };
const loginCardStyle: React.CSSProperties = { width: "100%", maxWidth: "440px", background: "#ffffff", borderRadius: "20px", padding: "32px", boxShadow: "0 20px 40px rgba(0,0,0,0.20)" };
const loginBrandStyle: React.CSSProperties = { fontSize: "14px", fontWeight: 800, color: "#475569", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "16px" };
const loginTitleStyle: React.CSSProperties = { margin: 0, fontSize: "34px", fontWeight: 800, color: "#0f172a" };
const loginSubtitleStyle: React.CSSProperties = { margin: "10px 0 24px 0", color: "#64748b", lineHeight: 1.5 };
const loginFormStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "16px" };
const loginErrorStyle: React.CSSProperties = { margin: 0, color: "#dc2626", fontWeight: 600 };
const loginButtonStyle: React.CSSProperties = { border: "none", borderRadius: "12px", padding: "14px 18px", background: "#0f172a", color: "#ffffff", fontSize: "15px", fontWeight: 700, cursor: "pointer" };
const appShellStyle: React.CSSProperties = { minHeight: "100vh", background: "#f1f5f9", color: "#0f172a" };
const topbarStyle: React.CSSProperties = { position: "sticky", top: 0, zIndex: 100, background: "#ffffff", borderBottom: "1px solid #e2e8f0", boxShadow: "0 4px 18px rgba(15,23,42,0.04)" };
const topbarInnerStyle: React.CSSProperties = { maxWidth: "1800px", margin: "0 auto", padding: "18px 24px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "20px" };
const topbarLeftStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "28px", flexWrap: "wrap" };
const topbarLogoStyle: React.CSSProperties = { fontSize: "24px", fontWeight: 900, letterSpacing: "-0.03em", color: "#0f172a", whiteSpace: "nowrap" };
const topbarNavStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" };
const topbarNavButtonStyle: React.CSSProperties = { border: "1px solid transparent", background: "transparent", color: "#475569", borderRadius: "12px", padding: "10px 14px", fontSize: "14px", fontWeight: 700, cursor: "pointer" };
const topbarNavButtonActiveStyle: React.CSSProperties = { ...topbarNavButtonStyle, background: "#0f172a", color: "#ffffff", border: "1px solid #0f172a" };
const topbarRightStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "14px", flexWrap: "wrap", justifyContent: "flex-end" };
const topbarLogoutButtonStyle: React.CSSProperties = { border: "1px solid #cbd5e1", background: "#ffffff", color: "#0f172a", borderRadius: "12px", padding: "10px 14px", fontWeight: 700, cursor: "pointer" };
const contentAreaStyle: React.CSSProperties = { width: "100%" };
const contentInnerStyle: React.CSSProperties = { width: "100%", maxWidth: "1800px", margin: "0 auto", padding: "28px 24px 32px 24px" };
const headerRowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "26px", gap: "16px", flexWrap: "wrap" };
const pageTitleStyle: React.CSSProperties = { margin: 0, fontSize: "36px", fontWeight: 900, letterSpacing: "-0.03em" };
const pageSubtitleStyle: React.CSSProperties = { margin: "8px 0 0 0", color: "#64748b", fontSize: "15px" };
const panelStyle: React.CSSProperties = { background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "20px", padding: "22px", boxShadow: "0 8px 24px rgba(15,23,42,0.05)", marginBottom: "16px" };
const panelHeaderStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "18px" };
const panelHeaderActionsStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" };
const iconImageStyle: React.CSSProperties = { width: "16px", height: "16px" };
const iconButtonStyle: React.CSSProperties = { width: "34px", height: "34px", border: "1px solid #e2e8f0", borderRadius: "10px", background: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" };
const panelTitleStyle: React.CSSProperties = { margin: 0, fontSize: "22px", fontWeight: 900, letterSpacing: "-0.02em" };
const panelSubtitleStyle: React.CSSProperties = { margin: "6px 0 0 0", color: "#64748b", fontSize: "14px" };
const fieldGroupStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "8px", minWidth: "240px", maxWidth: "520px" };
const fieldGroupFullStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "8px", width: "100%" };
const labelStyle: React.CSSProperties = { fontSize: "13px", fontWeight: 800, color: "#334155", letterSpacing: "0.01em" };
const inputStyle: React.CSSProperties = { padding: "14px", borderRadius: "14px", border: "1px solid #cbd5e1", fontSize: "14px", background: "#fff", outline: "none", boxShadow: "inset 0 1px 2px rgba(15,23,42,0.03)" };
const textareaStyle: React.CSSProperties = { minHeight: "220px", padding: "14px", borderRadius: "14px", border: "1px solid #cbd5e1", fontSize: "14px", background: "#fff", resize: "vertical", fontFamily: "inherit", outline: "none", boxShadow: "inset 0 1px 2px rgba(15,23,42,0.03)" };
const selectStyle: React.CSSProperties = { padding: "12px 14px", borderRadius: "14px", border: "1px solid #cbd5e1", fontSize: "14px", background: "#fff", outline: "none", boxShadow: "inset 0 1px 2px rgba(15,23,42,0.03)" };
const primaryButtonStyle: React.CSSProperties = { border: "none", borderRadius: "14px", padding: "14px 18px", background: "#0f172a", color: "#ffffff", fontSize: "15px", fontWeight: 800, cursor: "pointer", boxShadow: "0 8px 18px rgba(15,23,42,0.16)" };
const secondaryButtonStyle: React.CSSProperties = { border: "1px solid #cbd5e1", borderRadius: "12px", padding: "10px 14px", background: "#ffffff", color: "#0f172a", fontSize: "14px", fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" };
const viewButtonStyle: React.CSSProperties = { ...secondaryButtonStyle, minWidth: "180px", justifyContent: "space-between", display: "inline-flex", alignItems: "center" };
const secondaryButtonActiveStyle: React.CSSProperties = { ...secondaryButtonStyle, background: "#0f172a", color: "#ffffff", border: "1px solid #0f172a" };
const dangerButtonStyle: React.CSSProperties = { border: "1px solid #fecaca", borderRadius: "12px", padding: "10px 14px", background: "#ffffff", color: "#991b1b", fontSize: "14px", fontWeight: 800, cursor: "pointer" };
const editorActionsStyle: React.CSSProperties = { display: "flex", gap: "12px", flexWrap: "wrap" };
const listCardsWrapStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "14px" };
const watchlistCardStyle: React.CSSProperties = { border: "1px solid #e2e8f0", borderRadius: "18px", padding: "18px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "16px", boxShadow: "0 4px 14px rgba(15,23,42,0.04)" };
const watchlistCardButtonStyle: React.CSSProperties = { ...watchlistCardStyle, width: "100%", background: "#ffffff", cursor: "pointer", textAlign: "left" };
const watchlistNameStyle: React.CSSProperties = { fontSize: "18px", fontWeight: 900, color: "#0f172a", marginBottom: "4px", letterSpacing: "-0.02em" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "separate", borderSpacing: 0, background: "#ffffff" };
const bodyCellStyle: React.CSSProperties = { padding: "10px 12px", borderBottom: "1px solid #eef2f7", fontSize: "13px", color: "#0f172a", whiteSpace: "nowrap" };
const statusBadgeStyle: React.CSSProperties = { display: "inline-block", padding: "6px 10px", borderRadius: "999px", fontWeight: 800, fontSize: "12px", textTransform: "uppercase" };
const moneynessBadgeStyle: React.CSSProperties = { display: "inline-block", padding: "6px 10px", borderRadius: "999px", fontWeight: 800, fontSize: "12px", textTransform: "uppercase" };
const optionSideBadgeStyle: React.CSSProperties = { display: "inline-block", padding: "5px 10px", borderRadius: "999px", fontWeight: 800, fontSize: "12px", background: "#e2e8f0", color: "#334155" };
const toolbarShellStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "14px", minHeight: "72px" };
const toolbarPrimaryRowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "16px", flexWrap: "wrap" };
const toolbarPrimaryLeftStyle: React.CSSProperties = { display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap", minHeight: "72px", flex: 1 };
const toolbarPrimaryActionsStyle: React.CSSProperties = { display: "flex", alignItems: "flex-end", minHeight: "72px" };
const toolbarPrimaryRightStyle: React.CSSProperties = { display: "flex", alignItems: "flex-end", minHeight: "72px" };
const toolbarSecondaryRowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: "16px", flexWrap: "wrap", minHeight: "72px" };
const toolbarSecondaryGroupStyle: React.CSSProperties = { display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap", minHeight: "72px" };
const toolbarMenuAnchorStyle: React.CSSProperties = { position: "relative", display: "flex", flexDirection: "column" };
const floatingMenuStyle: React.CSSProperties = { position: "absolute", top: "calc(100% + 10px)", left: 0, minWidth: "340px", width: "min(340px, calc(100vw - 96px))", padding: "18px", borderRadius: "18px", border: "1px solid #e2e8f0", background: "#ffffff", boxShadow: "0 20px 40px rgba(15,23,42,0.16)", zIndex: 40 };
const floatingMenuStyleClamped: React.CSSProperties = { ...floatingMenuStyle, left: "auto", right: 0 };
const floatingMenuStyleClampedWide: React.CSSProperties = { ...floatingMenuStyleClamped, minWidth: "560px", width: "min(560px, calc(100vw - 96px))" };
const floatingMenuHeaderStyle: React.CSSProperties = { marginBottom: "14px" };
const floatingMenuTitleStyle: React.CSSProperties = { margin: 0, fontSize: "18px", fontWeight: 900, letterSpacing: "-0.02em", color: "#0f172a" };
const floatingMenuSubtitleStyle: React.CSSProperties = { margin: "6px 0 0 0", color: "#64748b", fontSize: "13px" };
const floatingMenuFooterStyle: React.CSSProperties = { marginTop: "16px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "center" };
const floatingScrollableContentStyle: React.CSSProperties = { maxHeight: "360px", overflowY: "auto", overflowX: "hidden", paddingRight: "4px" };
const floatingScrollableContentStyleWide: React.CSSProperties = { ...floatingScrollableContentStyle, maxHeight: "420px" };
const sortOptionsGridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr", gap: "10px" };
const sortOptionButtonStyle: React.CSSProperties = { border: "1px solid #e2e8f0", borderRadius: "12px", padding: "12px 14px", background: "#f8fafc", color: "#0f172a", fontSize: "14px", fontWeight: 700, cursor: "pointer", textAlign: "left" };
const sortOptionActiveStyle: React.CSSProperties = { ...sortOptionButtonStyle, background: "#0f172a", color: "#ffffff", border: "1px solid #0f172a" };
const toolbarControlGroupStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "8px", minWidth: 0, minHeight: "72px", justifyContent: "flex-end" };
const compactSelectStyle: React.CSSProperties = { padding: "12px 14px", borderRadius: "14px", border: "1px solid #cbd5e1", fontSize: "14px", background: "#fff", outline: "none", boxShadow: "inset 0 1px 2px rgba(15,23,42,0.03)", width: "220px", minWidth: "220px" };
const toolbarRightInfoStyle: React.CSSProperties = { minHeight: "48px", padding: "12px 14px", borderRadius: "14px", background: "#f8fafc", border: "1px solid #e2e8f0", display: "flex", flexDirection: "column", justifyContent: "center" };
const toolbarRightValueStyle: React.CSSProperties = { fontWeight: 800, color: "#0f172a", fontSize: "14px" };
const smallMutedDarkStyle: React.CSSProperties = { color: "#64748b", fontSize: "12px", marginBottom: "4px" };
const watchlistTableShellStyle: React.CSSProperties = { border: "1px solid #e2e8f0", borderRadius: "16px", overflow: "hidden", background: "#ffffff" };
const watchlistTableWrapStyle: React.CSSProperties = { overflowX: "auto", overflowY: "auto", maxHeight: "640px" };
const stickyHeaderCellStyle: React.CSSProperties = { textAlign: "left", padding: "12px", background: "#f8fafc", color: "#475569", fontSize: "12px", fontWeight: 800, borderBottom: "1px solid #e2e8f0", position: "sticky", top: 0, zIndex: 1, whiteSpace: "nowrap" };
const columnHeaderContentStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "6px" };
const columnDragHandleStyle: React.CSSProperties = { fontSize: "12px", color: "#94a3b8", cursor: "grab", userSelect: "none" };
const stickyFirstHeaderCellStyle: React.CSSProperties = { ...stickyHeaderCellStyle, left: 0, zIndex: 3, background: "#f8fafc" };
const stickyFirstBodyCellStyle: React.CSSProperties = { ...bodyCellStyle, position: "sticky", left: 0, zIndex: 2, background: "#ffffff", fontWeight: 800 };
const watchlistAdminGridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "420px 1fr", gap: "22px", marginTop: "22px", alignItems: "start" };
const columnsMenuSectionStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: "10px", marginBottom: "18px" };
const columnsMenuSectionTitleStyle: React.CSSProperties = { fontSize: "12px", fontWeight: 900, color: "#475569", textTransform: "uppercase", letterSpacing: "0.08em" };
const columnsPanelGridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "12px" };
const filtersPanelGridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr", gap: "16px" };
const columnToggleLabelStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: "10px", padding: "12px 14px", border: "1px solid #e2e8f0", borderRadius: "14px", background: "#f8fafc", fontWeight: 700, color: "#0f172a" };

export default App;
