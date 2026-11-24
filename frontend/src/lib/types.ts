export type Label = "exceptional" | "good" | "fair" | "overpriced" | "risky";
export type MatchStatus = "new" | "seen" | "favorite" | "interested" | "planned" | "purchased" | "rejected";
export type SearchStatus = "active" | "paused" | "archived" | "completed";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  timezone: string;
  currency: string;
  locale: string;
  country: string;
  postal_code: string | null;
  city: string | null;
  has_coordinates: boolean;
  radius_km: number;
  delivery: "ship" | "pickup" | "both";
  monthly_budget: number | null;
  notification_prefs: NotificationPrefs;
  search_schedule: { times: string[] };
  ai_limits: AILimits;
  ai_paused_reason: string | null;
  ai_preferred: { credential_id?: string | null; models?: Record<string, string> };
  share_location_with_ai: boolean;
  learned_prefs: { weights?: Record<string, number>; signals?: number };
  ui_prefs: Partial<import("./prefs").UIPrefs>;
}

export interface NotificationPrefs {
  instant_exceptional: boolean;
  instant_good: boolean;
  price_drops: boolean;
  search_failures: boolean;
  usage_warnings: boolean;
  digest_enabled: boolean;
  digest_times: string[];
  digest_days: number[];
  digest_min_score: number;
  digest_max_results: number;
  digest_include_price_drops: boolean;
  digest_include_alternatives: boolean;
  digest_include_accessories: boolean;
}

export interface AILimits {
  monthly_limit_usd: number;
  daily_limit_usd: number;
  warn_pct: number;
  pause_pct: number;
  max_deep_per_day: number;
  max_vision_per_day: number;
  max_analyses_per_run: number;
  auto_pause: boolean;
}

export interface ProductTarget { name: string; reason?: string | null }
export interface AccessoryTarget { name: string; essential: boolean; max_budget?: number | null; compatibility?: string | null }

export interface SearchSpec {
  desired_products: ProductTarget[];
  alternatives: ProductTarget[];
  allow_alternatives: boolean;
  excluded: string[];
  preferred_brands: string[];
  accessories: AccessoryTarget[];
  must_have: string[];
  nice_to_have: string[];
  queries: string[];
  notes?: string | null;
}

export interface Search {
  id: string;
  title: string;
  prompt: string;
  category: string | null;
  spec: SearchSpec;
  max_budget: number | null;
  currency: string;
  condition: "any" | "used" | "new";
  prefer_condition: "used" | "new" | null;
  postal_code: string | null;
  radius_km: number | null;
  delivery: "ship" | "pickup" | "both" | null;
  sources: Record<string, { enabled: boolean; priority: number }>;
  schedule: { mode: "default" | "custom" | "interval"; times?: string[]; hours?: number };
  notify: { instant_min_score: number; digest: boolean };
  priority: number;
  status: SearchStatus;
  min_score: number;
  parent_search_id: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  stats: { matches?: number; best_score?: number | null; new?: number; good_deals?: number; image?: string | null };
}

export interface SearchDraft {
  title: string;
  category: string | null;
  spec: SearchSpec;
  max_budget: number | null;
  currency: string;
  condition: "any" | "used" | "new";
  prefer_condition: "used" | "new" | null;
  delivery: "ship" | "pickup" | "both" | null;
  radius_km: number | null;
  priority: number;
  summary: string;
}

export interface Interpretation {
  needs_clarification: boolean;
  questions: string[];
  draft: SearchDraft;
  assumptions: string[];
}

export interface ListingLite {
  id: string;
  source: string;
  url: string;
  title: string;
  price: number | null;
  currency: string;
  images: string[];
  condition: string | null;
  location_text: string | null;
  price_type: string;
  ends_at: string | null;
}

export interface Listing extends ListingLite {
  description: string | null;
  shipping_cost: number | null;
  shipping_known: boolean;
  shipping_possible: boolean | null;
  pickup_possible: boolean | null;
  condition_text: string | null;
  seller: { name?: string; feedback_pct?: string; feedback_count?: number };
  is_new_retail: boolean;
  first_seen_at: string;
  last_seen_at: string;
  state: string;
}

export interface RedFlag { type: string; detail: string }

export interface AnalysisResult {
  relevance: string;
  identified_product: string | null;
  requirement_matches: string[];
  requirement_misses: string[];
  condition: string;
  included_items: string[];
  facts: string[];
  assumptions: string[];
  red_flags: RedFlag[];
  market_value_low: number | null;
  market_value_high: number | null;
  market_value_basis: string;
  market_confidence: "low" | "medium" | "high";
  alternative_reason: string | null;
  possibly_undervalued: boolean;
  summary: string;
  worth_deep_look: boolean;
  injection_suspected: boolean;
  vision?: {
    observations: string[];
    possible_issues: { issue: string; confidence: string; image_index: number }[];
    visible_items: string[];
    matches_title: boolean | null;
    looks_like_stock_photo: boolean;
    assessable: boolean;
    summary: string;
  };
}

export interface MarketValue {
  mid?: number | null;
  ai_low?: number | null;
  ai_high?: number | null;
  ai_basis?: string;
  ai_confidence?: string;
  comparables_n?: number;
  comparables_median?: number | null;
  source?: string;
  confidence?: string;
  ratio?: number;
  kind?: string;
}

export interface Analysis {
  id: string;
  kind: string;
  provider: string;
  model: string;
  result: AnalysisResult;
  score: number | null;
  label: Label | null;
  breakdown: { label: string; points: number; kind: string }[];
  market_value: MarketValue;
  created_at: string;
}

export interface Deal {
  id: string;
  search_id: string;
  search_title: string | null;
  status: MatchStatus;
  relevance: string;
  deal_score: number | null;
  deal_label: Label | null;
  effective_price: number | null;
  effective_price_estimated: boolean;
  distance_km: number | null;
  within_radius: boolean | null;
  analysis_state: string;
  skip_reason: string | null;
  previous_price: number | null;
  price_dropped_at: string | null;
  first_seen_at: string;
  summary: string | null;
  identified_product: string | null;
  market_mid: number | null;
  red_flag_count: number;
  note: string | null;
  listing: ListingLite;
}

export interface DealDetail extends Omit<Deal, "listing"> {
  listing: Listing;
  analysis: Analysis | null;
  price_history: { price: number; shipping: number | null; at: string }[];
  similar: Deal[];
}

export interface WishItem {
  id: string;
  parent_id: string | null;
  title: string;
  kind: "main" | "accessory";
  category: string | null;
  essential: boolean;
  budget: number | null;
  compatibility: Record<string, string>;
  status: "planned" | "interested" | "purchased" | "rejected";
  search_id: string | null;
  notes: string | null;
  sort: number;
  created_at: string;
}

export interface Shop {
  id: string;
  name: string;
  host: string;
  mode: "woo" | "page";
  search_url: string;
  kind: "retail" | "secondhand";
  enabled: boolean;
  state: "ok" | "robots" | "blocked" | "no_data" | "error" | "untested";
  state_text: string;
  checked_at: string | null;
  paused_until: string | null;
  found_total: number;
}

export interface ShopPreview {
  title: string;
  price: number | null;
  currency: string;
  url: string;
  image: string | null;
}

export interface InboxInfo {
  configured: boolean;
  address: string | null;
  checked_at: string | null;
  last_alert_at: string | null;
  totals: Record<string, number>;
  unrouted: number;
  unreadable: number;
  ok: boolean | null;
  error?: string | null;
}

export interface SourceInfo {
  id: string;
  name: string;
  kind: string;
  homepage: string;
  state: "ready" | "needs_credentials" | "unsupported" | "planned" | "manual" | "alerts";
  reason: string;
  alternatives: string | null;
  available: boolean;
}

export interface Outage {
  from: string;
  to: string;
  minutes: number;
  clean: boolean;
  searches_caught_up: number;
  runs_restarted: string[];
  analyses_requeued: number;
}

export interface Dashboard {
  last_outage: Outage | null;
  active_searches: number;
  new_today: number;
  good_this_week: number;
  top: Deal[];
  price_drops: Deal[];
  recent_runs: { search: string; status: string; started_at: string; new_matches: number; fetched: number; error: string | null }[];
  next_run_at: string | null;
  ai_budget: BudgetStatus;
  setup: { ai_ready: boolean; telegram_linked: boolean; telegram_configured: boolean; location_set: boolean; sources_ready: string[] };
}

export interface BudgetStatus {
  day_usd: number;
  month_usd: number;
  daily_limit_usd: number | null;
  monthly_limit_usd: number | null;
  warn_pct: number;
  pause_pct: number;
  paused_reason: string | null;
}
