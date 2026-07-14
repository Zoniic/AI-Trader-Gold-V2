import "server-only";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type RunSummary = {
  run_id: string;
  strategy: string;
  started_at: string;
  finished_at: string | null;
  initial_balance: number | null;
  final_balance: number | null;
  total_trades: number | null;
  win_rate_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  expectancy: number | null;
  halted_at: string | null;
  halt_reason: string | null;
  timeframe: string | null;
  config: string | null;
};

export type Trade = {
  id: number;
  direction: string;
  entry_time: string;
  entry: number;
  sl: number;
  tp: number;
  lot: number;
  exit_time: string | null; // null = ยังเปิดอยู่
  exit_price: number | null;
  pnl: number | null;
  outcome: string | null;
  regime: string | null;
  reason: string | null; // เหตุผล/confluence ตอนเข้าไม้
  discussion: string | null; // JSON ความเห็นนักเทรด 5 คนตอนอนุมัติไม้นี้
  pnl_r: number | null; // กำไร/ขาดทุนเป็นเท่าของความเสี่ยง (R multiple)
  mae_r: number | null; // ราคาสวนลึกสุดระหว่างถือ (R)
  mfe_r: number | null; // ราคาเป็นใจไกลสุดระหว่างถือ (R)
  post_exit_r: number | null; // หลังชน TP ราคาวิ่งต่ออีกกี่ R
  review: string | null; // บทวิเคราะห์รายไม้อัตโนมัติ
  ticket: number | null; // MT5 position ticket (null = dry-run)
  margin_used: number | null; // margin ที่ใช้เปิดไม้นี้ (currency บัญชี)
  margin_pct: number | null; // margin_used / initial_balance * 100
  current_price: number | null; // ราคาปัจจุบัน (ไม้ที่ยังเปิดอยู่)
  floating_pnl: number | null; // กำไร/ขาดทุนลอย (ไม้ที่ยังเปิดอยู่)
};

export type ReviewSummary = {
  total: number;
  wins?: number;
  losses?: number;
  avg_win_r?: number;
  avg_loss_r?: number;
  losses_were_winning_1r?: number;
  losses_wrong_entry?: number;
  wins_clean_sl?: number;
  wins_near_death?: number;
  tp_hits_with_lookahead?: number;
  tp_ran_on_1r?: number;
  recommendations: string[];
};

export type CommitteeOpinion = {
  member: string;
  role: string;
  approve: boolean;
  comment: string;
};

export type RegimeStats = {
  regime: string;
  total_trades: number;
  win_rate_pct: number;
  profit_factor: number | null;
  expectancy: number;
  total_pnl: number;
};

export type RunDetail = {
  run: RunSummary;
  trades: Trade[];
  rejected_count: number;
  rejected_reasons: { reason: string; count: number }[];
  regime_breakdown: RegimeStats[];
  review_summary: ReviewSummary;
  config: Record<string, unknown> | null;
};

export type StrategyInfo = {
  name: string;
  description: string;
  params: Record<string, number | string>;
  committee: { name: string; role: string }[];
};

export async function fetchRuns(): Promise<RunSummary[]> {
  const res = await fetch(`${BACKEND_URL}/runs`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRuns failed: ${res.status}`);
  return res.json();
}

export async function fetchStrategies(): Promise<StrategyInfo[]> {
  const res = await fetch(`${BACKEND_URL}/strategies`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchStrategies failed: ${res.status}`);
  return res.json();
}

export type LiveTeamStatus = {
  run_id: string;
  strategy: string;
  timeframe: string | null;
  symbol: string; // สินทรัพย์ที่ทีมนี้เทรด (multi-asset — run เก่า backend fallback เป็น SYMBOL หลักให้แล้ว)
  started_at: string;
  finished_at: string | null;
  is_running: boolean;
  initial_balance: number | null;
  current_balance: number; // initial + realized pnl + floating pnl ไม้ที่เปิดอยู่ (คำนวณสด)
  open_position: Trade | null;
  total_trades: number; // จำนวนไม้ที่ปิดแล้วทั้งหมดของ run นี้ (คำนวณสด ไม่พึ่ง finish_run)
  win_rate_pct: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  closed_trades_today: number;
  total_pnl: number;
  floating_pnl: number;
  equity_curve: { time: string; balance: number }[];
  recent_trades: Trade[];
};

export type PnlCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type LivePortfolio = {
  initial_balance: number;
  current_balance: number;
  total_pnl: number;
  floating_pnl: number;
  equity_curve: { time: string; balance: number }[];
  pnl_candles: PnlCandle[];
  by_team: { strategy: string; timeframe: string | null; symbol: string; pnl: number }[];
  by_symbol: { symbol: string; pnl: number; teams: number; open_positions: number }[];
};

export type LiveStatus = {
  active: boolean;
  teams: LiveTeamStatus[];
  portfolio: LivePortfolio;
};

export type LiveCandle = { time: number; open: number; high: number; low: number; close: number };
export type LiveMarker = {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown" | "circle";
  color: string;
  text: string;
};
export type LiveOpenLine = {
  team: string;
  direction: string;
  entry: number | null;
  sl: number | null;
  tp: number | null;
};
export type LiveCandles = {
  symbol: string;
  timeframe: string;
  source: string; // "mt5" = ราคาสด | "parquet" = cache ล่าสุด (อาจไม่ใช่ราคาปัจจุบัน)
  candles: LiveCandle[];
  markers: LiveMarker[];
  open_lines: LiveOpenLine[];
};

export async function fetchLiveCandles(symbol: string, timeframe: string): Promise<LiveCandles> {
  const res = await fetch(
    `${BACKEND_URL}/live/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchLiveCandles failed: ${res.status}`);
  return res.json();
}

export async function fetchLiveStatus(): Promise<LiveStatus> {
  const res = await fetch(`${BACKEND_URL}/live/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchLiveStatus failed: ${res.status}`);
  return res.json();
}

export type RegimeCell = {
  timeframe: string;
  regime: string;
  strategy: string;
  run_id: string;
  total_trades: number;
  win_rate_pct: number;
  expectancy: number;
  total_pnl: number;
  qualified: boolean;
};

export type RegimeChampion = {
  timeframe: string;
  regime: string;
  champion: string | null;
  total_pnl?: number;
  expectancy?: number;
  win_rate_pct?: number;
  total_trades?: number;
  profitable?: boolean;
  runner_up?: string | null;
  note: string;
};

export type RegimeChampionsData = {
  matrix: RegimeCell[];
  champions: RegimeChampion[];
};

export async function fetchRegimeChampions(): Promise<RegimeChampionsData> {
  const res = await fetch(`${BACKEND_URL}/regime-champions`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchRegimeChampions failed: ${res.status}`);
  return res.json();
}

export type PortfolioRow = {
  multiplier: number;
  final_balance: number;
  max_drawdown_pct: number;
  avg_monthly_return_pct: number;
  worst_month_pct: number;
  best_month_pct: number;
  trades_taken: number;
  ruined: boolean;
};

export type PortfolioData = {
  selections: { strategy: string; timeframe: string; risk_pct: number }[];
  initial_balance: number;
  multiplier_comparison: PortfolioRow[];
  monthly_returns_1x: { month: string; return_pct: number; equity: number }[];
  error?: string;
};

export async function fetchPortfolio(): Promise<PortfolioData> {
  const res = await fetch(`${BACKEND_URL}/portfolio`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchPortfolio failed: ${res.status}`);
  return res.json();
}

export type CouncilSection = { focus: string; findings: string[] };
export type CouncilData = Record<string, CouncilSection>;

export async function fetchCouncil(): Promise<CouncilData> {
  const res = await fetch(`${BACKEND_URL}/council`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchCouncil failed: ${res.status}`);
  return res.json();
}

export async function fetchRunDetail(runId: string): Promise<RunDetail | null> {
  const res = await fetch(`${BACKEND_URL}/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchRunDetail failed: ${res.status}`);
  return res.json();
}
