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

/* =========================
AUTH
========================= */

export async function login(
  username: string,
  password: string
): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: username,
      password,
    }),
  });

  return handleResponse<LoginResponse>(response);
}

/* =========================
SCAN TYPES
========================= */

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

/* =========================
LIST TYPES
========================= */

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
  bid?: number | null;
  ask?: number | null;
  volume?: number | null;
  updated_at: string | null;
  status: string | null;
  error?: string | null;
};

export type TickerItem = {
  id: number;
  list_id: number;
  symbol: string;
};

/* =========================
OPTIONS TYPES
========================= */

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

/* =========================
API CALLS
========================= */

export async function getLatestScanResults(
  listId: number
): Promise<ScanResultRow[]> {
  const response = await fetch(
    `${API_BASE}/lists/${listId}/scan/results/latest`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );

  return handleResponse<ScanResultRow[]>(response);
}

export async function getScanHistoryRuns(
  listId: number
): Promise<ScanHistoryRunSummary[]> {
  const response = await fetch(
    `${API_BASE}/lists/${listId}/scan/history/runs`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );

  return handleResponse<ScanHistoryRunSummary[]>(response);
}

export async function getScanHistoryRunDetail(
  listId: number,
  runAt: string
): Promise<ScanResultRow[]> {
  const response = await fetch(
    `${API_BASE}/lists/${listId}/scan/history/${encodeURIComponent(runAt)}`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );

  return handleResponse<ScanResultRow[]>(response);
}

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

export async function updateList(
  listId: number,
  name: string
): Promise<Watchlist> {
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

export async function getWatchlistQuotes(
  listId: number
): Promise<WatchlistQuote[]> {
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

export async function createTicker(
  listId: number,
  symbol: string
): Promise<TickerItem> {
  const response = await fetch(`${API_BASE}/lists/${listId}/tickers`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ symbol }),
  });

  return handleResponse<TickerItem>(response);
}

export async function deleteTicker(
  listId: number,
  tickerId: number
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/lists/${listId}/tickers/${tickerId}`,
    {
      method: "DELETE",
      headers: getAuthHeaders(),
    }
  );

  await handleResponse<unknown>(response);
}

function toQueryString(params: Record<string, string>) {
  const searchParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== "") {
      searchParams.set(key, value);
    }
  });

  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

function normalizeNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeResolvedOption(value: unknown): PolygonResolvedOption | null {
  if (!value || typeof value !== "object") return null;

  const item = value as Record<string, unknown>;

  const optionSide =
    item.optionSide === "Call" || item.optionSide === "Put"
      ? item.optionSide
      : "Call";

  const bid = normalizeNullableNumber(item.bid);
  const ask = normalizeNullableNumber(item.ask);
  const last = normalizeNullableNumber(item.last);

  return {
    optionTicker:
      typeof item.optionTicker === "string" ? item.optionTicker : "",
    optionSide,
    expiry: typeof item.expiry === "string" ? item.expiry : "",
    strike: normalizeNullableNumber(item.strike),

    bid,
    ask,
    last,

    premium:
      normalizeNullableNumber(item.premium) ??
      last ??
      (bid !== null && ask !== null ? (bid + ask) / 2 : bid ?? ask),

    returnPercent: normalizeNullableNumber(item.returnPercent),

    delta: normalizeNullableNumber(item.delta),
    gamma: normalizeNullableNumber(item.gamma),
    theta: normalizeNullableNumber(item.theta),
    vega: normalizeNullableNumber(item.vega),
    rho: normalizeNullableNumber(item.rho),

    underlyingPrice: normalizeNullableNumber(item.underlyingPrice),

    moneyness:
      typeof item.moneyness === "string" || item.moneyness === null
        ? (item.moneyness as PolygonResolvedOption["moneyness"])
        : null,
  };
}

export async function getPolygonOptionResolved(
  symbol: string,
  params: PolygonOptionQueryParams = {}
): Promise<PolygonOptionResolvedResponse> {
  const query = toQueryString({
    expiry_scope: params.expiryScope ?? "weekly",
    horizon_mode: params.horizonMode ?? "1m",
    option_side: params.optionSide ?? "calls",
    premium_mode: params.premiumMode ?? "mid",
    ...(params.manualExpiry ? { manual_expiry: params.manualExpiry } : {}),
    ...(params.targetMode ? { target_mode: params.targetMode } : {}),
    ...(params.targetDelta !== null &&
    params.targetDelta !== undefined &&
    String(params.targetDelta).trim() !== ""
      ? { target_delta: String(params.targetDelta) }
      : {}),
    ...(params.targetPercentOtm !== null &&
    params.targetPercentOtm !== undefined &&
    String(params.targetPercentOtm).trim() !== ""
      ? { target_percent_otm: String(params.targetPercentOtm) }
      : {}),
  });

  const response = await fetch(
    `${API_BASE}/polygon/options/${encodeURIComponent(symbol)}${query}`,
    {
      headers: getAuthHeaders(),
    }
  );

  const raw = await handleResponse<Record<string, unknown>>(response);

  return {
    symbol: typeof raw.symbol === "string" ? raw.symbol : symbol.toUpperCase(),
    expiryScope:
      typeof raw.expiryScope === "string"
        ? raw.expiryScope
        : params.expiryScope ?? "weekly",
    horizonMode:
      typeof raw.horizonMode === "string"
        ? raw.horizonMode
        : params.horizonMode ?? null,
    optionSideRequest:
      typeof raw.optionSideRequest === "string"
        ? raw.optionSideRequest
        : params.optionSide ?? "calls",
    premiumMode:
      typeof raw.premiumMode === "string"
        ? raw.premiumMode
        : params.premiumMode ?? "mid",
    availableExpiries: Array.isArray(raw.availableExpiries)
      ? raw.availableExpiries.filter(
          (value): value is string => typeof value === "string"
        )
      : [],
    selectedExpiry:
      typeof raw.selectedExpiry === "string" ? raw.selectedExpiry : null,
    contractsEvaluated: normalizeNullableNumber(raw.contractsEvaluated) ?? 0,
    resolved: normalizeResolvedOption(raw.resolved),
  };
}