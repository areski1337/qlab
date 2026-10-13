// ===================== Moteur d'exécution QLab (miroir de qlab.backtest.engine) =====================
// Sémantique : conditions évaluées à la clôture de la barre i, ordre au marché à l'ouverture de i+1 ;
// stop/objectif côté serveur ; break-even, trailing, sortie sur signal opposé et time stop décidés
// à la clôture et appliqués à l'ouverture suivante. Une position à la fois.
#include <Trade/Trade.mqh>

input bool   InpTrace = true;     // trace de diagnostic (fichier commun QLab/<run>.csv)
input string InpRunId = "";       // identifiant de run (parité)
input double InpRiskScale = 1.0;  // montée progressive du risque (0..1) : ne peut que RÉDUIRE le risque compilé

CTrade   g_trade;
datetime g_last_bar = 0;
int      g_trace = INVALID_HANDLE;
// état de risque (contrôleur indépendant, mêmes règles que qlab.risk.controller)
double g_peak = 0.0, g_day_start = 0.0;
long   g_day = -1;
int    g_day_orders = 0;
bool   g_halted = false;
long   g_cnt_day = -1;
int    g_cnt = 0;
// position
datetime g_entry_bar = 0;
double   g_entry = 0.0, g_dist = 0.0, g_sl = 0.0;
int      g_dir = 0;
bool     g_be_done = false;
datetime g_last_exit_bar = 0;
bool     g_had_pos = false;
bool     g_first = true;
// filtre d'annonces : fichier commun QLab\news_<symbole>.csv (COV;début;fin / BLK;début;fin, UTC)
long     g_cov_a[], g_cov_b[], g_blk_a[], g_blk_b[];
int      g_ncov = 0, g_nblk = 0;
bool     g_news_ok = false;
datetime g_news_loaded = 0;

void QL_LoadNews()
{
   g_ncov = 0; g_nblk = 0; g_news_ok = false;
   int h = FileOpen("QLab\\news_" + _Symbol + ".csv", FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE) return;
   while(!FileIsEnding(h))
   {
      string parts[];
      if(StringSplit(FileReadString(h), ';', parts) < 3) continue;
      if(parts[0] == "QLAB_NEWS") { g_news_ok = true; continue; }
      long a = StringToInteger(parts[1]), b = StringToInteger(parts[2]);
      if(parts[0] == "COV") { ArrayResize(g_cov_a, g_ncov + 1); ArrayResize(g_cov_b, g_ncov + 1); g_cov_a[g_ncov] = a; g_cov_b[g_ncov] = b; g_ncov++; }
      if(parts[0] == "BLK") { ArrayResize(g_blk_a, g_nblk + 1); ArrayResize(g_blk_b, g_nblk + 1); g_blk_a[g_nblk] = a; g_blk_b[g_nblk] = b; g_nblk++; }
   }
   FileClose(h);
}

bool QL_InIntervals(const long &a[], const long &b[], const int n, const long t)
{
   for(int k = 0; k < n; k++) if(t >= a[k] && t < b[k]) return true;
   return false;
}

void QL_Trace(const string line)
{
   if(g_trace != INVALID_HANDLE) FileWriteString(g_trace, line + "\r\n");
}

int OnInit()
{
   QL_NAN = MathArccos(2.0);
   QL_K = QL_GEN_K;
   QL_TZ_MODE = QL_GEN_TZ_MODE;
   QL_TZ_FIXED = QL_GEN_TZ_FIXED;
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL)
   {
      Print("QLab : refus d'exécution sur un compte RÉEL (EA de recherche/démo uniquement).");
      return(INIT_FAILED);
   }
   if(_Symbol != QL_GEN_SYMBOL || _Period != QL_GEN_TF)
   {
      Print("QLab : symbole/timeframe attendus ", QL_GEN_SYMBOL, " / ", EnumToString(QL_GEN_TF));
      return(INIT_PARAMETERS_INCORRECT);
   }
   g_trade.SetExpertMagicNumber(QL_GEN_MAGIC);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetDeviationInPoints(QL_GEN_DEVIATION);
   g_peak = AccountInfoDouble(ACCOUNT_BALANCE);
   if(InpTrace)
   {
      string name = "QLab\\" + (InpRunId == "" ? "trace" : InpRunId) + ".csv";
      g_trace = FileOpen(name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      QL_Trace("HDR;" + QL_GEN_GENOME_HASH + ";" + QL_GEN_REVISION + ";" + IntegerToString(QL_GEN_W));
   }
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   if(g_trace == INVALID_HANDLE) return;
   QL_Trace(StringFormat("LASTBAR;%I64d", QL_ServerToUTC((long)g_last_bar)));
   if(HistorySelect(0, TimeCurrent() + 86400))
   {
      for(int k = 0; k < HistoryDealsTotal(); k++)
      {
         ulong d = HistoryDealGetTicket(k);
         if(HistoryDealGetInteger(d, DEAL_MAGIC) != QL_GEN_MAGIC) continue;
         QL_Trace(StringFormat("DEAL;%I64u;%I64d;%d;%d;%.8f;%.4f;%.4f;%.4f;%.4f;%d;%I64d",
            d, (long)HistoryDealGetInteger(d, DEAL_TIME), (int)HistoryDealGetInteger(d, DEAL_TYPE),
            (int)HistoryDealGetInteger(d, DEAL_ENTRY), HistoryDealGetDouble(d, DEAL_PRICE),
            HistoryDealGetDouble(d, DEAL_VOLUME), HistoryDealGetDouble(d, DEAL_PROFIT),
            HistoryDealGetDouble(d, DEAL_COMMISSION), HistoryDealGetDouble(d, DEAL_SWAP),
            (int)HistoryDealGetInteger(d, DEAL_REASON), (long)HistoryDealGetInteger(d, DEAL_POSITION_ID)));
      }
   }
   FileClose(g_trace);
   g_trace = INVALID_HANDLE;
}

bool QL_HasPosition()
{
   for(int k = PositionsTotal() - 1; k >= 0; k--)
   {
      ulong t = PositionGetTicket(k);
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == QL_GEN_MAGIC) return true;
   }
   return false;
}

bool QL_ClosePosition(const string why)
{
   for(int k = PositionsTotal() - 1; k >= 0; k--)
   {
      ulong t = PositionGetTicket(k);
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == QL_GEN_MAGIC)
      {
         QL_Trace("CLOSE;" + why);
         return g_trade.PositionClose(t);
      }
   }
   return false;
}

// Barre (heure d'ouverture) contenant la dernière sortie de cette stratégie.
datetime QL_LastExitBar()
{
   datetime best = 0;
   if(!HistorySelect(TimeCurrent() - 86400 * 30, TimeCurrent() + 60)) return 0;
   for(int k = HistoryDealsTotal() - 1; k >= 0; k--)
   {
      ulong d = HistoryDealGetTicket(k);
      if(HistoryDealGetInteger(d, DEAL_MAGIC) != QL_GEN_MAGIC) continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      if(t > best) best = t;
   }
   if(best == 0) return 0;
   int sh = iBarShift(_Symbol, QL_GEN_TF, best, false);
   return iTime(_Symbol, QL_GEN_TF, sh);
}

// Refus motivé ou "" (ordre identique à RiskController.check_entry).
string QL_RiskCheck(const long day, const double lots, const double spread_pts)
{
   double eq = AccountInfoDouble(ACCOUNT_BALANCE);
   if(day != g_day) { g_day = day; g_day_start = eq; g_day_orders = 0; }
   if(g_halted) return "max_drawdown_halt";
   if(!(eq > 0)) return "equity_invalid";
   if((g_peak - eq) / g_peak * 100.0 >= QL_LIM_MAX_DD_PCT) { g_halted = true; return "max_drawdown_halt"; }
   if((g_day_start - eq) / g_day_start * 100.0 >= QL_LIM_MAX_DAILY_LOSS_PCT) return "daily_loss_limit";
   if(QL_LIM_DAILY_PROFIT_TARGET_PCT > 0 && (eq - g_day_start) / g_day_start * 100.0 >= QL_LIM_DAILY_PROFIT_TARGET_PCT) return "daily_profit_target";
   if(QL_HasPosition()) return "max_open_positions";
   if(g_day_orders >= QL_LIM_MAX_ORDERS_PER_DAY) return "max_orders_per_day";
   if(lots > QL_LIM_MAX_LOTS) return "max_lots";
   if(QL_LIM_MAX_SPREAD_POINTS > 0 && spread_pts > QL_LIM_MAX_SPREAD_POINTS) return "spread_too_wide";
   return "";
}

void OnTick()
{
   datetime bt = iTime(_Symbol, QL_GEN_TF, 0);
   if(bt == 0 || bt == g_last_bar) return;
   g_last_bar = bt;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal > g_peak) g_peak = bal;

   bool has = QL_HasPosition();
   if(g_had_pos && !has) g_last_exit_bar = QL_LastExitBar();   // sortie serveur (stop/objectif)
   g_had_pos = has;

   if(!QL_LoadAll()) { QL_Trace("NOHIST;" + IntegerToString((long)bt)); return; }
   QL_ComputeAll();
   int n = g_b0.n;
   if(g_first) { g_first = false; QL_Trace(StringFormat("FIRST;%I64d", g_b0.t[n - 1] + g_b0.tfsec)); }
   bool sig_long = QL_LongSignal();
   bool sig_short = QL_ShortSignal();
   long close_utc = g_b0.t[n - 1] + g_b0.tfsec;
   if(sig_long || sig_short) QL_Trace(StringFormat("SIG;%I64d;%d;%d", close_utc, sig_long, sig_short));

   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   // ---- gestion de la position ouverte (décisions prises à la clôture de la barre n-1) ----
   if(has)
   {
      double cl = g_b0.c[n - 1] + (g_dir == -1 ? g_b0.sp[n - 1] * pt : 0.0);
      double r_now = (cl - g_entry) * g_dir / g_dist;
      bool weekend = QL_LIM_WEEKEND_MIN > 0 && QL_MinToWeeklyClose(QL_ServerToUTC((long)bt)) <= QL_LIM_WEEKEND_MIN;
      bool opp = weekend || (QL_GEN_EXIT_ON_OPPOSITE && ((g_dir == 1 && sig_short) || (g_dir == -1 && sig_long)));
      int held = iBarShift(_Symbol, QL_GEN_TF, g_entry_bar, false);   // barres depuis l'entrée e jusqu'à la barre courante
      if(opp) { if(QL_ClosePosition(weekend ? "weekend_close" : "opposite_signal")) { g_last_exit_bar = bt; has = false; g_had_pos = false; } }
      else if(QL_GEN_TIME_STOP > 0 && held >= QL_GEN_TIME_STOP) { if(QL_ClosePosition("time_stop")) { g_last_exit_bar = bt; has = false; g_had_pos = false; } }
      else
      {
         double new_sl = g_sl;
         if(QL_GEN_BE_AT_R > 0 && !g_be_done && r_now >= QL_GEN_BE_AT_R)
         {
            if((g_entry - new_sl) * g_dir > 0) new_sl = g_entry;
            g_be_done = true;
         }
         if(QL_GEN_TRAIL_MULT > 0 && r_now >= QL_GEN_TRAIL_ACTIVATE_R)
         {
            double ta = QL_TrailATR();
            if(QL_OK(ta))
            {
               double cand = cl - g_dir * QL_GEN_TRAIL_MULT * ta;
               if((cand - new_sl) * g_dir > 0) new_sl = cand;
            }
         }
         if(new_sl != g_sl)
         {
            for(int k = PositionsTotal() - 1; k >= 0; k--)
            {
               ulong t = PositionGetTicket(k);
               if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == QL_GEN_MAGIC)
                  if(g_trade.PositionModify(t, NormalizeDouble(new_sl, _Digits), PositionGetDouble(POSITION_TP)))
                  { g_sl = new_sl; QL_Trace(StringFormat("MODSL;%I64d;%.8f", close_utc, new_sl)); }
            }
         }
      }
   }
   if(has) return;

   // ---- entrée ----
   if(!sig_long && !sig_short) return;
   if(sig_long && sig_short) { QL_Trace("SKIP;conflict_long_short"); return; }
   int d = sig_long ? 1 : -1;
   if(g_last_exit_bar > 0)
   {
      int since = iBarShift(_Symbol, QL_GEN_TF, g_last_exit_bar, false) - 1;   // = i - last_exit
      if(since < QL_GEN_COOLDOWN) { QL_Trace("SKIP;cooldown"); return; }
   }
   long day = QL_TradingDay(QL_ServerToUTC((long)bt));
   if(day != g_cnt_day) { g_cnt_day = day; g_cnt = 0; }
   if(g_cnt >= QL_GEN_MAX_TRADES_PER_DAY) { QL_Trace("SKIP;max_trades_per_day"); return; }
   long t_entry = QL_ServerToUTC((long)bt);
   if(QL_LIM_WEEKEND_MIN > 0 && QL_MinToWeeklyClose(t_entry) <= QL_LIM_WEEKEND_MIN) { QL_Trace("SKIP;risk:weekend_window"); return; }
   if(QL_LIM_NEWS_ENABLED)
   {
      if(TimeCurrent() - g_news_loaded > 3600 || g_news_loaded == 0) { QL_LoadNews(); g_news_loaded = TimeCurrent(); }
      if(!g_news_ok || !QL_InIntervals(g_cov_a, g_cov_b, g_ncov, t_entry)) { QL_Trace("SKIP;risk:news_data_unavailable"); return; }
      if(QL_InIntervals(g_blk_a, g_blk_b, g_nblk, t_entry)) { QL_Trace("SKIP;risk:news_window"); return; }
   }
   // Arrêt d'urgence global / suspension de cette stratégie : plus aucune entrée (positions existantes conservées).
   if(FileIsExist("QLab\\EMERGENCY_STOP", FILE_COMMON)) { QL_Trace("SKIP;emergency_stop"); return; }
   if(FileIsExist("QLab\\suspend_" + IntegerToString(QL_GEN_MAGIC) + ".flag", FILE_COMMON)) { QL_Trace("SKIP;suspended"); return; }

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk)) return;
   double entry = d == 1 ? tk.ask : tk.bid;
   double dist = QL_StopDistance(d, entry);
   if(!QL_OK(dist) || dist <= 0) { QL_Trace("SKIP;stop_not_computable"); return; }
   double sl = entry - d * dist;
   double tp = QL_Target(d, entry, dist);
   if(QL_GEN_TARGET_KIND == 2 && !QL_OK(tp)) { QL_Trace("SKIP;target_not_computable"); return; }

   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double vpu = tv / ts;
   double risk_pct = MathMin(QL_GEN_RISK_PCT, QL_LIM_MAX_RISK_PCT) * MathMax(0.0, MathMin(1.0, InpRiskScale));
   double raw_lots = AccountInfoDouble(ACCOUNT_BALANCE) * risk_pct / 100.0 / (dist * vpu);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), QL_LIM_MAX_LOTS);
   double lots = MathFloor(raw_lots / step + 1e-9) * step;
   lots = MathMin(NormalizeDouble(lots, 8), vmax);
   if(lots < vmin) { QL_Trace("SKIP;lots_below_min"); return; }
   string why = QL_RiskCheck(day, lots, (double)(tk.ask - tk.bid) / pt);
   if(why != "") { QL_Trace("SKIP;risk:" + why); return; }

   // Verrou : un seul robot QLab ouvre une position sur ce symbole à une bougie donnée.
   string lock = "QLAB_LOCK_" + _Symbol;
   double prev_lock = GlobalVariableCheck(lock) ? GlobalVariableGet(lock) : 0.0;
   if(prev_lock == (double)bt) { QL_Trace("SKIP;concurrent_lock"); return; }
   if(GlobalVariableCheck(lock) ? !GlobalVariableSetOnCondition(lock, (double)bt, prev_lock) : GlobalVariableSet(lock, (double)bt) == 0)
   { QL_Trace("SKIP;concurrent_lock"); return; }
   bool ok = d == 1 ? g_trade.Buy(lots, _Symbol, 0.0, NormalizeDouble(sl, _Digits), QL_OK(tp) ? NormalizeDouble(tp, _Digits) : 0.0, "qlab")
                    : g_trade.Sell(lots, _Symbol, 0.0, NormalizeDouble(sl, _Digits), QL_OK(tp) ? NormalizeDouble(tp, _Digits) : 0.0, "qlab");
   if(!ok) { QL_Trace("ORDERFAIL;" + IntegerToString((int)g_trade.ResultRetcode())); return; }
   g_day_orders++;
   g_cnt++;
   g_entry_bar = bt; g_entry = g_trade.ResultPrice() > 0 ? g_trade.ResultPrice() : entry;
   g_dist = dist; g_sl = sl; g_dir = d; g_be_done = false; g_had_pos = true;
   QL_Trace(StringFormat("ENTRY;%I64d;%d;%.8f;%.8f;%.8f;%.2f", close_utc, d, g_entry, sl, QL_OK(tp) ? tp : 0.0, lots));
}
