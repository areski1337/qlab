//+------------------------------------------------------------------+
//| EA généré par QLab — NE PAS MODIFIER À LA MAIN                     |
//+------------------------------------------------------------------+
// genome_revision : rev_001a13637fb11f783dfec39
// semantic_hash   : cd2941421ebf9a1d8774b9ddd82d64ac11f86c35d8a25fde4c87582b6c25ee75
// generator       : qlab.mql5_generator 1.0 (engine 0.1.0)
// risk_limits     : sha256 689e82d1fd56a555bdb9dabde4225705a146aae0e7d15e16a1620b2ab45e33ad (limites absolues figées, non modifiables par input)
// timezone serveur: NY+7
// Hypothèses d'exécution : signal à la clôture, ordre au marché à l'ouverture suivante ;
//   stop/objectif côté serveur ; une position à la fois ; refus sur compte réel.
// Règles :
//   marché : XAUUSD M5
//   entrée long : (fvg(expiry=60,min_atr=0.3).bull_retest ET structure(break_on=close,disp_atr=1.0,left=3,right=3).trend[H1] > 0 ET (session(name=london_kz).active OU session(name=ny_am_kz).active) ET range_position(lookback=100).value < 50)
//   entrée short : —
//   exécution : signal à la clôture de la barre, ordre au marché à l'ouverture suivante
//   stop : dernier swing (3/3) ± 0.2 × ATR(14)
//   objectif : 2.5 R
//   break-even : non
//   trailing : 2.5 × ATR(14) après 1.5 R
//   time stop : 144 barres
//   sortie sur signal opposé : non
//   risque demandé : 0.5 % (plafonné par le contrôleur de risque)
//   gestion : max 2 trades/jour, pause 6 barres
#property copyright "QLab (recherche) — aucune garantie de performance"
#property version   "1.0"

#define QL_GEN_SYMBOL "XAUUSD"
#define QL_GEN_TF PERIOD_M5
#define QL_GEN_K 3
#define QL_GEN_TZ_MODE 2
#define QL_GEN_TZ_FIXED 0
#define QL_GEN_MAGIC 1740645464
#define QL_GEN_DEVIATION 10
#define QL_GEN_GENOME_HASH "cd2941421ebf9a1d8774b9ddd82d64ac11f86c35d8a25fde4c87582b6c25ee75"
#define QL_GEN_REVISION "rev_001a13637fb11f783dfec39"
#define QL_GEN_W 3000
#define QL_GEN_EXIT_ON_OPPOSITE false
#define QL_GEN_TIME_STOP 144
#define QL_GEN_BE_AT_R 0.0
#define QL_GEN_TRAIL_MULT 2.5
#define QL_GEN_TRAIL_ACTIVATE_R 1.5
#define QL_GEN_COOLDOWN 6
#define QL_GEN_MAX_TRADES_PER_DAY 2
#define QL_GEN_TARGET_KIND 1
#define QL_GEN_RISK_PCT 0.5
#define QL_LIM_MAX_RISK_PCT 1.0
#define QL_LIM_MAX_DAILY_LOSS_PCT 4.0
#define QL_LIM_MAX_DD_PCT 25.0
#define QL_LIM_MAX_LOTS 50.0
#define QL_LIM_MAX_ORDERS_PER_DAY 50
#define QL_LIM_MAX_SPREAD_POINTS 0.0

// ===================== QLab core library (mql5_generator 1.0) =====================
// Miroir des définitions Python (qlab.features). Toute divergence de formule
// est un défaut de parité. NaN = valeur non calculable (jamais remplacée).
double QL_NAN = 0.0;
int    QL_K   = 3;      // nombre de dernières barres où les sorties « glissantes » sont calculées

bool QL_OK(const double x) { return MathIsValidNumber(x); }
bool QL_GT(const double a, const double b) { return QL_OK(a) && QL_OK(b) && a > b; }
bool QL_LT(const double a, const double b) { return QL_OK(a) && QL_OK(b) && a < b; }
bool QL_LE(const double a, const double b) { return QL_OK(a) && QL_OK(b) && a <= b; }
bool QL_GE(const double a, const double b) { return QL_OK(a) && QL_OK(b) && a >= b; }
bool QL_EV(const double a) { return QL_OK(a) && a > 0.5; }

struct QLBars
{
   int    n;
   int    tfsec;
   double o[], h[], l[], c[], tv[], sp[], rv[];
   long   t[];        // ouverture de barre en secondes UTC
};

void QL_Init(double &a[], const int n, const double v) { ArrayResize(a, n); ArrayInitialize(a, v); }

// ---------------------------------------------------------------- temps / fuseaux
int  QL_DOW(const long t) { return (int)(((t / 86400) + 4) % 7); }   // 0 = dimanche
long QL_Ymd(const int y, const int m, const int d)
{
   MqlDateTime s; s.year = y; s.mon = m; s.day = d; s.hour = 0; s.min = 0; s.sec = 0;
   return (long)StructToTime(s);
}
int  QL_Year(const long t) { MqlDateTime s; TimeToStruct((datetime)t, s); return s.year; }
long QL_NthSunday(const int y, const int m, const int nth)
{
   long t = QL_Ymd(y, m, 1);
   int first = (7 - QL_DOW(t)) % 7;
   return t + (long)(first + 7 * (nth - 1)) * 86400;
}
long QL_LastSunday(const int y, const int m)
{
   long t = (m == 12) ? QL_Ymd(y + 1, 1, 1) : QL_Ymd(y, m + 1, 1);
   t -= 86400;
   return t - (long)QL_DOW(t) * 86400;
}
bool QL_US_DST(const long u)   // u en UTC
{
   int y = QL_Year(u);
   return u >= QL_NthSunday(y, 3, 2) + 7 * 3600 && u < QL_NthSunday(y, 11, 1) + 6 * 3600;
}
bool QL_EU_DST(const long u)
{
   int y = QL_Year(u);
   return u >= QL_LastSunday(y, 3) + 3600 && u < QL_LastSunday(y, 10) + 3600;
}
long QL_NYOffset(const long u) { return QL_US_DST(u) ? -4 * 3600 : -5 * 3600; }

// Profil de fuseau serveur, figé à la génération : 0 = UTC, 1 = décalage fixe, 2 = "NY+7".
int  QL_TZ_MODE  = 2;
long QL_TZ_FIXED = 0;
long QL_ServerToUTC(const long s)
{
   if(QL_TZ_MODE == 0) return s;
   if(QL_TZ_MODE == 1) return s - QL_TZ_FIXED;
   if(QL_US_DST(s - 3 * 3600)) return s - 3 * 3600;
   return s - 2 * 3600;
}
long QL_TradingDay(const long u)  { long x = u + QL_NYOffset(u) + 7 * 3600; return (long)MathFloor((double)x / 86400.0); }
long QL_TradingWeek(const long u) { return (long)MathFloor((double)(QL_TradingDay(u) + 3) / 7.0); }

int QL_LocalMinutes(const long u, const int zone)   // 0 NY, 1 Londres, 2 Tokyo
{
   long off = 0;
   if(zone == 0) off = QL_NYOffset(u);
   else if(zone == 1) off = QL_EU_DST(u) ? 3600 : 0;
   else off = 9 * 3600;
   long loc = u + off;
   long sod = ((loc % 86400) + 86400) % 86400;
   return (int)(sod / 60);
}
bool QL_InSession(const long u, const int zone, const int start_min, const int end_min)
{
   int m = QL_LocalMinutes(u, zone);
   if(start_min < end_min) return m >= start_min && m < end_min;
   return m >= start_min || m < end_min;
}

// ---------------------------------------------------------------- données
bool QL_Load(const string sym, const ENUM_TIMEFRAMES tf, const int W, QLBars &b)
{
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(sym, tf, 1, W, r);     // position 1 : la barre en formation est exclue
   if(got < W) return false;                  // historique insuffisant : aucun signal (prudence)
   b.n = got;
   b.tfsec = PeriodSeconds(tf);
   ArrayResize(b.o, got); ArrayResize(b.h, got); ArrayResize(b.l, got); ArrayResize(b.c, got);
   ArrayResize(b.tv, got); ArrayResize(b.sp, got); ArrayResize(b.rv, got); ArrayResize(b.t, got);
   for(int i = 0; i < got; i++)
   {
      b.o[i] = r[i].open; b.h[i] = r[i].high; b.l[i] = r[i].low; b.c[i] = r[i].close;
      b.tv[i] = (double)r[i].tick_volume; b.sp[i] = (double)r[i].spread; b.rv[i] = (double)r[i].real_volume;
      b.t[i] = QL_ServerToUTC((long)r[i].time);
   }
   return true;
}

// Index de la dernière barre HTF close à l'instant t (UTC), -1 sinon.
int QL_AlignAt(QLBars &htf, const long t)
{
   int lo = 0, hi = htf.n - 1, ans = -1;
   while(lo <= hi)
   {
      int mid = (lo + hi) / 2;
      if(htf.t[mid] + htf.tfsec <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
   }
   return ans;
}

// ---------------------------------------------------------------- primitives
// Lissage exponentiel amorcé par la moyenne des n premières valeurs finies (= Python _ewm_seeded).
void QL_EWM(const double &x[], const int N, const int n, const double alpha, double &out[])
{
   QL_Init(out, N, QL_NAN);
   int s = -1;
   for(int i = 0; i < N; i++) if(QL_OK(x[i])) { s = i; break; }
   if(s < 0 || s + n > N) return;
   double seed = 0.0;
   for(int i = s; i < s + n; i++) seed += x[i];
   seed /= n;
   out[s + n - 1] = seed;
   for(int i = s + n; i < N; i++) out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1];
}
void QL_EMA(const double &x[], const int N, const int n, double &out[])    { QL_EWM(x, N, n, 2.0 / (n + 1), out); }
void QL_Wilder(const double &x[], const int N, const int n, double &out[]) { QL_EWM(x, N, n, 1.0 / n, out); }

// Moyenne glissante sur n valeurs (NaN si une valeur manque), calculée pour i >= from.
void QL_SMA(const double &x[], const int N, const int n, const int from, double &out[])
{
   QL_Init(out, N, QL_NAN);
   for(int i = MathMax(from, n - 1); i < N; i++)
   {
      double s = 0.0; bool ok = true;
      for(int k = i - n + 1; k <= i; k++) { if(!QL_OK(x[k])) { ok = false; break; } s += x[k]; }
      if(ok) out[i] = s / n;
   }
}
// Max/min glissant sur les n valeurs finissant en i (incluse), i >= from.
void QL_RollMax(const double &x[], const int N, const int n, const int from, double &out[])
{
   QL_Init(out, N, QL_NAN);
   for(int i = MathMax(from, n - 1); i < N; i++)
   {
      double m = x[i - n + 1];
      for(int k = i - n + 2; k <= i; k++) if(x[k] > m) m = x[k];
      out[i] = m;
   }
}
void QL_RollMin(const double &x[], const int N, const int n, const int from, double &out[])
{
   QL_Init(out, N, QL_NAN);
   for(int i = MathMax(from, n - 1); i < N; i++)
   {
      double m = x[i - n + 1];
      for(int k = i - n + 2; k <= i; k++) if(x[k] < m) m = x[k];
      out[i] = m;
   }
}
// Écart-type population glissant (NaN si une valeur manque).
void QL_RollStd(const double &x[], const int N, const int n, const int from, double &out[])
{
   QL_Init(out, N, QL_NAN);
   for(int i = MathMax(from, n - 1); i < N; i++)
   {
      double s = 0.0; bool ok = true;
      for(int k = i - n + 1; k <= i; k++) { if(!QL_OK(x[k])) { ok = false; break; } s += x[k]; }
      if(!ok) continue;
      double m = s / n, v = 0.0;
      for(int k = i - n + 1; k <= i; k++) v += (x[k] - m) * (x[k] - m);
      out[i] = MathSqrt(v / n);
   }
}
void QL_TR(QLBars &b, double &tr[])
{
   QL_Init(tr, b.n, QL_NAN);
   tr[0] = b.h[0] - b.l[0];
   for(int i = 1; i < b.n; i++)
      tr[i] = MathMax(b.h[i] - b.l[i], MathMax(MathAbs(b.h[i] - b.c[i - 1]), MathAbs(b.l[i] - b.c[i - 1])));
}
void QL_ATR(QLBars &b, const int n, double &out[]) { double tr[]; QL_TR(b, tr); QL_Wilder(tr, b.n, n, out); }

// ---------------------------------------------------------------- features classiques
void F_price(QLBars &b, double &open[], double &high[], double &low[], double &close[])
{
   ArrayCopy(open, b.o); ArrayCopy(high, b.h); ArrayCopy(low, b.l); ArrayCopy(close, b.c);
}
void F_sma(QLBars &b, const int period, double &value[]) { QL_SMA(b.c, b.n, period, b.n - QL_K, value); }
void F_ema(QLBars &b, const int period, double &value[]) { QL_EMA(b.c, b.n, period, value); }
void F_atr(QLBars &b, const int period, double &value[]) { QL_ATR(b, period, value); }
void F_rsi(QLBars &b, const int period, double &value[])
{
   int N = b.n;
   double g[], l[], ag[], al[];
   QL_Init(g, N, QL_NAN); QL_Init(l, N, QL_NAN);
   for(int i = 1; i < N; i++) { double d = b.c[i] - b.c[i - 1]; g[i] = d > 0 ? d : 0.0; l[i] = d < 0 ? -d : 0.0; }
   QL_Wilder(g, N, period, ag); QL_Wilder(l, N, period, al);
   QL_Init(value, N, QL_NAN);
   for(int i = 0; i < N; i++)
   {
      if(!QL_OK(ag[i])) continue;
      if(al[i] == 0.0) value[i] = (ag[i] == 0.0) ? 50.0 : 100.0;
      else value[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i]);
   }
}
void F_macd(QLBars &b, const int fast, const int slow, const int signal, double &macd[], double &sig[], double &hist[])
{
   int N = b.n;
   double ef[], es[];
   QL_EMA(b.c, N, fast, ef); QL_EMA(b.c, N, slow, es);
   QL_Init(macd, N, QL_NAN);
   for(int i = 0; i < N; i++) if(QL_OK(ef[i]) && QL_OK(es[i])) macd[i] = ef[i] - es[i];
   QL_EMA(macd, N, signal, sig);
   QL_Init(hist, N, QL_NAN);
   for(int i = 0; i < N; i++) if(QL_OK(macd[i]) && QL_OK(sig[i])) hist[i] = macd[i] - sig[i];
}
void F_stoch(QLBars &b, const int k, const int d, const int smooth, double &kk[], double &dd[])
{
   int N = b.n, from = b.n - QL_K - smooth - d - 2;
   double hh[], ll[], raw[];
   QL_RollMax(b.h, N, k, from, hh); QL_RollMin(b.l, N, k, from, ll);
   QL_Init(raw, N, QL_NAN);
   for(int i = 0; i < N; i++)
   {
      if(!QL_OK(hh[i]) || !QL_OK(ll[i])) continue;
      double rng = hh[i] - ll[i];
      raw[i] = rng > 0 ? (b.c[i] - ll[i]) / rng * 100.0 : 50.0;
   }
   if(smooth > 1) QL_SMA(raw, N, smooth, from + smooth, kk); else ArrayCopy(kk, raw);
   if(d > 1) QL_SMA(kk, N, d, from + smooth + d, dd); else ArrayCopy(dd, kk);
}
void F_bollinger(QLBars &b, const int period, const double dev, double &upper[], double &mid[], double &lower[])
{
   int N = b.n, from = b.n - QL_K;
   double sd[];
   QL_SMA(b.c, N, period, from, mid); QL_RollStd(b.c, N, period, from, sd);
   QL_Init(upper, N, QL_NAN); QL_Init(lower, N, QL_NAN);
   for(int i = 0; i < N; i++) if(QL_OK(mid[i]) && QL_OK(sd[i])) { upper[i] = mid[i] + dev * sd[i]; lower[i] = mid[i] - dev * sd[i]; }
}
void F_keltner(QLBars &b, const int period, const double mult, double &upper[], double &mid[], double &lower[])
{
   int N = b.n;
   double a[];
   QL_EMA(b.c, N, period, mid); QL_ATR(b, period, a);
   QL_Init(upper, N, QL_NAN); QL_Init(lower, N, QL_NAN);
   for(int i = 0; i < N; i++) if(QL_OK(mid[i]) && QL_OK(a[i])) { upper[i] = mid[i] + mult * a[i]; lower[i] = mid[i] - mult * a[i]; }
}
void F_adx(QLBars &b, const int period, double &adx[], double &pdi[], double &mdi[])
{
   int N = b.n;
   double pdm[], mdm[], tr[], tr1[], str[], spdm[], smdm[], dx[];
   QL_Init(pdm, N, QL_NAN); QL_Init(mdm, N, QL_NAN); QL_Init(tr1, N, QL_NAN);
   QL_TR(b, tr);
   for(int i = 1; i < N; i++)
   {
      double up = b.h[i] - b.h[i - 1], dn = b.l[i - 1] - b.l[i];
      pdm[i] = (up > dn && up > 0) ? up : 0.0;
      mdm[i] = (dn > up && dn > 0) ? dn : 0.0;
      tr1[i] = tr[i];
   }
   QL_Wilder(tr1, N, period, str); QL_Wilder(pdm, N, period, spdm); QL_Wilder(mdm, N, period, smdm);
   QL_Init(pdi, N, QL_NAN); QL_Init(mdi, N, QL_NAN); QL_Init(dx, N, QL_NAN);
   for(int i = 0; i < N; i++)
   {
      if(!QL_OK(str[i]) || !QL_OK(spdm[i]) || !QL_OK(smdm[i])) continue;
      pdi[i] = 100.0 * spdm[i] / str[i];
      mdi[i] = 100.0 * smdm[i] / str[i];
      dx[i] = (pdi[i] + mdi[i] > 0) ? 100.0 * MathAbs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) : 0.0;
   }
   QL_Wilder(dx, N, period, adx);
}
void F_donchian(QLBars &b, const int period, double &upper[], double &lower[], double &mid[])
{
   int N = b.n, from = b.n - QL_K - 1;
   double hh[], ll[];
   QL_RollMax(b.h, N, period, from, hh); QL_RollMin(b.l, N, period, from, ll);
   QL_Init(upper, N, QL_NAN); QL_Init(lower, N, QL_NAN); QL_Init(mid, N, QL_NAN);
   for(int i = 1; i < N; i++)
      if(QL_OK(hh[i - 1]) && QL_OK(ll[i - 1])) { upper[i] = hh[i - 1]; lower[i] = ll[i - 1]; mid[i] = (hh[i - 1] + ll[i - 1]) / 2.0; }
}
void F_realized_vol(QLBars &b, const int period, double &value[])
{
   int N = b.n;
   double r[], sd[];
   QL_Init(r, N, QL_NAN);
   for(int i = 1; i < N; i++) r[i] = MathLog(b.c[i]) - MathLog(b.c[i - 1]);
   QL_RollStd(r, N, period, b.n - QL_K, sd);
   QL_Init(value, N, QL_NAN);
   for(int i = 0; i < N; i++) if(QL_OK(sd[i])) value[i] = sd[i] * 100.0;
}
void F_momentum(QLBars &b, const int period, double &roc[])
{
   QL_Init(roc, b.n, QL_NAN);
   for(int i = period; i < b.n; i++) roc[i] = (b.c[i] / b.c[i - period] - 1.0) * 100.0;
}
void F_compression(QLBars &b, const int fast, const int slow, double &value[])
{
   double af[], as[];
   QL_ATR(b, fast, af); QL_ATR(b, slow, as);
   QL_Init(value, b.n, QL_NAN);
   for(int i = 0; i < b.n; i++) if(QL_OK(af[i]) && QL_OK(as[i]) && as[i] != 0) value[i] = af[i] / as[i];
}
void F_rel_volume(QLBars &b, const int period, double &value[])
{
   double m[];
   QL_SMA(b.tv, b.n, period, b.n - QL_K, m);
   QL_Init(value, b.n, QL_NAN);
   for(int i = 0; i < b.n; i++) if(QL_OK(m[i]) && m[i] != 0) value[i] = b.tv[i] / m[i];
}
void F_spread(QLBars &b, double &points[])
{
   QL_Init(points, b.n, QL_NAN);
   for(int i = 0; i < b.n; i++) if(b.sp[i] > 0) points[i] = b.sp[i];
}
void F_session(QLBars &b, const int zone, const int smin, const int emin, double &active[])
{
   QL_Init(active, b.n, 0.0);
   for(int i = 0; i < b.n; i++) active[i] = QL_InSession(b.t[i] + b.tfsec, zone, smin, emin) ? 1.0 : 0.0;
}
void F_vwap(QLBars &b, const int anchor_week, const int use_real, const double dev, double &vwap[], double &upper[], double &lower[])
{
   int N = b.n;
   QL_Init(vwap, N, QL_NAN); QL_Init(upper, N, QL_NAN); QL_Init(lower, N, QL_NAN);
   bool any = false;
   for(int i = 0; i < N; i++) if((use_real ? b.rv[i] : b.tv[i]) > 0) { any = true; break; }
   if(use_real && !any) return;
   double spv = 0, sv = 0, sp2v = 0; long g = -999999;
   for(int i = 0; i < N; i++)
   {
      long gi = anchor_week ? QL_TradingWeek(b.t[i]) : QL_TradingDay(b.t[i]);
      if(gi != g) { g = gi; spv = 0; sv = 0; sp2v = 0; }
      double v = use_real ? b.rv[i] : b.tv[i];
      double tp = (b.h[i] + b.l[i] + b.c[i]) / 3.0;
      spv += tp * v; sv += v; sp2v += tp * tp * v;
      if(sv <= 0) continue;
      double vw = spv / sv;
      double var = MathMax(sp2v / sv - vw * vw, 0.0);
      vwap[i] = vw; upper[i] = vw + dev * MathSqrt(var); lower[i] = vw - dev * MathSqrt(var);
   }
}

// ---------------------------------------------------------------- ICT / SMC
// Pivots : sorties indexées à la confirmation (k + right).
void QL_Pivots(QLBars &b, const int left, const int right, double &lh[], double &ll[], double &ch[], double &cl[])
{
   int N = b.n;
   QL_Init(lh, N, QL_NAN); QL_Init(ll, N, QL_NAN); QL_Init(ch, N, 0.0); QL_Init(cl, N, 0.0);
   for(int k = left; k + right < N; k++)
   {
      bool ph = true, pl = true;
      for(int j = k - left; j < k; j++) { if(!(b.h[k] > b.h[j])) ph = false; if(!(b.l[k] < b.l[j])) pl = false; }
      for(int j = k + 1; j <= k + right; j++) { if(!(b.h[k] >= b.h[j])) ph = false; if(!(b.l[k] <= b.l[j])) pl = false; }
      if(ph) { ch[k + right] = 1.0; lh[k + right] = b.h[k]; }
      if(pl) { cl[k + right] = 1.0; ll[k + right] = b.l[k]; }
   }
   for(int i = 1; i < N; i++) { if(!QL_OK(lh[i])) lh[i] = lh[i - 1]; if(!QL_OK(ll[i])) ll[i] = ll[i - 1]; }
}
void F_swings(QLBars &b, const int left, const int right, double &last_high[], double &last_low[], double &new_high[], double &new_low[])
{
   QL_Pivots(b, left, right, last_high, last_low, new_high, new_low);
}
void QL_Structure(QLBars &b, const int left, const int right, const int on_close, const double disp_atr,
                  double &bu[], double &bd[], double &cu[], double &cd[], double &mu[], double &md[], double &trend[])
{
   int N = b.n;
   double lh[], ll[], ch[], cl[], atr[];
   QL_Pivots(b, left, right, lh, ll, ch, cl);
   QL_ATR(b, 14, atr);
   QL_Init(bu, N, 0); QL_Init(bd, N, 0); QL_Init(cu, N, 0); QL_Init(cd, N, 0); QL_Init(mu, N, 0); QL_Init(md, N, 0); QL_Init(trend, N, 0);
   int t = 0;
   double used_h = QL_NAN, used_l = QL_NAN;
   for(int i = 1; i < N; i++)
   {
      double h = lh[i - 1], l = ll[i - 1];
      double ux = on_close ? b.c[i] : b.h[i], dx = on_close ? b.c[i] : b.l[i];
      double body = MathAbs(b.c[i] - b.o[i]);
      bool h_new = QL_OK(h) && (!QL_OK(used_h) || h != used_h);
      bool l_new = QL_OK(l) && (!QL_OK(used_l) || l != used_l);
      if(h_new && ux > h)
      {
         used_h = h; bu[i] = 1;
         if(t == -1) { cu[i] = 1; mu[i] = (QL_OK(atr[i]) && body >= disp_atr * atr[i]) ? 1 : 0; }
         t = 1;
      }
      else if(l_new && dx < l)
      {
         used_l = l; bd[i] = 1;
         if(t == 1) { cd[i] = 1; md[i] = (QL_OK(atr[i]) && body >= disp_atr * atr[i]) ? 1 : 0; }
         t = -1;
      }
      trend[i] = t;
   }
}
void F_structure(QLBars &b, const int left, const int right, const int on_close, const double disp_atr,
                 double &bos_up[], double &bos_down[], double &choch_up[], double &choch_down[],
                 double &mss_up[], double &mss_down[], double &trend[])
{
   QL_Structure(b, left, right, on_close, disp_atr, bos_up, bos_down, choch_up, choch_down, mss_up, mss_down, trend);
}

// Moteur de zones commun (FVG, Order Blocks) — identique à qlab.features.ict._zones.
struct QLZone { int dir; double lo; double hi; int born; bool inv; };
void QL_Zones(QLBars &b, const int &cr_i[], const int &cr_dir[], const double &cr_lo[], const double &cr_hi[], const int ncr,
              const int expiry, double &bull[], double &bear[], double &ibull[], double &ibear[])
{
   int N = b.n;
   QL_Init(bull, N, 0); QL_Init(bear, N, 0); QL_Init(ibull, N, 0); QL_Init(ibear, N, 0);
   QLZone act[]; int na = 0;
   QLZone keep[];
   int p = 0;
   for(int i = 0; i < N; i++)
   {
      ArrayResize(keep, na + 8);
      int nk = 0;
      for(int z = 0; z < na; z++)
      {
         QLZone zz = act[z];
         if(i - zz.born > expiry) continue;
         int eff = zz.inv ? -zz.dir : zz.dir;
         if(eff == 1)
         {
            if(b.c[i] < zz.lo) { if(zz.inv) continue; zz.inv = true; keep[nk++] = zz; continue; }
            if(b.l[i] <= zz.hi && b.c[i] >= zz.lo) { if(zz.inv) ibull[i] = 1; else bull[i] = 1; continue; }
         }
         else
         {
            if(b.c[i] > zz.hi) { if(zz.inv) continue; zz.inv = true; keep[nk++] = zz; continue; }
            if(b.h[i] >= zz.lo && b.c[i] <= zz.hi) { if(zz.inv) ibear[i] = 1; else bear[i] = 1; continue; }
         }
         keep[nk++] = zz;
      }
      while(p < ncr && cr_i[p] == i)
      {
         ArrayResize(keep, nk + 1);
         keep[nk].dir = cr_dir[p]; keep[nk].lo = cr_lo[p]; keep[nk].hi = cr_hi[p]; keep[nk].born = i; keep[nk].inv = false;
         nk++; p++;
      }
      int start = MathMax(0, nk - 64);     // borne mémoire : 64 zones actives au plus
      na = nk - start;
      ArrayResize(act, na);
      for(int z = 0; z < na; z++) act[z] = keep[start + z];
   }
}
void F_fvg(QLBars &b, const double min_atr, const int expiry, double &new_bull[], double &new_bear[], double &bull_retest[],
           double &bear_retest[], double &ifvg_bull_retest[], double &ifvg_bear_retest[])
{
   int N = b.n;
   double atr[];
   QL_ATR(b, 14, atr);
   QL_Init(new_bull, N, 0); QL_Init(new_bear, N, 0);
   int ci[], cdir[]; double clo[], chi[]; int nc = 0;
   ArrayResize(ci, 2 * N); ArrayResize(cdir, 2 * N); ArrayResize(clo, 2 * N); ArrayResize(chi, 2 * N);
   // ordre de création identique à Python : haussiers puis baissiers, chacun par index croissant, puis tri stable par index
   for(int pass = 0; pass < 2; pass++)
      for(int i = 2; i < N; i++)
      {
         if(pass == 0)
         {
            bool ok = b.l[i] > b.h[i - 2] && (min_atr <= 0 || (QL_OK(atr[i]) && (b.l[i] - b.h[i - 2]) >= min_atr * atr[i]));
            if(ok) { new_bull[i] = 1; ci[nc] = i; cdir[nc] = 1; clo[nc] = b.h[i - 2]; chi[nc] = b.l[i]; nc++; }
         }
         else
         {
            bool ok = b.h[i] < b.l[i - 2] && (min_atr <= 0 || (QL_OK(atr[i]) && (b.l[i - 2] - b.h[i]) >= min_atr * atr[i]));
            if(ok) { new_bear[i] = 1; ci[nc] = i; cdir[nc] = -1; clo[nc] = b.h[i]; chi[nc] = b.l[i - 2]; nc++; }
         }
      }
   QL_SortCreations(ci, cdir, clo, chi, nc);
   QL_Zones(b, ci, cdir, clo, chi, nc, expiry, bull_retest, bear_retest, ifvg_bull_retest, ifvg_bear_retest);
}
// Tri stable par index de création (insertion), conserve l'ordre haussier puis baissier à index égal.
void QL_SortCreations(int &ci[], int &cdir[], double &clo[], double &chi[], const int nc)
{
   for(int a = 1; a < nc; a++)
   {
      int ki = ci[a], kd = cdir[a]; double kl = clo[a], kh = chi[a];
      int j = a - 1;
      while(j >= 0 && ci[j] > ki) { ci[j + 1] = ci[j]; cdir[j + 1] = cdir[j]; clo[j + 1] = clo[j]; chi[j + 1] = chi[j]; j--; }
      ci[j + 1] = ki; cdir[j + 1] = kd; clo[j + 1] = kl; chi[j + 1] = kh;
   }
}
void F_order_block(QLBars &b, const int left, const int right, const int lookback, const int expiry,
                   double &bull_retest[], double &bear_retest[], double &breaker_bull_retest[], double &breaker_bear_retest[])
{
   int N = b.n;
   double bu[], bd[], cu[], cd[], mu[], md[], tr[];
   QL_Structure(b, left, right, 1, 0.0, bu, bd, cu, cd, mu, md, tr);
   int ci[], cdir[]; double clo[], chi[]; int nc = 0;
   ArrayResize(ci, 2 * N); ArrayResize(cdir, 2 * N); ArrayResize(clo, 2 * N); ArrayResize(chi, 2 * N);
   for(int pass = 0; pass < 2; pass++)
      for(int i = 0; i < N; i++)
      {
         if((pass == 0 && bu[i] != 1) || (pass == 1 && bd[i] != 1)) continue;
         for(int j = i - 1; j >= MathMax(0, i - lookback); j--)
         {
            bool hit = pass == 0 ? (b.c[j] < b.o[j]) : (b.c[j] > b.o[j]);
            if(hit) { ci[nc] = i; cdir[nc] = pass == 0 ? 1 : -1; clo[nc] = b.l[j]; chi[nc] = b.h[j]; nc++; break; }
         }
      }
   QL_SortCreations(ci, cdir, clo, chi, nc);
   QL_Zones(b, ci, cdir, clo, chi, nc, expiry, bull_retest, bear_retest, breaker_bull_retest, breaker_bear_retest);
}
void QL_Equal(const double &lvl[], const double &conf[], const double &atr[], const int N, const double tol, double &out[])
{
   QL_Init(out, N, 0);
   double prev = QL_NAN;
   int last = -1;
   for(int i = 0; i < N; i++)
   {
      if(conf[i] != 1) continue;
      double cur = lvl[i];
      // la zone « égale » court de cette confirmation jusqu'à la suivante (exclue)
      if(QL_OK(prev) && QL_OK(atr[i]) && MathAbs(cur - prev) <= tol * atr[i])
      {
         int end = N;
         for(int k = i + 1; k < N; k++) if(conf[k] == 1) { end = k; break; }
         for(int k = i; k < end; k++) out[k] = 1;
      }
      prev = cur;
   }
}
void F_liquidity(QLBars &b, const int left, const int right, const double tol_atr,
                 double &sweep_high[], double &sweep_low[], double &equal_highs[], double &equal_lows[])
{
   int N = b.n;
   double lh[], ll[], ch[], cl[], atr[];
   QL_Pivots(b, left, right, lh, ll, ch, cl);
   QL_ATR(b, 14, atr);
   QL_Init(sweep_high, N, 0); QL_Init(sweep_low, N, 0);
   for(int i = 1; i < N; i++)
   {
      if(QL_OK(lh[i - 1]) && b.h[i] > lh[i - 1] && b.c[i] < lh[i - 1]) sweep_high[i] = 1;
      if(QL_OK(ll[i - 1]) && b.l[i] < ll[i - 1] && b.c[i] > ll[i - 1]) sweep_low[i] = 1;
   }
   QL_Equal(lh, ch, atr, N, tol_atr, equal_highs);
   QL_Equal(ll, cl, atr, N, tol_atr, equal_lows);
}
void QL_PrevExtremes(QLBars &b, const int weekly, double &ph[], double &pl[])
{
   int N = b.n;
   QL_Init(ph, N, QL_NAN); QL_Init(pl, N, QL_NAN);
   long g = -999999; double ch = 0, cl = 0, prevh = QL_NAN, prevl = QL_NAN;
   for(int i = 0; i < N; i++)
   {
      long gi = weekly ? QL_TradingWeek(b.t[i]) : QL_TradingDay(b.t[i]);
      if(gi != g)
      {
         if(g != -999999) { prevh = ch; prevl = cl; }
         g = gi; ch = b.h[i]; cl = b.l[i];
      }
      else { ch = MathMax(ch, b.h[i]); cl = MathMin(cl, b.l[i]); }
      ph[i] = prevh; pl[i] = prevl;
   }
}
void F_prev_extremes(QLBars &b, double &pdh[], double &pdl[], double &pwh[], double &pwl[])
{
   QL_PrevExtremes(b, 0, pdh, pdl);
   QL_PrevExtremes(b, 1, pwh, pwl);
}
void F_range_position(QLBars &b, const int lookback, double &value[])
{
   int N = b.n, from = b.n - QL_K;
   double hh[], ll[];
   QL_RollMax(b.h, N, lookback, from, hh); QL_RollMin(b.l, N, lookback, from, ll);
   QL_Init(value, N, QL_NAN);
   for(int i = 0; i < N; i++)
   {
      if(!QL_OK(hh[i]) || !QL_OK(ll[i])) continue;
      value[i] = hh[i] > ll[i] ? (b.c[i] - ll[i]) / (hh[i] - ll[i]) * 100.0 : 50.0;
   }
}
// ===================== fin de la bibliothèque QLab =====================


// ===================== Instances de features (génome) =====================
QLBars g_b0, g_b1;
double I0_new_bull[], I0_new_bear[], I0_bull_retest[], I0_bear_retest[], I0_ifvg_bull_retest[], I0_ifvg_bear_retest[];   // fvg{'expiry': 60, 'min_atr': 0.3} [M5]
double I1_bos_up[], I1_bos_down[], I1_choch_up[], I1_choch_down[], I1_mss_up[], I1_mss_down[], I1_trend[];   // structure{'break_on': 'close', 'disp_atr': 1.0, 'left': 3, 'right': 3} [H1]
double I2_active[];   // session{'name': 'london_kz'} [M5]
double I3_active[];   // session{'name': 'ny_am_kz'} [M5]
double I4_value[];   // range_position{'lookback': 100} [M5]
double I5_last_high[], I5_last_low[], I5_new_high[], I5_new_low[];   // swings{'left': 3, 'right': 3} [M5]
double I6_value[];   // atr{'period': 14} [M5]

double QL_At(const double &a[], QLBars &b, const int s) { int i = b.n - 1 - s; return i < 0 ? QL_NAN : a[i]; }
double QL_HTF(const double &a[], QLBars &h, QLBars &b, const int s)
{
   int i = b.n - 1 - s; if(i < 0) return QL_NAN;
   int k = QL_AlignAt(h, b.t[i] + b.tfsec);
   return k < 0 ? QL_NAN : a[k];
}
bool QL_LoadAll()
{
   if(!QL_Load(_Symbol, PERIOD_M5, 3000, g_b0)) return false;
   if(!QL_Load(_Symbol, PERIOD_H1, 3000, g_b1)) return false;
   return true;
}
void QL_ComputeAll()
{
   F_fvg(g_b0, 0.3, 60, I0_new_bull, I0_new_bear, I0_bull_retest, I0_bear_retest, I0_ifvg_bull_retest, I0_ifvg_bear_retest);
   F_structure(g_b1, 3, 3, 1, 1.0, I1_bos_up, I1_bos_down, I1_choch_up, I1_choch_down, I1_mss_up, I1_mss_down, I1_trend);
   F_session(g_b0, 0, 120, 300, I2_active);
   F_session(g_b0, 0, 420, 600, I3_active);
   F_range_position(g_b0, 100, I4_value);
   F_swings(g_b0, 3, 3, I5_last_high, I5_last_low, I5_new_high, I5_new_low);
   F_atr(g_b0, 14, I6_value);
}
bool QL_LongSignal()  { return (QL_EV(QL_At(I0_bull_retest, g_b0, 0)) && QL_GT(QL_HTF(I1_trend, g_b1, g_b0, 0), 0.0) && (QL_EV(QL_At(I2_active, g_b0, 0)) || QL_EV(QL_At(I3_active, g_b0, 0))) && QL_LT(QL_At(I4_value, g_b0, 0), 50.0)); }
bool QL_ShortSignal() { return false; }
double QL_StopDistance(const int d, const double entry)
{
   double a = QL_At(I6_value, g_b0, 0);
   double lvl = d == 1 ? QL_At(I5_last_low, g_b0, 0) - 0.2 * a : QL_At(I5_last_high, g_b0, 0) + 0.2 * a;
   return (entry - lvl) * d;
}
double QL_Target(const int d, const double entry, const double dist)
{
   return entry + d * 2.5 * dist;
}
double QL_TrailATR()
{
   return QL_At(I6_value, g_b0, 0);
}

// ===================== Moteur d'exécution QLab (miroir de qlab.backtest.engine) =====================
// Sémantique : conditions évaluées à la clôture de la barre i, ordre au marché à l'ouverture de i+1 ;
// stop/objectif côté serveur ; break-even, trailing, sortie sur signal opposé et time stop décidés
// à la clôture et appliqués à l'ouverture suivante. Une position à la fois.
#include <Trade/Trade.mqh>

input bool   InpTrace = true;     // trace de diagnostic (fichier commun QLab/<run>.csv)
input string InpRunId = "";       // identifiant de run (parité)

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
      bool opp = QL_GEN_EXIT_ON_OPPOSITE && ((g_dir == 1 && sig_short) || (g_dir == -1 && sig_long));
      int held = iBarShift(_Symbol, QL_GEN_TF, g_entry_bar, false);   // barres depuis l'entrée e jusqu'à la barre courante
      if(opp) { if(QL_ClosePosition("opposite_signal")) { g_last_exit_bar = bt; has = false; g_had_pos = false; } }
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
   double risk_pct = MathMin(QL_GEN_RISK_PCT, QL_LIM_MAX_RISK_PCT);
   double raw_lots = AccountInfoDouble(ACCOUNT_BALANCE) * risk_pct / 100.0 / (dist * vpu);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), QL_LIM_MAX_LOTS);
   double lots = MathFloor(raw_lots / step + 1e-9) * step;
   lots = MathMin(NormalizeDouble(lots, 8), vmax);
   if(lots < vmin) { QL_Trace("SKIP;lots_below_min"); return; }
   string why = QL_RiskCheck(day, lots, (double)(tk.ask - tk.bid) / pt);
   if(why != "") { QL_Trace("SKIP;risk:" + why); return; }

   bool ok = d == 1 ? g_trade.Buy(lots, _Symbol, 0.0, NormalizeDouble(sl, _Digits), QL_OK(tp) ? NormalizeDouble(tp, _Digits) : 0.0, "qlab")
                    : g_trade.Sell(lots, _Symbol, 0.0, NormalizeDouble(sl, _Digits), QL_OK(tp) ? NormalizeDouble(tp, _Digits) : 0.0, "qlab");
   if(!ok) { QL_Trace("ORDERFAIL;" + IntegerToString((int)g_trade.ResultRetcode())); return; }
   g_day_orders++;
   g_cnt++;
   g_entry_bar = bt; g_entry = g_trade.ResultPrice() > 0 ? g_trade.ResultPrice() : entry;
   g_dist = dist; g_sl = sl; g_dir = d; g_be_done = false; g_had_pos = true;
   QL_Trace(StringFormat("ENTRY;%I64d;%d;%.8f;%.8f;%.8f;%.2f", close_utc, d, g_entry, sl, QL_OK(tp) ? tp : 0.0, lots));
}
