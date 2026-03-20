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
  getPolygonOptionResolved,
  getTickers,
  getWatchlistQuotes,
  isLoggedIn,
  login,
  saveToken,
  updateList,
  type PolygonOptionQueryParams,
  type PolygonResolvedOption,
  type TickerItem,
  type Watchlist,
  type WatchlistQuote,
} from "./lib/api";

type ActivePage = "dashboard" | "watchlists";

type ExpiryScope =
  | "weekly"
  | "near"
  | "far"
  | "all"
  | "fixed-horizon"
  | "manual";

type HorizonMode = "1m" | "6m" | "1y";
type OptionSide = "calls" | "puts" | "both";
type PremiumMode = "mid" | "last" | "bid" | "ask";
type TargetMode = "delta" | "percent-otm";
type MoneynessState = "ITM" | "ATM" | "OTM" | "-";

type VisibleColumnsState = {
  symbol: boolean;
  price: boolean;
  strike: boolean;
  expiry: boolean;
  optionSide: boolean;
  premium: boolean;
  returnPercent: boolean;
  delta: boolean;
  gamma: boolean;
  theta: boolean;
  vega: boolean;
  rho: boolean;
  moneyness: boolean;
  ma20: boolean;
  ma30: boolean;
  ma50: boolean;
  ma200: boolean;
  change: boolean;
  changePercent: boolean;
  status: boolean;
  updated: boolean;
  note: boolean;
};

type ColumnKey = keyof VisibleColumnsState;

type WatchlistFiltersState = {
  minPrice: string;
  minChangePercent: string;
  status: string;
};

type OptionsControlsState = {
  expiryScope: ExpiryScope;
  horizonMode: HorizonMode;
  optionSide: OptionSide;
  premiumMode: PremiumMode;
  manualExpiry: string;
  targetMode: TargetMode;
  targetDelta: string;
  targetPercentOtm: string;
};

type SavedView = {
  id: string;
  name: string;
  columns: VisibleColumnsState;
  columnOrder: ColumnKey[];
  filters: WatchlistFiltersState;
  sort: string;
  optionsControls: OptionsControlsState;
};

type OptionRowState = {
  resolved: PolygonResolvedOption | null;
  note: string;
};

type WatchlistEditorMode = "idle" | "create" | "edit";
type ToolbarMenuKey = "columns" | "sort" | "filter" | "view" | null;

const defaultVisibleColumns: VisibleColumnsState = {
  symbol: true,
  price: true,
  strike: true,
  expiry: true,
  optionSide: false,
  premium: true,
  returnPercent: false,
  delta: false,
  gamma: false,
  theta: false,
  vega: false,
  rho: false,
  moneyness: true,
  ma20: false,
  ma30: false,
  ma50: false,
  ma200: false,
  change: true,
  changePercent: true,
  status: true,
  updated: true,
  note: true,
};

const defaultColumnOrder: ColumnKey[] = [
  "symbol",
  "price",
  "strike",
  "expiry",
  "optionSide",
  "premium",
  "returnPercent",
  "delta",
  "gamma",
  "theta",
  "vega",
  "rho",
  "moneyness",
  "ma20",
  "ma30",
  "ma50",
  "ma200",
  "change",
  "changePercent",
  "status",
  "updated",
  "note",
];

const coreColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "symbol", label: "Symbol" },
  { key: "price", label: "Price" },
  { key: "change", label: "Change" },
  { key: "changePercent", label: "Change %" },
  { key: "status", label: "Status" },
  { key: "updated", label: "Updated" },
  { key: "note", label: "Note" },
];

const optionsColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "strike", label: "Strike" },
  { key: "expiry", label: "Expiry" },
  { key: "optionSide", label: "Option Side" },
  { key: "premium", label: "Premium" },
  { key: "returnPercent", label: "Return %" },
  { key: "moneyness", label: "Moneyness" },
];

const greeksColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "delta", label: "Delta" },
  { key: "gamma", label: "Gamma" },
  { key: "theta", label: "Theta" },
  { key: "vega", label: "Vega" },
  { key: "rho", label: "Rho" },
];

const movingAverageColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  { key: "ma20", label: "MA20" },
  { key: "ma30", label: "MA30" },
  { key: "ma50", label: "MA50" },
  { key: "ma200", label: "MA200" },
];

const dashboardColumnOptions: Array<{ key: ColumnKey; label: string }> = [
  ...coreColumnOptions,
  ...optionsColumnOptions,
  ...greeksColumnOptions,
  ...movingAverageColumnOptions,
];

const defaultFilters: WatchlistFiltersState = {
  minPrice: "",
  minChangePercent: "",
  status: "all",
};

const defaultOptionsControls: OptionsControlsState = {
  expiryScope: "weekly",
  horizonMode: "1m",
  optionSide: "calls",
  premiumMode: "mid",
  manualExpiry: "",
  targetMode: "delta",
  targetDelta: "0.30",
  targetPercentOtm: "5",
};

const SAVED_VIEWS_STORAGE_KEY = "options-dashboard-saved-views";
const TOOLBAR_COLLAPSED_STORAGE_KEY = "options-dashboard-toolbar-collapsed";

function App() {
  const [authenticated, setAuthenticated] = useState(isLoggedIn());

  if (!authenticated) {
    return <LoginScreen onLoginSuccess={() => setAuthenticated(true)} />;
  }

  return (
    <Shell
      onLogout={() => {
        clearToken();
        setAuthenticated(false);
      }}
    />
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [activePage, setActivePage] = useState<ActivePage>("dashboard");
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [selectedListId, setSelectedListId] = useState<number | null>(null);
  const [listsLoading, setListsLoading] = useState(true);
  const [listsError, setListsError] = useState("");

  async function loadLists() {
    try {
      setListsLoading(true);
      setListsError("");

      const data = await getLists();
      setLists(data);

      if (data.length === 0) {
        setSelectedListId(null);
      } else if (!selectedListId || !data.some((x) => x.id === selectedListId)) {
        setSelectedListId(data[0].id);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setListsError(message);

      if (message.includes("Not authenticated") || message.includes("401")) {
        clearToken();
        onLogout();
      }
    } finally {
      setListsLoading(false);
    }
  }

  useEffect(() => {
    loadLists();
  }, []);

  return (
    <div style={appShellStyle}>
      <header style={topbarStyle}>
        <div style={topbarInnerStyle}>
          <div style={topbarLeftStyle}>
            <div style={topbarLogoStyle}>Options Dashboard</div>

            <nav style={topbarNavStyle}>
              <button
                type="button"
                onClick={() => setActivePage("dashboard")}
                style={
                  activePage === "dashboard"
                    ? topbarNavButtonActiveStyle
                    : topbarNavButtonStyle
                }
              >
                Dashboard
              </button>

              <button
                type="button"
                onClick={() => setActivePage("watchlists")}
                style={
                  activePage === "watchlists"
                    ? topbarNavButtonActiveStyle
                    : topbarNavButtonStyle
                }
              >
                Watchlists
              </button>
            </nav>
          </div>

          <div style={topbarRightStyle}>
            <div style={topbarMetaStyle}>
              <div style={topbarMetaLabelStyle}>Build Phase</div>
              <div style={topbarMetaValueStyle}>Frontend Integration</div>
            </div>

            <button onClick={onLogout} style={topbarLogoutButtonStyle}>
              Log out
            </button>
          </div>
        </div>
      </header>

      <main style={contentAreaStyle}>
        <div style={contentInnerStyle}>
          {activePage === "dashboard" ? (
            <WatchlistsWorkspacePage
              lists={lists}
              selectedListId={selectedListId}
              setSelectedListId={setSelectedListId}
              listsLoading={listsLoading}
              listsError={listsError}
              onOpenWatchlistsPage={() => setActivePage("watchlists")}
            />
          ) : (
            <WatchlistsManagerPage
              lists={lists}
              refreshLists={loadLists}
              listsLoading={listsLoading}
              listsError={listsError}
            />
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
      setLoading(true);
      setError("");

      const data = await login(username, password);
      saveToken(data.access_token);
      onLoginSuccess();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={loginPageStyle}>
      <div style={loginCardStyle}>
        <div style={loginBrandStyle}>Options Dashboard</div>
        <h1 style={loginTitleStyle}>Sign in</h1>
        <p style={loginSubtitleStyle}>
          Use your account to access live watchlists and saved layouts.
        </p>

        <form onSubmit={handleSubmit} style={loginFormStyle}>
          <div style={fieldGroupStyle}>
            <label style={labelStyle}>Email / Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              style={inputStyle}
              placeholder="Enter your email or username"
            />
          </div>

          <div style={fieldGroupStyle}>
            <label style={labelStyle}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
              placeholder="Enter your password"
            />
          </div>

          {error && <p style={loginErrorStyle}>Error: {error}</p>}

          <button type="submit" style={loginButtonStyle} disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

type WatchlistsWorkspacePageProps = {
  lists: Watchlist[];
  selectedListId: number | null;
  setSelectedListId: React.Dispatch<React.SetStateAction<number | null>>;
  listsLoading: boolean;
  listsError: string;
  onOpenWatchlistsPage: () => void;
};

function WatchlistsWorkspacePage({
  lists,
  selectedListId,
  setSelectedListId,
  listsLoading,
  listsError,
  onOpenWatchlistsPage,
}: WatchlistsWorkspacePageProps) {
  const [quotes, setQuotes] = useState<WatchlistQuote[]>([]);
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesError, setQuotesError] = useState("");

  const [optionsBySymbol, setOptionsBySymbol] = useState<
    Record<string, OptionRowState>
  >({});
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState("");

  const [openMenu, setOpenMenu] = useState<ToolbarMenuKey>(null);

  const [visibleColumns, setVisibleColumns] =
    useState<VisibleColumnsState>(defaultVisibleColumns);
  const [columnOrder, setColumnOrder] =
    useState<ColumnKey[]>(defaultColumnOrder);
  const [filters, setFilters] = useState<WatchlistFiltersState>(defaultFilters);
  const [sortOption, setSortOption] = useState("symbol-asc");
  const [optionsControls, setOptionsControls] =
    useState<OptionsControlsState>(defaultOptionsControls);
  const [availableExpiries, setAvailableExpiries] = useState<string[]>([]);
  const [expiryOptionsLoading, setExpiryOptionsLoading] = useState(false);
  const [draggedColumnKey, setDraggedColumnKey] = useState<ColumnKey | null>(null);
  const [dragOverColumnKey, setDragOverColumnKey] = useState<ColumnKey | null>(null);
  const [toolbarCollapsed, setToolbarCollapsed] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(TOOLBAR_COLLAPSED_STORAGE_KEY);
      return raw ? JSON.parse(raw) === true : true;
    } catch {
      return true;
    }
  });

  const optionsRequestIdRef = useRef(0);

  const [savedViews, setSavedViews] = useState<SavedView[]>(() => {
    const defaultView: SavedView = {
      id: "default",
      name: "Default",
      columns: defaultVisibleColumns,
      columnOrder: defaultColumnOrder,
      filters: defaultFilters,
      sort: "symbol-asc",
      optionsControls: defaultOptionsControls,
    };

    try {
      const raw = localStorage.getItem(SAVED_VIEWS_STORAGE_KEY);
      if (!raw) {
        return [defaultView];
      }

      const parsed = JSON.parse(raw);

      if (!Array.isArray(parsed) || parsed.length === 0) {
        return [defaultView];
      }

      return parsed.map((view) => ({
        id: typeof view?.id === "string" ? view.id : crypto.randomUUID(),
        name: typeof view?.name === "string" ? view.name : "Saved View",
        columns: {
          ...defaultVisibleColumns,
          ...(view?.columns ?? {}),
        },
        columnOrder:
          Array.isArray(view?.columnOrder) && view.columnOrder.length > 0
            ? normalizeColumnOrder(view.columnOrder as ColumnKey[])
            : defaultColumnOrder,
        filters: {
          ...defaultFilters,
          ...(view?.filters ?? {}),
        },
        sort: typeof view?.sort === "string" ? view.sort : "symbol-asc",
        optionsControls: {
          ...defaultOptionsControls,
          ...(view?.optionsControls ?? {}),
        },
      }));
    } catch {
      return [defaultView];
    }
  });

  const [activeViewId, setActiveViewId] = useState<string>("default");

  const columnsMenuRef = useRef<HTMLDivElement | null>(null);
  const filterMenuRef = useRef<HTMLDivElement | null>(null);
  const sortMenuRef = useRef<HTMLDivElement | null>(null);
  const viewMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    localStorage.setItem(SAVED_VIEWS_STORAGE_KEY, JSON.stringify(savedViews));
  }, [savedViews]);

  useEffect(() => {
    localStorage.setItem(
      TOOLBAR_COLLAPSED_STORAGE_KEY,
      JSON.stringify(toolbarCollapsed)
    );
  }, [toolbarCollapsed]);

  useEffect(() => {
    setVisibleColumns(defaultVisibleColumns);
    setColumnOrder(defaultColumnOrder);
    setFilters(defaultFilters);
    setSortOption("symbol-asc");
    setOptionsControls(defaultOptionsControls);
    setOptionsBySymbol({});
    setOptionsError("");
    setAvailableExpiries([]);
    setExpiryOptionsLoading(false);
    setOpenMenu(null);
    setActiveViewId("default");
    setDraggedColumnKey(null);
    setDragOverColumnKey(null);
    optionsRequestIdRef.current += 1;
  }, [selectedListId]);

  useEffect(() => {
    function handleDocumentClick(event: MouseEvent) {
      const target = event.target as Node;

      const refs = [
        columnsMenuRef.current,
        filterMenuRef.current,
        sortMenuRef.current,
        viewMenuRef.current,
      ];

      const clickedInsideAnyMenu = refs.some((ref) => ref?.contains(target));

      if (!clickedInsideAnyMenu) {
        setOpenMenu(null);
      }
    }

    document.addEventListener("mousedown", handleDocumentClick);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
    };
  }, []);

  const optionSymbols = useMemo(
    () =>
      Array.from(
        new Set(
          quotes
            .map((quote) => quote.symbol)
            .filter((symbol): symbol is string => Boolean(symbol))
        )
      ).sort(),
    [quotes]
  );

  async function loadQuotesForList(listId: number): Promise<WatchlistQuote[]> {
    setQuotesLoading(true);
    setQuotesError("");

    try {
      const data = await getWatchlistQuotes(listId);
      const normalized = Array.isArray(data) ? data : [];
      setQuotes(normalized);
      return normalized;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load quotes";
      setQuotesError(message);
      setQuotes([]);
      return [];
    } finally {
      setQuotesLoading(false);
    }
  }

  async function loadOptionsForSymbols(symbols: string[]) {
    const requestId = ++optionsRequestIdRef.current;

    if (symbols.length === 0) {
      setOptionsBySymbol({});
      setOptionsError("");
      setOptionsLoading(false);
      return;
    }

    setOptionsLoading(true);
    setOptionsError("");

    try {
      const queryParams: PolygonOptionQueryParams = {
        expiryScope: optionsControls.expiryScope,
        horizonMode: optionsControls.horizonMode,
        optionSide: optionsControls.optionSide,
        premiumMode: optionsControls.premiumMode,
        manualExpiry:
          optionsControls.expiryScope === "manual" &&
          optionsControls.manualExpiry.trim()
            ? optionsControls.manualExpiry.trim()
            : undefined,
        targetMode: optionsControls.targetMode,
        targetDelta:
          optionsControls.targetMode === "delta" &&
          optionsControls.targetDelta.trim()
            ? optionsControls.targetDelta.trim()
            : undefined,
        targetPercentOtm:
          optionsControls.targetMode === "percent-otm" &&
          optionsControls.targetPercentOtm.trim()
            ? optionsControls.targetPercentOtm.trim()
            : undefined,
      };

      const selectedManualExpiry =
        optionsControls.expiryScope === "manual" &&
        optionsControls.manualExpiry.trim()
          ? optionsControls.manualExpiry.trim()
          : "";

      const concurrencyLimit = 4;
      const nextBySymbol: Record<string, OptionRowState> = {};
      let failureCount = 0;

      for (let index = 0; index < symbols.length; index += concurrencyLimit) {
        const batch = symbols.slice(index, index + concurrencyLimit);

        const batchResults = await Promise.allSettled(
          batch.map((symbol) => getPolygonOptionResolved(symbol, queryParams))
        );

        if (requestId !== optionsRequestIdRef.current) {
          return;
        }

        batchResults.forEach((result, batchIndex) => {
          const symbol = batch[batchIndex];

          if (result.status === "fulfilled") {
            const response = result.value;
            const resolved = response?.resolved ?? null;
            const returnedExpiries = Array.isArray(response?.availableExpiries)
              ? response.availableExpiries
              : [];

            let note = "";

            if (resolved) {
              note = "Live option loaded";
            } else if (optionsControls.expiryScope === "manual") {
              if (
                selectedManualExpiry &&
                returnedExpiries.length > 0 &&
                !returnedExpiries.includes(selectedManualExpiry)
              ) {
                note = "Selected expiry unavailable for this symbol";
              } else {
                note = "No contract at selected expiry";
              }
            } else {
              note = "No option match";
            }

            nextBySymbol[symbol] = {
              resolved,
              note,
            };

            if (!resolved) {
              failureCount += 1;
            }
          } else {
            failureCount += 1;

            nextBySymbol[symbol] = {
              resolved: null,
              note:
                optionsControls.expiryScope === "manual"
                  ? "No contract at selected expiry"
                  : "Options unavailable",
            };
          }
        });
      }

      if (requestId !== optionsRequestIdRef.current) {
        return;
      }

      setOptionsBySymbol(nextBySymbol);

      const resolvedCount = Object.values(nextBySymbol).filter(
        (item) => item.resolved
      ).length;

      if (failureCount > 0 && resolvedCount === 0) {
        setOptionsError(
          `Options data unavailable for ${failureCount} ticker${
            failureCount === 1 ? "" : "s"
          }.`
        );
      } else {
        setOptionsError("");
      }
    } catch (err) {
      if (requestId !== optionsRequestIdRef.current) {
        return;
      }

      const message =
        err instanceof Error ? err.message : "Failed to load options";
      setOptionsBySymbol({});
      setOptionsError(message);
    } finally {
      if (requestId === optionsRequestIdRef.current) {
        setOptionsLoading(false);
      }
    }
  }

  function getDisplayOptionData(quote: WatchlistQuote) {
    const rowOptionState = optionsBySymbol[quote.symbol];
    const liveData = rowOptionState?.resolved ?? null;

    const optionSideLabel: "Call" | "Put" | "Mixed" =
      liveData?.optionSide === "Call"
        ? "Call"
        : liveData?.optionSide === "Put"
        ? "Put"
        : "Mixed";

    const moneyness: MoneynessState =
      liveData?.moneyness === "ITM" ||
      liveData?.moneyness === "ATM" ||
      liveData?.moneyness === "OTM"
        ? liveData.moneyness
        : "-";

    let expiryLabel = "-";

    if (liveData?.expiry) {
      expiryLabel = liveData.expiry;
    } else if (optionsControls.expiryScope === "manual") {
      expiryLabel = optionsControls.manualExpiry || "Select expiry";
    }

    return {
      strike: liveData?.strike ?? null,
      expiryLabel,
      expirySortValue: liveData?.expiry ?? optionsControls.manualExpiry ?? "",
      optionSideLabel,
      premium: liveData?.premium ?? null,
      returnPercent: liveData?.returnPercent ?? null,
      delta: liveData?.delta ?? null,
      gamma: liveData?.gamma ?? null,
      theta: liveData?.theta ?? null,
      vega: liveData?.vega ?? null,
      rho: liveData?.rho ?? null,
      moneyness,
      ma20: null,
      ma30: null,
      ma50: null,
      ma200: null,
      underlyingPrice: liveData?.underlyingPrice ?? null,
      note: rowOptionState?.note ?? "",
      hasResolvedOption: Boolean(liveData),
    };
  }

  const filteredAndSortedQuotes = useMemo(() => {
    const minPriceValue = toSafeNumber(filters.minPrice);
    const minChangePercentValue = toSafeNumber(filters.minChangePercent);

    return [...quotes]
      .filter((quote) => {
        const quotePrice = toSafeNumber(quote.last_price);
        const quoteChangePercent = toSafeNumber(quote.change_percent);
        const quoteStatus = String(quote.status ?? "").toLowerCase();

        if (minPriceValue !== null) {
          if (quotePrice === null || quotePrice <= minPriceValue) {
            return false;
          }
        }

        if (minChangePercentValue !== null) {
          if (quoteChangePercent === null || quoteChangePercent <= minChangePercentValue) {
            return false;
          }
        }

        if (filters.status !== "all" && quoteStatus !== filters.status) {
          return false;
        }

        return true;
      })
      .sort((a, b) => {
        const [column, direction] = sortOption.split("-");
        const directionMultiplier = direction === "asc" ? 1 : -1;

        if (column === "symbol") {
          return compareValues(a.symbol ?? "", b.symbol ?? "") * directionMultiplier;
        }

        if (column === "price") {
          return (
            compareValues(
              toSafeNumber(a.last_price) ?? Number.NEGATIVE_INFINITY,
              toSafeNumber(b.last_price) ?? Number.NEGATIVE_INFINITY
            ) * directionMultiplier
          );
        }

        if (column === "change") {
          return (
            compareValues(
              toSafeNumber(a.change) ?? Number.NEGATIVE_INFINITY,
              toSafeNumber(b.change) ?? Number.NEGATIVE_INFINITY
            ) * directionMultiplier
          );
        }

        if (column === "changePercent") {
          return (
            compareValues(
              toSafeNumber(a.change_percent) ?? Number.NEGATIVE_INFINITY,
              toSafeNumber(b.change_percent) ?? Number.NEGATIVE_INFINITY
            ) * directionMultiplier
          );
        }

        if (column === "updated") {
          return compareValues(a.updated_at ?? "", b.updated_at ?? "") * directionMultiplier;
        }

        const optionDataA = getDisplayOptionData(a);
        const optionDataB = getDisplayOptionData(b);

        switch (column) {
          case "strike":
            return compareValues(optionDataA.strike, optionDataB.strike) * directionMultiplier;
          case "expiry":
            return (
              compareValues(optionDataA.expirySortValue, optionDataB.expirySortValue) *
              directionMultiplier
            );
          case "optionSide":
            return (
              compareValues(optionDataA.optionSideLabel, optionDataB.optionSideLabel) *
              directionMultiplier
            );
          case "premium":
            return compareValues(optionDataA.premium, optionDataB.premium) * directionMultiplier;
          case "returnPercent":
            return (
              compareValues(optionDataA.returnPercent, optionDataB.returnPercent) *
              directionMultiplier
            );
          case "delta":
            return compareValues(optionDataA.delta, optionDataB.delta) * directionMultiplier;
          case "gamma":
            return compareValues(optionDataA.gamma, optionDataB.gamma) * directionMultiplier;
          case "theta":
            return compareValues(optionDataA.theta, optionDataB.theta) * directionMultiplier;
          case "vega":
            return compareValues(optionDataA.vega, optionDataB.vega) * directionMultiplier;
          case "rho":
            return compareValues(optionDataA.rho, optionDataB.rho) * directionMultiplier;
          case "moneyness":
            return (
              compareValues(
                getMoneynessRank(optionDataA.moneyness),
                getMoneynessRank(optionDataB.moneyness)
              ) * directionMultiplier
            );
          case "ma20":
            return compareValues(optionDataA.ma20, optionDataB.ma20) * directionMultiplier;
          case "ma30":
            return compareValues(optionDataA.ma30, optionDataB.ma30) * directionMultiplier;
          case "ma50":
            return compareValues(optionDataA.ma50, optionDataB.ma50) * directionMultiplier;
          case "ma200":
            return compareValues(optionDataA.ma200, optionDataB.ma200) * directionMultiplier;
          default:
            return 0;
        }
      });
  }, [quotes, filters, sortOption, optionsControls, optionsBySymbol]);

  const orderedVisibleColumns = useMemo(
    () => columnOrder.filter((key) => visibleColumns[key]),
    [columnOrder, visibleColumns]
  );

  useEffect(() => {
    if (!selectedListId) {
      setQuotes([]);
      setQuotesError("");
      setQuotesLoading(false);
      return;
    }

    const listId = selectedListId;
    let cancelled = false;

    async function loadQuotes() {
      if (cancelled) return;
      await loadQuotesForList(listId);
    }

    loadQuotes();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadQuotes();
      }
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [selectedListId]);

  useEffect(() => {
    if (optionsControls.expiryScope !== "manual") {
      setAvailableExpiries([]);
      setExpiryOptionsLoading(false);
      return;
    }

    if (optionSymbols.length === 0) {
      setAvailableExpiries([]);
      setExpiryOptionsLoading(false);
      return;
    }

    let cancelled = false;

    async function loadExpiryOptions() {
      try {
        setExpiryOptionsLoading(true);

        const response = await getPolygonOptionResolved(optionSymbols[0], {
          expiryScope: "manual",
          horizonMode: optionsControls.horizonMode,
          optionSide: optionsControls.optionSide,
          premiumMode: optionsControls.premiumMode,
          targetMode: optionsControls.targetMode,
          targetDelta:
            optionsControls.targetMode === "delta" &&
            optionsControls.targetDelta.trim()
              ? optionsControls.targetDelta.trim()
              : undefined,
          targetPercentOtm:
            optionsControls.targetMode === "percent-otm" &&
            optionsControls.targetPercentOtm.trim()
              ? optionsControls.targetPercentOtm.trim()
              : undefined,
        });

        if (cancelled) return;

        const expiries = Array.isArray(response.availableExpiries)
          ? response.availableExpiries
          : [];

        setAvailableExpiries(expiries);

        if (
          expiries.length > 0 &&
          (!optionsControls.manualExpiry ||
            !expiries.includes(optionsControls.manualExpiry))
        ) {
          setOptionsControls((prev) => ({
            ...prev,
            manualExpiry: response.selectedExpiry || expiries[0],
          }));
        }
      } catch {
        if (cancelled) return;
        setAvailableExpiries([]);
      } finally {
        if (!cancelled) {
          setExpiryOptionsLoading(false);
        }
      }
    }

    loadExpiryOptions();

    return () => {
      cancelled = true;
    };
  }, [
    optionSymbols.join("|"),
    optionsControls.expiryScope,
    optionsControls.horizonMode,
    optionsControls.optionSide,
    optionsControls.premiumMode,
    optionsControls.targetMode,
    optionsControls.targetDelta,
    optionsControls.targetPercentOtm,
  ]);

  useEffect(() => {
    if (!selectedListId || optionSymbols.length === 0) {
      setOptionsBySymbol({});
      setOptionsError("");
      setOptionsLoading(false);
      return;
    }

    let cancelled = false;

    async function loadOptions() {
      if (cancelled) return;
      await loadOptionsForSymbols(optionSymbols);
    }

    loadOptions();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadOptions();
      }
    }, 60000);

    return () => {
      cancelled = true;
      optionsRequestIdRef.current += 1;
      window.clearInterval(intervalId);
    };
  }, [
    selectedListId,
    optionSymbols.join("|"),
    optionsControls.expiryScope,
    optionsControls.horizonMode,
    optionsControls.optionSide,
    optionsControls.premiumMode,
    optionsControls.manualExpiry,
    optionsControls.targetMode,
    optionsControls.targetDelta,
    optionsControls.targetPercentOtm,
  ]);

  function getSortKeyForColumn(columnKey: ColumnKey): string | null {
    switch (columnKey) {
      case "symbol":
      case "price":
      case "strike":
      case "expiry":
      case "optionSide":
      case "premium":
      case "returnPercent":
      case "delta":
      case "gamma":
      case "theta":
      case "vega":
      case "rho":
      case "moneyness":
      case "ma20":
      case "ma30":
      case "ma50":
      case "ma200":
      case "change":
      case "changePercent":
      case "updated":
        return columnKey;
      default:
        return null;
    }
  }

  function getSortIndicatorForColumn(
    columnKey: ColumnKey,
    currentSortOption: string
  ): string {
    const sortKey = getSortKeyForColumn(columnKey);
    if (!sortKey) return "";

    const [currentKey, currentDirection] = currentSortOption.split("-");
    if (currentKey !== sortKey) return "";

    return currentDirection === "asc" ? " ▲" : " ▼";
  }

  function moveColumn(draggedKey: ColumnKey, targetKey: ColumnKey) {
    if (draggedKey === targetKey) return;

    setColumnOrder((prev) => {
      const next = [...prev];
      const fromIndex = next.indexOf(draggedKey);
      const toIndex = next.indexOf(targetKey);

      if (fromIndex === -1 || toIndex === -1) return prev;

      next.splice(fromIndex, 1);
      next.splice(toIndex, 0, draggedKey);
      return next;
    });
  }

  function renderCell(
    columnKey: ColumnKey,
    quote: WatchlistQuote,
    isFirstVisibleColumn: boolean
  ) {
    const baseStyle = isFirstVisibleColumn ? stickyFirstBodyCellStyle : bodyCellStyle;
    const optionData = getDisplayOptionData(quote);

    switch (columnKey) {
      case "symbol":
        return <td style={{ ...baseStyle, fontWeight: 800 }}>{quote.symbol}</td>;

      case "price":
        return (
          <td style={{ ...baseStyle, fontWeight: 800 }}>
            {formatNumber(toSafeNumber(quote.last_price))}
          </td>
        );

      case "strike":
        return (
          <td style={baseStyle}>
            <span style={{ fontWeight: 700 }}>
              {formatNumber(optionData.strike)}
            </span>
          </td>
        );

      case "expiry":
        return (
          <td style={baseStyle}>
            <span style={{ fontWeight: 700 }}>{optionData.expiryLabel}</span>
          </td>
        );

      case "optionSide":
        return (
          <td style={baseStyle}>
            <span style={optionSideBadgeStyle}>
              {optionData.optionSideLabel === "Mixed" ? "-" : optionData.optionSideLabel}
            </span>
          </td>
        );

      case "premium":
        return (
          <td style={{ ...baseStyle, fontWeight: 700 }}>
            {formatCurrency(optionData.premium)}
          </td>
        );

      case "returnPercent":
        return (
          <td
            style={{
              ...baseStyle,
              fontWeight: 700,
              color: getChangeColor(optionData.returnPercent),
            }}
          >
            {formatSignedPercent(optionData.returnPercent)}
          </td>
        );

      case "delta":
        return <td style={baseStyle}>{formatMetric(optionData.delta, 3)}</td>;

      case "gamma":
        return <td style={baseStyle}>{formatMetric(optionData.gamma, 3)}</td>;

      case "theta":
        return (
          <td style={{ ...baseStyle, color: (optionData.theta ?? 0) < 0 ? "#991b1b" : "#0f172a" }}>
            {formatSignedMetric(optionData.theta, 3)}
          </td>
        );

      case "vega":
        return <td style={baseStyle}>{formatMetric(optionData.vega, 3)}</td>;

      case "rho":
        return <td style={baseStyle}>{formatMetric(optionData.rho, 3)}</td>;

      case "moneyness":
        return (
          <td style={baseStyle}>
            <span
              style={{
                ...moneynessBadgeStyle,
                background:
                  optionData.moneyness === "ITM"
                    ? "#fee2e2"
                    : optionData.moneyness === "ATM"
                    ? "#fef3c7"
                    : optionData.moneyness === "OTM"
                    ? "#dcfce7"
                    : "#e2e8f0",
                color:
                  optionData.moneyness === "ITM"
                    ? "#991b1b"
                    : optionData.moneyness === "ATM"
                    ? "#92400e"
                    : optionData.moneyness === "OTM"
                    ? "#166534"
                    : "#475569",
              }}
            >
              {optionData.moneyness}
            </span>
          </td>
        );

      case "ma20":
        return <td style={baseStyle}>{formatNumber(optionData.ma20)}</td>;

      case "ma30":
        return <td style={baseStyle}>{formatNumber(optionData.ma30)}</td>;

      case "ma50":
        return <td style={baseStyle}>{formatNumber(optionData.ma50)}</td>;

      case "ma200":
        return <td style={baseStyle}>{formatNumber(optionData.ma200)}</td>;

      case "change":
        return (
          <td
            style={{
              ...baseStyle,
              fontWeight: 700,
              color: getChangeColor(toSafeNumber(quote.change)),
            }}
          >
            {formatSignedNumber(toSafeNumber(quote.change))}
          </td>
        );

      case "changePercent":
        return (
          <td
            style={{
              ...baseStyle,
              fontWeight: 700,
              color: getChangeColor(toSafeNumber(quote.change_percent)),
            }}
          >
            {formatSignedPercent(toSafeNumber(quote.change_percent))}
          </td>
        );

      case "status":
        return (
          <td style={baseStyle}>
            <span
              style={{
                ...statusBadgeStyle,
                backgroundColor:
                  quote.status === "ok"
                    ? "#dcfce7"
                    : quote.status === "delayed"
                    ? "#fef3c7"
                    : "#fee2e2",
                color:
                  quote.status === "ok"
                    ? "#166534"
                    : quote.status === "delayed"
                    ? "#92400e"
                    : "#991b1b",
              }}
            >
              {quote.status ?? "-"}
            </span>
          </td>
        );

      case "updated":
        return <td style={baseStyle}>{formatTimeShort(quote.updated_at)}</td>;

      case "note": {
        const optionData = getDisplayOptionData(quote);

        let noteText = optionData.note;

        if (!noteText) {
          noteText = optionsLoading
            ? "Loading options"
            : quote.status === "delayed"
            ? "Fallback daily data"
            : "No option match";
        }

        const isExpiryIssue =
          noteText === "No contract at selected expiry" ||
          noteText === "Selected expiry unavailable for this symbol";

        return (
          <td
            style={{
              ...baseStyle,
              color: isExpiryIssue ? "#92400e" : baseStyle.color,
              fontWeight: isExpiryIssue ? 800 : baseStyle.fontWeight,
            }}
          >
            {noteText}
          </td>
        );
      }

      default:
        return <td style={baseStyle}>-</td>;
    }
  }

  function renderColumnsMenuSection(
    title: string,
    options: Array<{ key: ColumnKey; label: string }>
  ) {
    return (
      <div style={columnsMenuSectionStyle}>
        <div style={columnsMenuSectionTitleStyle}>{title}</div>
        <div style={columnsPanelGridStyle}>
          {options.map((column) => (
            <label key={column.key} style={columnToggleLabelStyle}>
              <input
                type="checkbox"
                checked={visibleColumns[column.key]}
                onChange={(e) =>
                  setVisibleColumns((prev) => ({
                    ...prev,
                    [column.key]: e.target.checked,
                  }))
                }
              />
              {column.label}
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
          <p style={pageSubtitleStyle}>
            Customizable options decision workspace with live quote context
          </p>
        </div>
      </div>

      <Panel>
        <div style={toolbarShellStyle}>
          <div style={toolbarPrimaryRowStyle}>
            <div style={toolbarPrimaryLeftStyle}>
              <div style={toolbarControlGroupStyle}>
                <label htmlFor="watchlist-select" style={labelStyle}>
                  Watchlist
                </label>
                <select
                  id="watchlist-select"
                  value={selectedListId ?? ""}
                  onChange={(e) =>
                    setSelectedListId(e.target.value ? Number(e.target.value) : null)
                  }
                  style={compactSelectStyle}
                  disabled={listsLoading || lists.length === 0}
                >
                  {lists.length === 0 ? (
                    <option value="">No watchlists found</option>
                  ) : (
                    lists.map((list) => (
                      <option key={list.id} value={list.id}>
                        {list.name}
                      </option>
                    ))
                  )}
                </select>
              </div>

              <div style={toolbarMenuAnchorStyle} ref={viewMenuRef}>
                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>View</label>
                  <button
                    type="button"
                    style={
                      openMenu === "view"
                        ? { ...viewButtonStyle, ...secondaryButtonActiveStyle }
                        : viewButtonStyle
                    }
                    onClick={() =>
                      setOpenMenu((prev) => (prev === "view" ? null : "view"))
                    }
                  >
                    {`View: ${
                      savedViews.find((view) => view.id === activeViewId)?.name ?? "Default"
                    }`}{" "}
                    {openMenu === "view" ? "▲" : "▼"}
                  </button>
                </div>

                {openMenu === "view" && (
                  <div style={floatingMenuStyle}>
                    <div style={floatingMenuHeaderStyle}>
                      <h3 style={floatingMenuTitleStyle}>Saved Views</h3>
                      <p style={floatingMenuSubtitleStyle}>
                        Quickly switch between dashboard layouts
                      </p>
                    </div>

                    <div style={floatingScrollableContentStyle}>
                      <div style={sortOptionsGridStyle}>
                        {savedViews.map((view) => (
                          <button
                            key={view.id}
                            type="button"
                            style={
                              activeViewId === view.id
                                ? sortOptionActiveStyle
                                : sortOptionButtonStyle
                            }
                            onClick={() => {
                              setVisibleColumns(view.columns);
                              setColumnOrder(
                                normalizeColumnOrder(view.columnOrder ?? defaultColumnOrder)
                              );
                              setFilters(view.filters);
                              setSortOption(view.sort);
                              setOptionsControls({
                                ...defaultOptionsControls,
                                ...(view.optionsControls ?? {}),
                              });
                              setActiveViewId(view.id);
                              setOpenMenu(null);
                            }}
                          >
                            {view.name}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div style={floatingMenuFooterStyle}>
                      <button
                        type="button"
                        style={secondaryButtonStyle}
                        onClick={() => {
                          setOpenMenu(null);
                        }}
                      >
                        Manage Views
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div style={toolbarControlGroupStyle}>
                <label style={labelStyle}>Expiry Scope</label>
                <select
                  value={optionsControls.expiryScope}
                  onChange={(e) =>
                    setOptionsControls((prev) => ({
                      ...prev,
                      expiryScope: e.target.value as ExpiryScope,
                      manualExpiry:
                        e.target.value === "manual" ? prev.manualExpiry : "",
                    }))
                  }
                  style={compactSelectStyle}
                >
                  <option value="weekly">Weekly</option>
                  <option value="near">Near</option>
                  <option value="far">Far</option>
                  <option value="all">All</option>
                  <option value="fixed-horizon">Fixed Horizon</option>
                  <option value="manual">Manual</option>
                </select>
              </div>

              <div style={toolbarPrimaryActionsStyle}>
                <button
                  type="button"
                  style={secondaryButtonStyle}
                  onClick={async () => {
                    if (!selectedListId) return;

                    const refreshedQuotes = await loadQuotesForList(selectedListId);

                    const refreshedSymbols = Array.from(
                      new Set(
                        refreshedQuotes
                          .map((quote) => quote.symbol)
                          .filter((symbol): symbol is string => Boolean(symbol))
                      )
                    ).sort();

                    await loadOptionsForSymbols(refreshedSymbols);
                  }}
                  disabled={!selectedListId || quotesLoading || optionsLoading}
                >
                  {quotesLoading || optionsLoading ? "Refreshing..." : "Refresh"}
                </button>
              </div>
            </div>

            <div style={toolbarPrimaryRightStyle}>
              <button
                type="button"
                style={secondaryButtonStyle}
                onClick={() => {
                  setToolbarCollapsed((prev) => !prev);
                  setOpenMenu(null);
                }}
              >
                {toolbarCollapsed ? "Expand Toolbar" : "Collapse Toolbar"}
              </button>
            </div>
          </div>

          {!toolbarCollapsed && (
            <div style={toolbarSecondaryRowStyle}>
              <div style={toolbarSecondaryGroupStyle}>
                {optionsControls.expiryScope === "fixed-horizon" && (
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Horizon</label>
                    <select
                      value={optionsControls.horizonMode}
                      onChange={(e) =>
                        setOptionsControls((prev) => ({
                          ...prev,
                          horizonMode: e.target.value as HorizonMode,
                        }))
                      }
                      style={compactNarrowSelectStyle}
                    >
                      <option value="1m">1 Month</option>
                      <option value="6m">6 Months</option>
                      <option value="1y">1 Year</option>
                    </select>
                  </div>
                )}

                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>Option Side</label>
                  <select
                    value={optionsControls.optionSide}
                    onChange={(e) =>
                      setOptionsControls((prev) => ({
                        ...prev,
                        optionSide: e.target.value as OptionSide,
                      }))
                    }
                    style={compactSelectStyle}
                  >
                    <option value="calls">Calls</option>
                    <option value="puts">Puts</option>
                    <option value="both">Both</option>
                  </select>
                </div>

                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>Premium Mode</label>
                  <select
                    value={optionsControls.premiumMode}
                    onChange={(e) =>
                      setOptionsControls((prev) => ({
                        ...prev,
                        premiumMode: e.target.value as PremiumMode,
                      }))
                    }
                    style={compactSelectStyle}
                  >
                    <option value="mid">Mid</option>
                    <option value="last">Last</option>
                    <option value="bid">Bid</option>
                    <option value="ask">Ask</option>
                  </select>
                </div>

                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>Target Mode</label>
                  <select
                    value={optionsControls.targetMode}
                    onChange={(e) =>
                      setOptionsControls((prev) => ({
                        ...prev,
                        targetMode: e.target.value as TargetMode,
                      }))
                    }
                    style={compactSelectStyle}
                  >
                    <option value="delta">Delta</option>
                    <option value="percent-otm">% OTM</option>
                  </select>
                </div>

                {optionsControls.targetMode === "delta" ? (
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Target Delta</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={optionsControls.targetDelta}
                      onChange={(e) =>
                        setOptionsControls((prev) => ({
                          ...prev,
                          targetDelta: e.target.value,
                        }))
                      }
                      style={{
                        ...inputStyle,
                        width: "140px",
                        minWidth: "140px",
                        padding: "12px 14px",
                      }}
                      placeholder="0.30"
                    />
                  </div>
                ) : (
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Target % OTM</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={optionsControls.targetPercentOtm}
                      onChange={(e) =>
                        setOptionsControls((prev) => ({
                          ...prev,
                          targetPercentOtm: e.target.value,
                        }))
                      }
                      style={{
                        ...inputStyle,
                        width: "140px",
                        minWidth: "140px",
                        padding: "12px 14px",
                      }}
                      placeholder="5"
                    />
                  </div>
                )}

                {optionsControls.expiryScope === "manual" && (
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>
                      Expiry
                      <span style={{ marginLeft: "6px", color: "#64748b", fontSize: "11px" }}>
                        {availableExpiries.length > 0
                          ? `(${availableExpiries.length})`
                          : expiryOptionsLoading
                          ? "(loading...)"
                          : ""}
                      </span>
                    </label>

                    {availableExpiries.length > 0 ? (
                      <select
                        value={optionsControls.manualExpiry || ""}
                        onChange={(e) =>
                          setOptionsControls((prev) => ({
                            ...prev,
                            manualExpiry: e.target.value,
                          }))
                        }
                        style={compactSelectStyle}
                      >
                        {availableExpiries.map((expiry) => (
                          <option key={expiry} value={expiry}>
                            {expiry}
                          </option>
                        ))}
                      </select>
                    ) : expiryOptionsLoading ? (
                      <select disabled style={compactSelectStyle}>
                        <option>Loading expiries...</option>
                      </select>
                    ) : (
                      <select disabled style={compactSelectStyle}>
                        <option>No expiries found</option>
                      </select>
                    )}
                  </div>
                )}
              </div>

              <div style={toolbarSecondaryGroupStyle}>
                <div style={toolbarMenuAnchorStyle} ref={columnsMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Columns</label>
                    <button
                      type="button"
                      style={
                        openMenu === "columns"
                          ? secondaryButtonActiveStyle
                          : secondaryButtonStyle
                      }
                      onClick={() =>
                        setOpenMenu((prev) => (prev === "columns" ? null : "columns"))
                      }
                    >
                      Columns {openMenu === "columns" ? "▲" : "▼"}
                    </button>
                  </div>

                  {openMenu === "columns" && (
                    <div style={floatingMenuStyleClampedWide}>
                      <div style={floatingMenuHeaderStyle}>
                        <div>
                          <h3 style={floatingMenuTitleStyle}>Visible Columns</h3>
                          <p style={floatingMenuSubtitleStyle}>
                            Choose which columns appear in the options workspace
                          </p>
                        </div>
                      </div>

                      <div style={floatingScrollableContentStyleWide}>
                        {renderColumnsMenuSection("Core", coreColumnOptions)}
                        {renderColumnsMenuSection("Options", optionsColumnOptions)}
                        {renderColumnsMenuSection("Greeks", greeksColumnOptions)}
                        {renderColumnsMenuSection(
                          "Moving Averages",
                          movingAverageColumnOptions
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div style={toolbarMenuAnchorStyle} ref={sortMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Sort</label>
                    <button
                      type="button"
                      style={
                        openMenu === "sort"
                          ? secondaryButtonActiveStyle
                          : secondaryButtonStyle
                      }
                      onClick={() =>
                        setOpenMenu((prev) => (prev === "sort" ? null : "sort"))
                      }
                    >
                      Sort {openMenu === "sort" ? "▲" : "▼"}
                    </button>
                  </div>

                  {openMenu === "sort" && (
                    <div style={floatingMenuStyleClamped}>
                      <div style={floatingMenuHeaderStyle}>
                        <div>
                          <h3 style={floatingMenuTitleStyle}>Sort Rows</h3>
                          <p style={floatingMenuSubtitleStyle}>
                            Choose how the workspace is ordered
                          </p>
                        </div>
                      </div>

                      <div style={floatingScrollableContentStyle}>
                        <div style={sortOptionsGridStyle}>
                          {[
                            ["symbol-asc", "Symbol A → Z"],
                            ["symbol-desc", "Symbol Z → A"],
                            ["price-asc", "Price Low → High"],
                            ["price-desc", "Price High → Low"],
                            ["strike-asc", "Strike Low → High"],
                            ["strike-desc", "Strike High → Low"],
                            ["expiry-asc", "Expiry Near → Far"],
                            ["expiry-desc", "Expiry Far → Near"],
                            ["premium-asc", "Premium Low → High"],
                            ["premium-desc", "Premium High → Low"],
                            ["returnPercent-asc", "Return % Low → High"],
                            ["returnPercent-desc", "Return % High → Low"],
                            ["delta-asc", "Delta Low → High"],
                            ["delta-desc", "Delta High → Low"],
                            ["change-asc", "Change Low → High"],
                            ["change-desc", "Change High → Low"],
                            ["changePercent-asc", "Change % Low → High"],
                            ["changePercent-desc", "Change % High → Low"],
                            ["updated-asc", "Updated Oldest → Newest"],
                            ["updated-desc", "Updated Newest → Oldest"],
                          ].map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              style={
                                sortOption === value
                                  ? sortOptionActiveStyle
                                  : sortOptionButtonStyle
                              }
                              onClick={() => {
                                setSortOption(value);
                                setOpenMenu(null);
                              }}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div style={toolbarMenuAnchorStyle} ref={filterMenuRef}>
                  <div style={toolbarControlGroupStyle}>
                    <label style={labelStyle}>Filter</label>
                    <button
                      type="button"
                      style={
                        openMenu === "filter"
                          ? secondaryButtonActiveStyle
                          : secondaryButtonStyle
                      }
                      onClick={() =>
                        setOpenMenu((prev) => (prev === "filter" ? null : "filter"))
                      }
                    >
                      Filter {openMenu === "filter" ? "▲" : "▼"}
                    </button>
                  </div>

                  {openMenu === "filter" && (
                    <div style={floatingMenuStyleClamped}>
                      <div style={floatingMenuHeaderStyle}>
                        <div>
                          <h3 style={floatingMenuTitleStyle}>Filters</h3>
                          <p style={floatingMenuSubtitleStyle}>
                            Narrow the workspace using simple client-side rules
                          </p>
                        </div>
                      </div>

                      <div style={floatingScrollableContentStyle}>
                        <div style={filtersPanelGridStyle}>
                          <div style={fieldGroupFullStyle}>
                            <label style={labelStyle}>Price greater than</label>
                            <input
                              type="number"
                              step="0.01"
                              value={filters.minPrice}
                              onChange={(e) =>
                                setFilters((prev) => ({
                                  ...prev,
                                  minPrice: e.target.value,
                                }))
                              }
                              style={inputStyle}
                              placeholder="Example: 20"
                            />
                          </div>

                          <div style={fieldGroupFullStyle}>
                            <label style={labelStyle}>Change % greater than</label>
                            <input
                              type="number"
                              step="0.01"
                              value={filters.minChangePercent}
                              onChange={(e) =>
                                setFilters((prev) => ({
                                  ...prev,
                                  minChangePercent: e.target.value,
                                }))
                              }
                              style={inputStyle}
                              placeholder="Example: 1.5"
                            />
                          </div>

                          <div style={fieldGroupFullStyle}>
                            <label style={labelStyle}>Status</label>
                            <select
                              value={filters.status}
                              onChange={(e) =>
                                setFilters((prev) => ({
                                  ...prev,
                                  status: e.target.value,
                                }))
                              }
                              style={selectStyle}
                            >
                              <option value="all">All</option>
                              <option value="ok">ok</option>
                              <option value="delayed">delayed</option>
                              <option value="error">error</option>
                            </select>
                          </div>
                        </div>
                      </div>

                      <div style={floatingMenuFooterStyle}>
                        <button
                          type="button"
                          style={secondaryButtonStyle}
                          onClick={() => setFilters(defaultFilters)}
                        >
                          Clear Filters
                        </button>

                        <div style={toolbarRightInfoStyle}>
                          <div style={smallMutedDarkStyle}>Matching rows</div>
                          <div style={toolbarRightValueStyle}>
                            {filteredAndSortedQuotes.length}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div style={toolbarControlGroupStyle}>
                  <label style={labelStyle}>Reset</label>
                  <button
                    type="button"
                    style={secondaryButtonStyle}
                    onClick={() => {
                      setVisibleColumns(defaultVisibleColumns);
                      setColumnOrder(defaultColumnOrder);
                      setFilters(defaultFilters);
                      setSortOption("symbol-asc");
                      setOptionsControls(defaultOptionsControls);
                      setOptionsBySymbol({});
                      setAvailableExpiries([]);
                      setExpiryOptionsLoading(false);
                      setActiveViewId("default");
                      setOpenMenu(null);
                    }}
                    disabled={!selectedListId}
                  >
                    Reset
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </Panel>

      {(listsError || quotesError || optionsError) && (
        <Panel>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {listsError && (
              <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>
                Error: {listsError}
              </p>
            )}
            {quotesError && (
              <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>
                Error: {quotesError}
              </p>
            )}
            {optionsError && (
              <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>
                Error: {optionsError}
              </p>
            )}
          </div>
        </Panel>
      )}

      <Panel>
        <div style={panelHeaderStyle}>
          <div>
            <h2 style={panelTitleStyle}>Live Watchlist</h2>
            <p style={panelSubtitleStyle}>
              Quotes refresh every 30 seconds • options refresh every 60 seconds
            </p>
          </div>

          <div style={panelHeaderActionsStyle}>
            <div style={smallMutedDarkStyle}>
              {optionsLoading ? "Loading options..." : "Options live"}
            </div>

            <button
              type="button"
              style={iconButtonStyle}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "#f8fafc";
                e.currentTarget.style.borderColor = "#94a3b8";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "#ffffff";
                e.currentTarget.style.borderColor = "#e2e8f0";
              }}
              onClick={() => {
                const rawName = window.prompt("Save view as", "New View");
                const name = rawName?.trim();

                if (!name) return;

                const existingView = savedViews.find(
                  (view) => view.name.toLowerCase() === name.toLowerCase()
                );

                if (existingView) {
                  const shouldOverwrite = window.confirm(
                    `A view named "${existingView.name}" already exists. Overwrite it?`
                  );

                  if (!shouldOverwrite) return;

                  setActiveViewId(existingView.id);

                  setSavedViews((prev) =>
                    prev.map((view) =>
                      view.id === existingView.id
                        ? {
                            ...view,
                            name,
                            columns: visibleColumns,
                            columnOrder,
                            filters,
                            sort: sortOption,
                            optionsControls,
                          }
                        : view
                    )
                  );

                  return;
                }

                const newView: SavedView = {
                  id: crypto.randomUUID(),
                  name,
                  columns: visibleColumns,
                  columnOrder,
                  filters,
                  sort: sortOption,
                  optionsControls,
                };

                setActiveViewId(newView.id);
                setSavedViews((prev) => [...prev, newView]);
              }}
              title="Save View"
              aria-label="Save View"
            >
              <img src={saveIcon} alt="Save View" style={iconImageStyle} />
            </button>

            <button
              type="button"
              style={iconButtonStyle}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "#f8fafc";
                e.currentTarget.style.borderColor = "#94a3b8";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "#ffffff";
                e.currentTarget.style.borderColor = "#e2e8f0";
              }}
              onClick={onOpenWatchlistsPage}
              title="Edit Watchlist"
              aria-label="Edit Watchlist"
            >
              <img src={editIcon} alt="Edit Watchlist" style={iconImageStyle} />
            </button>
          </div>
        </div>

        <div
          style={{
            marginBottom: "12px",
            color: "#64748b",
            fontSize: "12px",
            fontWeight: 700,
          }}
        >
          Drag column headers to reorder them.
        </div>

        {!selectedListId ? (
          <p style={{ margin: 0 }}>Select a watchlist to load quotes.</p>
        ) : quotesLoading && quotes.length === 0 ? (
          <p style={{ margin: 0 }}>Loading quotes...</p>
        ) : !Array.isArray(quotes) || quotes.length === 0 ? (
          <p style={{ margin: 0 }}>No quotes found for this watchlist.</p>
        ) : filteredAndSortedQuotes.length === 0 ? (
          <p style={{ margin: 0 }}>No rows match the current filters.</p>
        ) : (
          <div style={watchlistTableShellStyle}>
            <div style={watchlistTableWrapStyle}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    {orderedVisibleColumns.map((columnKey, index) => {
                      const columnLabel =
                        dashboardColumnOptions.find((column) => column.key === columnKey)
                          ?.label ?? columnKey;

                      const headerStyle =
                        index === 0
                          ? stickyFirstHeaderCellStyle
                          : stickyHeaderCellStyle;

                      return (
                        <th
                          key={columnKey}
                          draggable
                          onDragStart={() => {
                            setDraggedColumnKey(columnKey);
                            setDragOverColumnKey(null);
                          }}
                          onDragOver={(e) => {
                            e.preventDefault();
                            if (draggedColumnKey && draggedColumnKey !== columnKey) {
                              setDragOverColumnKey(columnKey);
                            }
                          }}
                          onDragLeave={() => {
                            if (dragOverColumnKey === columnKey) {
                              setDragOverColumnKey(null);
                            }
                          }}
                          onDrop={() => {
                            if (!draggedColumnKey) return;
                            moveColumn(draggedColumnKey, columnKey);
                            setDraggedColumnKey(null);
                            setDragOverColumnKey(null);
                          }}
                          onDragEnd={() => {
                            setDraggedColumnKey(null);
                            setDragOverColumnKey(null);
                          }}
                          onDoubleClick={() => {
                            const sortKey = getSortKeyForColumn(columnKey);
                            if (!sortKey) return;

                            setSortOption((prev) => {
                              const [currentKey, currentDirection] = prev.split("-");
                              if (currentKey === sortKey) {
                                return `${sortKey}-${currentDirection === "asc" ? "desc" : "asc"}`;
                              }
                              return `${sortKey}-asc`;
                            });
                          }}
                          style={{
                            ...headerStyle,
                            cursor: "grab",
                            opacity: draggedColumnKey === columnKey ? 0.55 : 1,
                            boxShadow:
                              draggedColumnKey === columnKey
                                ? "inset 0 0 0 2px #94a3b8"
                                : dragOverColumnKey === columnKey
                                ? "inset 3px 0 0 #2563eb"
                                : "none",
                            background:
                              index === 0
                                ? "#f8fafc"
                                : headerStyle.background,
                          }}
                          title="Drag to reorder • Double-click to sort"
                        >
                          <span style={columnHeaderContentStyle}>
                            <span style={columnDragHandleStyle}>⋮⋮</span>
                            <span>
                              {columnLabel}
                              {getSortIndicatorForColumn(columnKey, sortOption)}
                            </span>
                          </span>
                        </th>
                      );
                    })}
                  </tr>
                </thead>

                <tbody>
                  {filteredAndSortedQuotes.map((quote, rowIndex) => (
                    <tr
                      key={quote.symbol}
                      style={{
                        background: rowIndex % 2 === 0 ? "#ffffff" : "#f8fafc",
                        transition: "background 0.15s ease",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = "#eef2f7";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background =
                          rowIndex % 2 === 0 ? "#ffffff" : "#f8fafc";
                      }}
                    >
                      {orderedVisibleColumns.map((columnKey, columnIndex) => (
                        <React.Fragment key={`${quote.symbol}-${columnKey}`}>
                          {renderCell(columnKey, quote, columnIndex === 0)}
                        </React.Fragment>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>
    </>
  );
}

type WatchlistsManagerPageProps = {
  lists: Watchlist[];
  refreshLists: () => Promise<void>;
  listsLoading: boolean;
  listsError: string;
};

function WatchlistsManagerPage({
  lists,
  refreshLists,
  listsLoading,
  listsError,
}: WatchlistsManagerPageProps) {
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

  function resetBuilder() {
    setEditorMode("idle");
    setEditingListId(null);
    setEditingListName("");
    setTickerText("");
    setExistingTickers([]);
  }

  function openCreateBuilder() {
    setEditorMode("create");
    setEditingListId(null);
    setEditingListName("");
    setTickerText("");
    setExistingTickers([]);
    setPageError("");
    setSuccessMessage("");
  }

  async function openEditBuilder(list: Watchlist) {
    setEditorMode("edit");
    setEditingListId(list.id);
    setEditingListName(list.name);
    setPageError("");
    setSuccessMessage("");

    const cachedTickers = tickersCache[list.id];

    if (cachedTickers) {
      setExistingTickers(cachedTickers);
      setTickerText(cachedTickers.map((ticker) => ticker.symbol).join("\n"));
      return;
    }

    try {
      setBuilderLoading(true);

      const tickers = await getTickers(list.id);
      setExistingTickers(tickers);
      setTickerText(tickers.map((ticker) => ticker.symbol).join("\n"));

      setTickersCache((prev) => ({
        ...prev,
        [list.id]: tickers,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load watchlist";
      setPageError(message);
    } finally {
      setBuilderLoading(false);
    }
  }

  async function handleDeleteWatchlist() {
    if (!editingListId || editorMode !== "edit") return;

    const confirmed = window.confirm(
      `Delete watchlist "${editingListName}"?\n\nThis will remove the watchlist and its tickers.`
    );

    if (!confirmed) return;

    try {
      setDeletingWatchlist(true);
      setPageError("");
      setSuccessMessage("");

      await deleteList(editingListId);
      await refreshLists();

            setTickersCache((prev) => {
        const next = { ...prev };
        delete next[editingListId];
        return next;
      });

      const deletedName = editingListName;
      resetBuilder();
      setSuccessMessage(`Deleted watchlist: ${deletedName}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete watchlist";
      setPageError(message);
    } finally {
      setDeletingWatchlist(false);
    }
  }

  async function handleSaveBuilder(e: React.FormEvent) {
    e.preventDefault();

    try {
      setSavingBuilder(true);
      setPageError("");
      setSuccessMessage("");

      const parsedSymbols = tickerText
        .split(/[\s,]+/)
        .map((symbol) => symbol.trim().toUpperCase())
        .filter(Boolean);

      const uniqueSymbols = Array.from(new Set(parsedSymbols));

      if (editorMode === "create") {
        const trimmedName = editingListName.trim();

        if (!trimmedName) {
          setPageError("Watchlist name is required.");
          return;
        }

        const created = await createList(trimmedName);

        for (const symbol of uniqueSymbols) {
          await createTicker(created.id, symbol);
        }

        await refreshLists();
        await openEditBuilder(created);
        setSuccessMessage(`Created watchlist: ${created.name}`);
        return;
      }

      if (editorMode === "edit" && editingListId) {
        const trimmedName = editingListName.trim();

        if (!trimmedName) {
          setPageError("Watchlist name is required.");
          return;
        }

        const currentList = lists.find((list) => list.id === editingListId);

        if (!currentList) {
          setPageError("Watchlist not found.");
          return;
        }

        if (currentList.name !== trimmedName) {
          await updateList(editingListId, trimmedName);
        }

        const currentSymbols = existingTickers.map((ticker) => ticker.symbol.toUpperCase());

        const tickerIdsBySymbol = new Map(
          existingTickers.map((ticker) => [ticker.symbol.toUpperCase(), ticker.id])
        );

        const symbolsToAdd = uniqueSymbols.filter((symbol) => !currentSymbols.includes(symbol));
        const symbolsToDelete = currentSymbols.filter(
          (symbol) => !uniqueSymbols.includes(symbol)
        );

        for (const symbol of symbolsToAdd) {
          await createTicker(editingListId, symbol);
        }

        for (const symbol of symbolsToDelete) {
          const tickerId = tickerIdsBySymbol.get(symbol);
          if (tickerId) {
            await deleteTicker(editingListId, tickerId);
          }
        }

        await refreshLists();

        const refreshedTickers = await getTickers(editingListId);
                setTickersCache((prev) => ({
          ...prev,
          [editingListId]: refreshedTickers,
        }));
        setExistingTickers(refreshedTickers);
        setTickerText(refreshedTickers.map((ticker) => ticker.symbol).join("\n"));
        setSuccessMessage(`Saved watchlist: ${trimmedName}`);
        return;
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save watchlist";
      setPageError(message);
    } finally {
      setSavingBuilder(false);
    }
  }

  return (
    <>
      <div style={headerRowStyle}>
        <div>
          <h1 style={pageTitleStyle}>Watchlists</h1>
          <p style={pageSubtitleStyle}>Create and manage your watchlists</p>
        </div>
      </div>

      {(pageError || successMessage || listsError) && (
        <Panel>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {pageError && (
              <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>
                Error: {pageError}
              </p>
            )}
            {listsError && (
              <p style={{ margin: 0, color: "#dc2626", fontWeight: 600 }}>
                Error: {listsError}
              </p>
            )}
            {successMessage && (
              <p style={{ margin: 0, color: "#166534", fontWeight: 600 }}>
                {successMessage}
              </p>
            )}
          </div>
        </Panel>
      )}

      <div style={watchlistAdminGridStyle}>
        <Panel>
          <div style={panelHeaderStyle}>
            <div>
              <h2 style={panelTitleStyle}>
                {editorMode === "create"
                  ? "Create Watchlist"
                  : editorMode === "edit"
                  ? "Edit Watchlist"
                  : "Watchlist Builder"}
              </h2>
              <p style={panelSubtitleStyle}>
                {editorMode === "idle"
                  ? "Create a new watchlist or click an existing one to edit it"
                  : editorMode === "create"
                  ? "Enter a name and all tickers at once"
                  : "Edit the watchlist name and tickers, then save"}
              </p>
            </div>
          </div>

          {editorMode === "idle" ? (
            <button type="button" style={primaryButtonStyle} onClick={openCreateBuilder}>
              Create Watchlist
            </button>
          ) : (
            <form onSubmit={handleSaveBuilder} style={loginFormStyle}>
              <div style={fieldGroupFullStyle}>
                <label style={labelStyle}>Watchlist Name</label>
                <input
                  type="text"
                  value={editingListName}
                  onChange={(e) => setEditingListName(e.target.value)}
                  style={inputStyle}
                  placeholder="Example: Wheel Strategy"
                  disabled={savingBuilder || deletingWatchlist}
                />
              </div>

              <div style={fieldGroupFullStyle}>
                <label style={labelStyle}>Tickers</label>
                <textarea
                  value={tickerText}
                  onChange={(e) => setTickerText(e.target.value)}
                  style={textareaStyle}
                  placeholder={"AAPL\nMSFT\nNVDA\nTSLL"}
                  disabled={savingBuilder || deletingWatchlist}
                />
              </div>

              <div style={editorActionsStyle}>
                <button
                  type="submit"
                  style={primaryButtonStyle}
                  disabled={savingBuilder || deletingWatchlist}
                >
                  {savingBuilder ? "Saving..." : "Save Watchlist"}
                </button>

                <button
                  type="button"
                  style={secondaryButtonStyle}
                  onClick={() => {
                    resetBuilder();
                    setPageError("");
                  }}
                  disabled={savingBuilder || deletingWatchlist}
                >
                  Cancel
                </button>
              </div>

              {editorMode === "edit" && editingListId && (
                <div style={editorActionsStyle}>
                  <button
                    type="button"
                    onClick={handleDeleteWatchlist}
                    disabled={savingBuilder || deletingWatchlist}
                    style={dangerButtonStyle}
                  >
                    {deletingWatchlist ? "Deleting..." : "Delete Watchlist"}
                  </button>
                </div>
              )}
            </form>
          )}
        </Panel>

        <Panel>
          <div style={panelHeaderStyle}>
            <div>
              <h2 style={panelTitleStyle}>Manage Watchlists</h2>
            </div>
          </div>

          {builderLoading ? (
            <p style={{ margin: 0 }}>Loading watchlist...</p>
          ) : listsLoading ? (
            <p style={{ margin: 0 }}>Loading watchlists...</p>
          ) : lists.length === 0 ? (
            <p style={{ margin: 0 }}>No watchlists found.</p>
          ) : (
            <div style={listCardsWrapStyle}>
              {lists.map((list) => {
                const isEditing = list.id === editingListId;

                return (
                  <button
                    key={list.id}
                    type="button"
                    onClick={() => openEditBuilder(list)}
                    style={{
                      ...watchlistCardButtonStyle,
                      borderColor: isEditing ? "#0f172a" : "#e2e8f0",
                      background: isEditing ? "#f8fafc" : "#ffffff",
                    }}
                  >
                    <div>
                      <div style={watchlistNameStyle}>{list.name}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return <section style={panelStyle}>{children}</section>;
}

function normalizeColumnOrder(order: ColumnKey[]): ColumnKey[] {
  const next = [...order];

  for (const key of defaultColumnOrder) {
    if (!next.includes(key)) {
      next.push(key);
    }
  }

  return next.filter((key, index) => next.indexOf(key) === index);
}

function compareValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined
): number {
  const aIsMissing = a === null || a === undefined;
  const bIsMissing = b === null || b === undefined;

  if (aIsMissing && bIsMissing) return 0;
  if (aIsMissing) return -1;
  if (bIsMissing) return 1;

  if (typeof a === "number" && typeof b === "number") {
    if (a > b) return 1;
    if (a < b) return -1;
    return 0;
  }

  const aString = String(a);
  const bString = String(b);

  if (aString > bString) return 1;
  if (aString < bString) return -1;
  return 0;
}

function toSafeNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;

  if (typeof value === "number") {
    return Number.isNaN(value) ? null : value;
  }

  const cleaned = String(value).replace(/[^0-9.-]/g, "");
  if (!cleaned) return null;

  const parsed = Number(cleaned);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return value.toFixed(2);
}

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `$${value.toFixed(2)}`;
}

function formatMetric(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "-";
  return value.toFixed(digits);
}

function formatSignedMetric(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function formatSignedNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatTimeShort(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleTimeString();
}

function getChangeColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "#64748b";
  if (value > 0) return "#166534";
  if (value < 0) return "#991b1b";
  return "#475569";
}

function getMoneynessRank(value: MoneynessState): number {
  if (value === "ITM") return 0;
  if (value === "ATM") return 1;
  if (value === "OTM") return 2;
  return 3;
}

const loginPageStyle: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background:
    "linear-gradient(135deg, #0f172a 0%, #111827 45%, #1e293b 100%)",
  padding: "24px",
};

const loginCardStyle: React.CSSProperties = {
  width: "100%",
  maxWidth: "440px",
  background: "#ffffff",
  borderRadius: "20px",
  padding: "32px",
  boxShadow: "0 20px 40px rgba(0, 0, 0, 0.20)",
};

const loginBrandStyle: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: 800,
  color: "#475569",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: "16px",
};

const loginTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "34px",
  fontWeight: 800,
  color: "#0f172a",
};

const loginSubtitleStyle: React.CSSProperties = {
  margin: "10px 0 24px 0",
  color: "#64748b",
  lineHeight: 1.5,
};

const loginFormStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "16px",
};

const loginErrorStyle: React.CSSProperties = {
  margin: 0,
  color: "#dc2626",
  fontWeight: 600,
};

const loginButtonStyle: React.CSSProperties = {
  border: "none",
  borderRadius: "12px",
  padding: "14px 18px",
  background: "#0f172a",
  color: "#ffffff",
  fontSize: "15px",
  fontWeight: 700,
  cursor: "pointer",
};

const appShellStyle: React.CSSProperties = {
  minHeight: "100vh",
  background: "#f1f5f9",
  color: "#0f172a",
};

const topbarStyle: React.CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 100,
  background: "#ffffff",
  borderBottom: "1px solid #e2e8f0",
  boxShadow: "0 4px 18px rgba(15, 23, 42, 0.04)",
};

const topbarInnerStyle: React.CSSProperties = {
  maxWidth: "1800px",
  margin: "0 auto",
  padding: "18px 24px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "20px",
};

const topbarLeftStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "28px",
  flexWrap: "wrap",
};

const topbarLogoStyle: React.CSSProperties = {
  fontSize: "24px",
  fontWeight: 900,
  letterSpacing: "-0.03em",
  color: "#0f172a",
  whiteSpace: "nowrap",
};

const topbarNavStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  flexWrap: "wrap",
};

const topbarNavButtonStyle: React.CSSProperties = {
  border: "1px solid transparent",
  background: "transparent",
  color: "#475569",
  borderRadius: "12px",
  padding: "10px 14px",
  fontSize: "14px",
  fontWeight: 700,
  cursor: "pointer",
};

const topbarNavButtonActiveStyle: React.CSSProperties = {
  ...topbarNavButtonStyle,
  background: "#0f172a",
  color: "#ffffff",
  border: "1px solid #0f172a",
};

const topbarRightStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "14px",
  flexWrap: "wrap",
  justifyContent: "flex-end",
};

const topbarMetaStyle: React.CSSProperties = {
  padding: "10px 14px",
  background: "#f8fafc",
  border: "1px solid #e2e8f0",
  borderRadius: "14px",
};

const topbarMetaLabelStyle: React.CSSProperties = {
  fontSize: "11px",
  color: "#64748b",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontWeight: 800,
  marginBottom: "2px",
};

const topbarMetaValueStyle: React.CSSProperties = {
  fontSize: "13px",
  color: "#0f172a",
  fontWeight: 800,
};

const topbarLogoutButtonStyle: React.CSSProperties = {
  border: "1px solid #cbd5e1",
  background: "#ffffff",
  color: "#0f172a",
  borderRadius: "12px",
  padding: "10px 14px",
  fontWeight: 700,
  cursor: "pointer",
};

const contentAreaStyle: React.CSSProperties = {
  width: "100%",
};

const contentInnerStyle: React.CSSProperties = {
  width: "100%",
  maxWidth: "1800px",
  margin: "0 auto",
  padding: "28px 24px 32px 24px",
};

const headerRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: "26px",
  gap: "16px",
  flexWrap: "wrap",
};

const pageTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "36px",
  fontWeight: 900,
  letterSpacing: "-0.03em",
};

const pageSubtitleStyle: React.CSSProperties = {
  margin: "8px 0 0 0",
  color: "#64748b",
  fontSize: "15px",
};

const panelStyle: React.CSSProperties = {
  background: "#ffffff",
  border: "1px solid #e2e8f0",
  borderRadius: "20px",
  padding: "22px",
  boxShadow: "0 8px 24px rgba(15, 23, 42, 0.05)",
};

const panelHeaderStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: "18px",
};

const panelHeaderActionsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  flexWrap: "wrap",
};

const iconImageStyle: React.CSSProperties = {
  width: "16px",
  height: "16px",
};

const iconButtonStyle: React.CSSProperties = {
  width: "34px",
  height: "34px",
  border: "1px solid #e2e8f0",
  borderRadius: "10px",
  background: "#ffffff",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
};

const panelTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "22px",
  fontWeight: 900,
  letterSpacing: "-0.02em",
};

const panelSubtitleStyle: React.CSSProperties = {
  margin: "6px 0 0 0",
  color: "#64748b",
  fontSize: "14px",
};

const fieldGroupStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  minWidth: "240px",
  maxWidth: "520px",
};

const fieldGroupFullStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  width: "100%",
};

const labelStyle: React.CSSProperties = {
  fontSize: "13px",
  fontWeight: 800,
  color: "#334155",
  letterSpacing: "0.01em",
};

const inputStyle: React.CSSProperties = {
  padding: "14px 14px",
  borderRadius: "14px",
  border: "1px solid #cbd5e1",
  fontSize: "14px",
  background: "#fff",
  outline: "none",
  boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.03)",
};

const textareaStyle: React.CSSProperties = {
  minHeight: "220px",
  padding: "14px 14px",
  borderRadius: "14px",
  border: "1px solid #cbd5e1",
  fontSize: "14px",
  background: "#fff",
  resize: "vertical",
  fontFamily: "inherit",
  outline: "none",
  boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.03)",
};

const selectStyle: React.CSSProperties = {
  padding: "12px 14px",
  borderRadius: "14px",
  border: "1px solid #cbd5e1",
  fontSize: "14px",
  background: "#fff",
  outline: "none",
  boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.03)",
};

const primaryButtonStyle: React.CSSProperties = {
  border: "none",
  borderRadius: "14px",
  padding: "14px 18px",
  background: "#0f172a",
  color: "#ffffff",
  fontSize: "15px",
  fontWeight: 800,
  cursor: "pointer",
  boxShadow: "0 8px 18px rgba(15, 23, 42, 0.16)",
};

const secondaryButtonStyle: React.CSSProperties = {
  border: "1px solid #cbd5e1",
  borderRadius: "12px",
  padding: "10px 14px",
  background: "#ffffff",
  color: "#0f172a",
  fontSize: "14px",
  fontWeight: 700,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const viewButtonStyle: React.CSSProperties = {
  ...secondaryButtonStyle,
  minWidth: "180px",
  justifyContent: "space-between",
  display: "inline-flex",
  alignItems: "center",
};

const secondaryButtonActiveStyle: React.CSSProperties = {
  ...secondaryButtonStyle,
  background: "#0f172a",
  color: "#ffffff",
  border: "1px solid #0f172a",
};

const dangerButtonStyle: React.CSSProperties = {
  border: "1px solid #fecaca",
  borderRadius: "12px",
  padding: "10px 14px",
  background: "#ffffff",
  color: "#991b1b",
  fontSize: "14px",
  fontWeight: 800,
  cursor: "pointer",
};

const editorActionsStyle: React.CSSProperties = {
  display: "flex",
  gap: "12px",
  flexWrap: "wrap",
};

const listCardsWrapStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "14px",
};

const watchlistCardStyle: React.CSSProperties = {
  border: "1px solid #e2e8f0",
  borderRadius: "18px",
  padding: "18px",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: "16px",
  boxShadow: "0 4px 14px rgba(15, 23, 42, 0.04)",
};

const watchlistCardButtonStyle: React.CSSProperties = {
  ...watchlistCardStyle,
  width: "100%",
  background: "#ffffff",
  cursor: "pointer",
  textAlign: "left",
};

const watchlistNameStyle: React.CSSProperties = {
  fontSize: "18px",
  fontWeight: 900,
  color: "#0f172a",
  marginBottom: "4px",
  letterSpacing: "-0.02em",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "separate",
  borderSpacing: 0,
  background: "#ffffff",
};

const bodyCellStyle: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid #eef2f7",
  fontSize: "13px",
  color: "#0f172a",
  whiteSpace: "nowrap",
};

const statusBadgeStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "6px 10px",
  borderRadius: "999px",
  fontWeight: 800,
  fontSize: "12px",
  textTransform: "uppercase",
};

const moneynessBadgeStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "6px 10px",
  borderRadius: "999px",
  fontWeight: 800,
  fontSize: "12px",
  textTransform: "uppercase",
};

const optionSideBadgeStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "5px 10px",
  borderRadius: "999px",
  fontWeight: 800,
  fontSize: "12px",
  background: "#e2e8f0",
  color: "#334155",
};

const toolbarShellStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "14px",
  minHeight: "108px",
};

const toolbarPrimaryRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-end",
  gap: "16px",
  flexWrap: "wrap",
};

const toolbarPrimaryLeftStyle: React.CSSProperties = {
  display: "flex",
  gap: "10px",
  alignItems: "flex-end",
  flexWrap: "wrap",
  minHeight: "72px",
  flex: 1,
};

const toolbarPrimaryActionsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  minHeight: "72px",
};

const toolbarPrimaryRightStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-end",
  minHeight: "72px",
};

const toolbarSecondaryRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-end",
  gap: "16px",
  flexWrap: "wrap",
  minHeight: "72px",
};

const toolbarSecondaryGroupStyle: React.CSSProperties = {
  display: "flex",
  gap: "10px",
  alignItems: "flex-end",
  flexWrap: "wrap",
  minHeight: "72px",
};

const toolbarMenuAnchorStyle: React.CSSProperties = {
  position: "relative",
  display: "flex",
  flexDirection: "column",
};

const floatingMenuStyle: React.CSSProperties = {
  position: "absolute",
  top: "calc(100% + 10px)",
  left: 0,
  minWidth: "340px",
  width: "min(340px, calc(100vw - 96px))",
  padding: "18px",
  borderRadius: "18px",
  border: "1px solid #e2e8f0",
  background: "#ffffff",
  boxShadow: "0 20px 40px rgba(15, 23, 42, 0.16)",
  zIndex: 40,
};

const floatingMenuStyleClamped: React.CSSProperties = {
  ...floatingMenuStyle,
  left: "auto",
  right: 0,
};

const floatingMenuStyleClampedWide: React.CSSProperties = {
  ...floatingMenuStyleClamped,
  minWidth: "560px",
  width: "min(560px, calc(100vw - 96px))",
};

const floatingMenuHeaderStyle: React.CSSProperties = {
  marginBottom: "14px",
};

const floatingMenuTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "18px",
  fontWeight: 900,
  letterSpacing: "-0.02em",
  color: "#0f172a",
};

const floatingMenuSubtitleStyle: React.CSSProperties = {
  margin: "6px 0 0 0",
  color: "#64748b",
  fontSize: "13px",
};

const floatingMenuFooterStyle: React.CSSProperties = {
  marginTop: "16px",
  display: "flex",
  gap: "12px",
  flexWrap: "wrap",
  alignItems: "center",
};

const floatingScrollableContentStyle: React.CSSProperties = {
  maxHeight: "360px",
  overflowY: "auto",
  overflowX: "hidden",
  paddingRight: "4px",
};

const floatingScrollableContentStyleWide: React.CSSProperties = {
  ...floatingScrollableContentStyle,
  maxHeight: "420px",
};

const sortOptionsGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: "10px",
};

const sortOptionButtonStyle: React.CSSProperties = {
  border: "1px solid #e2e8f0",
  borderRadius: "12px",
  padding: "12px 14px",
  background: "#f8fafc",
  color: "#0f172a",
  fontSize: "14px",
  fontWeight: 700,
  cursor: "pointer",
  textAlign: "left",
};

const sortOptionActiveStyle: React.CSSProperties = {
  ...sortOptionButtonStyle,
  background: "#0f172a",
  color: "#ffffff",
  border: "1px solid #0f172a",
};

const toolbarControlGroupStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
  minWidth: 0,
  minHeight: "72px",
  justifyContent: "flex-end",
};

const compactSelectStyle: React.CSSProperties = {
  padding: "12px 14px",
  borderRadius: "14px",
  border: "1px solid #cbd5e1",
  fontSize: "14px",
  background: "#fff",
  outline: "none",
  boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.03)",
  width: "220px",
  minWidth: "220px",
};

const compactNarrowSelectStyle: React.CSSProperties = {
  padding: "12px 14px",
  borderRadius: "14px",
  border: "1px solid #cbd5e1",
  fontSize: "14px",
  background: "#fff",
  outline: "none",
  boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.03)",
  width: "160px",
  minWidth: "160px",
};

const toolbarRightInfoStyle: React.CSSProperties = {
  minHeight: "48px",
  padding: "12px 14px",
  borderRadius: "14px",
  background: "#f8fafc",
  border: "1px solid #e2e8f0",
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
};

const toolbarRightValueStyle: React.CSSProperties = {
  fontWeight: 800,
  color: "#0f172a",
  fontSize: "14px",
};

const smallMutedDarkStyle: React.CSSProperties = {
  color: "#64748b",
  fontSize: "12px",
  marginBottom: "4px",
};

const watchlistTableShellStyle: React.CSSProperties = {
  border: "1px solid #e2e8f0",
  borderRadius: "16px",
  overflow: "hidden",
  background: "#ffffff",
};

const watchlistTableWrapStyle: React.CSSProperties = {
  overflowX: "auto",
  overflowY: "auto",
  maxHeight: "640px",
};

const stickyHeaderCellStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "12px 12px",
  background: "#f8fafc",
  color: "#475569",
  fontSize: "12px",
  fontWeight: 800,
  borderBottom: "1px solid #e2e8f0",
  position: "sticky",
  top: 0,
  zIndex: 1,
  whiteSpace: "nowrap",
};

const columnHeaderContentStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "6px",
};

const columnDragHandleStyle: React.CSSProperties = {
  fontSize: "12px",
  color: "#94a3b8",
  cursor: "grab",
  userSelect: "none",
};

const stickyFirstHeaderCellStyle: React.CSSProperties = {
  ...stickyHeaderCellStyle,
  left: 0,
  zIndex: 3,
  background: "#f8fafc",
};

const stickyFirstBodyCellStyle: React.CSSProperties = {
  ...bodyCellStyle,
  position: "sticky",
  left: 0,
  zIndex: 2,
  background: "#ffffff",
  fontWeight: 800,
};

const watchlistAdminGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "420px 1fr",
  gap: "22px",
  marginTop: "22px",
  alignItems: "start",
};

const columnsMenuSectionStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "10px",
  marginBottom: "18px",
};

const columnsMenuSectionTitleStyle: React.CSSProperties = {
  fontSize: "12px",
  fontWeight: 900,
  color: "#475569",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const columnsPanelGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: "12px",
};

const filtersPanelGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: "16px",
};

const columnToggleLabelStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  padding: "12px 14px",
  border: "1px solid #e2e8f0",
  borderRadius: "14px",
  background: "#f8fafc",
  fontWeight: 700,
  color: "#0f172a",
};

export default App;