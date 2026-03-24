const API_BASE = "http://127.0.0.1:8000";

export type LoginResponse = {
  access_token: string;
  token_type: string;
};

function getToken(): string | null {
  return localStorage.getItem("token");
}

export function saveToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

export function isLoggedIn(): boolean {
  const token = getToken();
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    const exp = payload.exp;
    if (exp && Date.now() / 1000 > exp) {
      localStorage.removeItem("token");
      return false;
    }
    return true;
  } catch {
    return !!token;
  }
}

function getAuthHeaders(): HeadersInit {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

/* ========================= AUTH ========================= */

export async function login(username: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: username, password }),
  });
  return handleResponse<LoginResponse>(response);
}

/* ========================= TYPES ========================= */

export type Watchlist = {
  id: number;
  name: string;
  created_at?: string;
};

export type WatchlistQuote = {
  symbol: string;
  last_price: number | null;
  change: number | null;
  change_percent: number | null;
  updated_at: string | null;
  status: string | null;
  error?: string | null;
  // Options data from cache
  strike?: number | null;
  expiry?: string | null;
  option_side?: string | null;
  premium?: number | null;
  return_percent?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  moneyness?: string | null;
  available_expiries?: string[];
};

export type TickerItem = {
  id: number;
  list_id: number;
  symbol: string;
};

export type PolygonOptionQueryParams = {
  expiryScope?: "weekly" | "near" | "far" | "all" | "fixed-horizon" | "manual";
  horizonMode?: "1m" | "6m" | "1y";
  optionSide?: "calls" | "puts" | "both";
  premiumMode?: "mid" | "last" | "bid" | "ask";
  manualExpiry?: string | null;
  targetMode?: "delta" | "percent-otm";
  targetDelta?: string | number | null;
  targetPercentOtm?: string | number | null;
};

export type PolygonResolvedOption = {
  optionTicker: string;
  optionSide: "Call" | "Put";
  expiry: string;
  strike: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  premium: number | null;
  returnPercent: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  rho: number | null;
  underlyingPrice: number | null;
  moneyness: "ITM" | "ATM" | "OTM" | string | null;
};

export type PolygonOptionResolvedResponse = {
  symbol: string;
  expiryScope: string;
  horizonMode: string | null;
  optionSideRequest: string;
  premiumMode: string;
  availableExpiries: string[];
  selectedExpiry: string | null;
  contractsEvaluated: number;
  resolved: PolygonResolvedOption | null;
};

export type ScanResultRow = {
  id: number;
  list_id: number;
  ticker_id: number;
  symbol: string;
  run_at: string;
  underlying_price: number | null;
  option_type: string | null;
  expiry: string | null;
  strike: number | null;
  delta: number | null;
  premium: number | null;
  return_pct: number | null;
  status: string;
  error: string | null;
  raw_json: Record<string, any> | null;
};

export type ScanHistoryRunSummary = {
  run_at: string;
  total: number;
  ok: number;
  errors: number;
};

/* ========================= API CALLS ========================= */

export async function getLists(): Promise<Watchlist[]> {
  const response = await fetch(`${API_BASE}/lists`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return handleResponse<Watchlist[]>(response);
}

export async function createList(name: string): Promise<Watchlist> {
  const response = await fetch(`${API_BASE}/lists`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ name }),
  });
  return handleResponse<Watchlist>(response);
}

export async function updateList(listId: number, name: string): Promise<Watchlist> {
  const response = await fetch(`${API_BASE}/lists/${listId}`, {
    method: "PATCH",
    headers: getAuthHeaders(),
    body: JSON.stringify({ name }),
  });
  return handleResponse<Watchlist>(response);
}

export async function deleteList(listId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/lists/${listId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  await handleResponse<unknown>(response);
}

export async function getTickers(listId: number): Promise<TickerItem[]> {
  const response = await fetch(`${API_BASE}/lists/${listId}/tickers`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return handleResponse<TickerItem[]>(response);
}

export async function getWatchlistQuotes(listId: number): Promise<WatchlistQuote[]> {
  const response = await fetch(`${API_BASE}/lists/${listId}/quotes`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  const data = await handleResponse<{
    list_id: number;
    count: number;
    quotes: WatchlistQuote[];
  }>(response);
  return Array.isArray(data.quotes) ? data.quotes : [];
}

export async function createTicker(listId: number, symbol: string): Promise<TickerItem> {
  const response = await fetch(`${API_BASE}/lists/${listId}/tickers`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ symbol }),
  });
  return handleResponse<TickerItem>(response);
}

export async function deleteTicker(listId: number, tickerId: number): Promise<void> {
  const response = await fetch(`${API_BASE}/lists/${listId}/tickers/${tickerId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  await handleResponse<unknown>(response);
}

export async function getPolygonOptionResolved(
  symbol: string,
  params: PolygonOptionQueryParams = {}
): Promise<PolygonOptionResolvedResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("expiry_scope", params.expiryScope ?? "weekly");
  searchParams.set("horizon_mode", params.horizonMode ?? "1m");
  searchParams.set("option_side", params.optionSide ?? "calls");
  searchParams.set("premium_mode", params.premiumMode ?? "mid");
  if (params.manualExpiry) searchParams.set("manual_expiry", params.manualExpiry);
  if (params.targetMode) searchParams.set("target_mode", params.targetMode);
  if (params.targetDelta != null && String(params.targetDelta).trim() !== "")
    searchParams.set("target_delta", String(params.targetDelta));
  if (params.targetPercentOtm != null && String(params.targetPercentOtm).trim() !== "")
    searchParams.set("target_percent_otm", String(params.targetPercentOtm));

  const response = await fetch(
    `${API_BASE}/polygon/options/${encodeURIComponent(symbol)}?${searchParams.toString()}`,
    { headers: getAuthHeaders() }
  );

  const raw = await handleResponse<Record<string, unknown>>(response);

  return {
    symbol: typeof raw.symbol === "string" ? raw.symbol : symbol.toUpperCase(),
    expiryScope: typeof raw.expiryScope === "string" ? raw.expiryScope : params.expiryScope ?? "weekly",
    horizonMode: typeof raw.horizonMode === "string" ? raw.horizonMode : params.horizonMode ?? null,
    optionSideRequest: typeof raw.optionSideRequest === "string" ? raw.optionSideRequest : params.optionSide ?? "calls",
    premiumMode: typeof raw.premiumMode === "string" ? raw.premiumMode : params.premiumMode ?? "mid",
    availableExpiries: Array.isArray(raw.availableExpiries)
      ? raw.availableExpiries.filter((v): v is string => typeof v === "string")
      : [],
    selectedExpiry: typeof raw.selectedExpiry === "string" ? raw.selectedExpiry : null,
    contractsEvaluated: typeof raw.contractsEvaluated === "number" ? raw.contractsEvaluated : 0,
    resolved: raw.resolved as PolygonResolvedOption | null,
  };
}