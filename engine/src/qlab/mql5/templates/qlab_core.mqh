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
// Minutes jusqu'à la clôture hebdomadaire (vendredi 17:00 New York) — miroir de minutes_to_weekly_close.
double QL_MinToWeeklyClose(const long u)
{
   long loc = u + QL_NYOffset(u);
   int wd = (QL_DOW(loc) + 6) % 7;                 // 0 = lundi
   double mins = (double)(((loc % 86400) + 86400) % 86400) / 60.0;
   double out = ((4 - wd + 7) % 7) * 1440.0 + (1020.0 - mins);
   return out <= 0 ? out + 10080.0 : out;
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
   if(got < W) { SymbolSelect(sym, true); return false; }  // historique insuffisant : aucun signal (prudence)
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
// ---------------------------------------------------------------- itération 2 : Judas, PO3, SMT, Mitigation
void F_judas(QLBars &b, const double sweep_atr, double &asian_high[], double &asian_low[], double &judas_bull[], double &judas_bear[])
{
   int N = b.n;
   double atr[];
   QL_ATR(b, 14, atr);
   QL_Init(asian_high, N, QL_NAN); QL_Init(asian_low, N, QL_NAN); QL_Init(judas_bull, N, 0); QL_Init(judas_bear, N, 0);
   long cur = -999999;
   double hi = -DBL_MAX, lo = DBL_MAX;
   bool seen = false, done = false, fired = false;
   for(int i = 0; i < N; i++)
   {
      long d = QL_TradingDay(b.t[i]);
      if(d != cur) { cur = d; hi = -DBL_MAX; lo = DBL_MAX; seen = false; done = false; fired = false; }
      bool asia = QL_InSession(b.t[i] + b.tfsec, 0, 1200, 0);
      bool ldn = QL_InSession(b.t[i] + b.tfsec, 0, 120, 300);
      if(asia) { if(!done) { hi = MathMax(hi, b.h[i]); lo = MathMin(lo, b.l[i]); seen = true; } }
      else if(seen) done = true;
      if(done)
      {
         asian_high[i] = hi; asian_low[i] = lo;
         if(ldn && !fired && QL_OK(atr[i]))
         {
            if(b.l[i] < lo - sweep_atr * atr[i] && b.c[i] > lo) { judas_bull[i] = 1; fired = true; }
            else if(b.h[i] > hi + sweep_atr * atr[i] && b.c[i] < hi) { judas_bear[i] = 1; fired = true; }
         }
      }
   }
}

void F_po3(QLBars &b, const double manip_atr, double &midnight_open[], double &po3_bull[], double &po3_bear[])
{
   int N = b.n;
   double atr[];
   QL_ATR(b, 14, atr);
   QL_Init(midnight_open, N, QL_NAN); QL_Init(po3_bull, N, 0); QL_Init(po3_bear, N, 0);
   long cur = -999999;
   double op = QL_NAN;
   bool down = false, up = false;
   int state = 0;
   for(int i = 0; i < N; i++)
   {
      long d = QL_TradingDay(b.t[i]);
      if(d != cur) { cur = d; op = QL_NAN; down = false; up = false; state = 0; }
      if(!QL_OK(op) && QL_LocalMinutes(b.t[i], 0) < 1020) op = b.o[i];
      if(QL_OK(op))
      {
         midnight_open[i] = op;
         if(state == 0 && QL_OK(atr[i]))
         {
            if(b.l[i] <= op - manip_atr * atr[i]) down = true;
            if(b.h[i] >= op + manip_atr * atr[i]) up = true;
            if(down && b.c[i] > op) state = 1;
            else if(up && b.c[i] < op) state = -1;
         }
         po3_bull[i] = state == 1 ? 1 : 0; po3_bear[i] = state == -1 ? 1 : 0;
      }
   }
}

void F_mitigation(QLBars &b, const int left, const int right, const int lookback, const int expiry, double &bull_retest[], double &bear_retest[])
{
   int N = b.n;
   double lh[], ll[], ch[], cl[], bu[], bd[], cu[], cd[], mu[], md[], tr[];
   QL_Pivots(b, left, right, lh, ll, ch, cl);
   QL_Structure(b, left, right, 1, 0.0, bu, bd, cu, cd, mu, md, tr);
   double prev_h[], prev_l[];
   QL_Init(prev_h, N, QL_NAN); QL_Init(prev_l, N, QL_NAN);
   double ph = QL_NAN, pl = QL_NAN, last_h = QL_NAN, last_l = QL_NAN;
   for(int i = 0; i < N; i++)
   {
      if(ch[i] == 1) { ph = last_h; last_h = lh[i]; }
      if(cl[i] == 1) { pl = last_l; last_l = ll[i]; }
      prev_h[i] = ph; prev_l[i] = pl;
   }
   int ci[], cdir[]; double clo[], chi[]; int nc = 0;
   ArrayResize(ci, 2 * N); ArrayResize(cdir, 2 * N); ArrayResize(clo, 2 * N); ArrayResize(chi, 2 * N);
   for(int pass = 0; pass < 2; pass++)
      for(int i = 1; i < N; i++)
      {
         bool ok;
         if(pass == 0) ok = bu[i] == 1 && QL_OK(ll[i - 1]) && QL_OK(prev_l[i - 1]) && ll[i - 1] > prev_l[i - 1];
         else          ok = bd[i] == 1 && QL_OK(lh[i - 1]) && QL_OK(prev_h[i - 1]) && lh[i - 1] < prev_h[i - 1];
         if(!ok) continue;
         for(int j = i - 1; j >= MathMax(0, i - lookback); j--)
         {
            bool hit = pass == 0 ? (b.c[j] < b.o[j]) : (b.c[j] > b.o[j]);
            if(hit) { ci[nc] = i; cdir[nc] = pass == 0 ? 1 : -1; clo[nc] = b.l[j]; chi[nc] = b.h[j]; nc++; break; }
         }
      }
   QL_SortCreations(ci, cdir, clo, chi, nc);
   double ib[], is[];
   QL_Zones(b, ci, cdir, clo, chi, nc, expiry, bull_retest, bear_retest, ib, is);
}

// Index de la barre de référence de même horodatage, -1 sinon.
int QL_FindTs(QLBars &r, const long t)
{
   int lo = 0, hi = r.n - 1;
   while(lo <= hi)
   {
      int mid = (lo + hi) / 2;
      if(r.t[mid] == t) return mid;
      if(r.t[mid] < t) lo = mid + 1; else hi = mid - 1;
   }
   return -1;
}

void F_smt(QLBars &b, QLBars &r, const int lookback, double &bull[], double &bear[])
{
   int N = b.n;
   QL_Init(bull, N, 0); QL_Init(bear, N, 0);
   for(int i = MathMax(lookback, N - QL_K); i < N; i++)
   {
      double pl = DBL_MAX, ph = -DBL_MAX, rpl = DBL_MAX, rph = -DBL_MAX;
      bool ok = true;
      int ki = QL_FindTs(r, b.t[i]);
      if(ki < 0) continue;
      for(int k = i - lookback; k < i; k++)
      {
         pl = MathMin(pl, b.l[k]); ph = MathMax(ph, b.h[k]);
         int q = QL_FindTs(r, b.t[k]);
         if(q < 0) { ok = false; break; }
         rpl = MathMin(rpl, r.l[q]); rph = MathMax(rph, r.h[q]);
      }
      if(!ok) continue;
      if(b.l[i] < pl && r.l[ki] >= rpl) bull[i] = 1;
      if(b.h[i] > ph && r.h[ki] <= rph) bear[i] = 1;
   }
}
// ---------------------------------------------------------------- régimes v1.1 (miroir de qlab.regime.engine)
void F_regime(QLBars &b, const int trend_period, const int confirm,
              double &bull_trend[], double &bear_trend[], double &range_[], double &compression[], double &expansion[],
              double &transition[], double &disturbed[], double &confidence[], double &trend_slope[], double &vol_ratio[])
{
   int N = b.n;
   double adx[], pdi[], mdi[], e[], a14[], a5[], a50[];
   F_adx(b, 14, adx, pdi, mdi);
   QL_EMA(b.c, N, trend_period, e);
   QL_ATR(b, 14, a14); QL_ATR(b, 5, a5); QL_ATR(b, 50, a50);
   QL_Init(trend_slope, N, QL_NAN); QL_Init(vol_ratio, N, QL_NAN);
   int raw[]; ArrayResize(raw, N);
   double sum = 0; int cnt = 0;   // moyenne glissante des spreads > 0 sur 100 barres
   for(int i = 0; i < N; i++)
   {
      if(b.sp[i] > 0) { sum += b.sp[i]; cnt++; }
      if(i >= 100 && b.sp[i - 100] > 0) { sum -= b.sp[i - 100]; cnt--; }
      double mean = cnt >= 20 ? sum / cnt : QL_NAN;
      if(i >= 5 && QL_OK(e[i]) && QL_OK(e[i - 5]) && QL_OK(a14[i]) && a14[i] != 0) trend_slope[i] = (e[i] - e[i - 5]) / (a14[i] * 5);
      if(QL_OK(a5[i]) && QL_OK(a50[i]) && a50[i] != 0) vol_ratio[i] = a5[i] / a50[i];
      bool dist = (QL_OK(a50[i]) && (b.h[i] - b.l[i]) > 4 * a50[i]) || (b.sp[i] > 0 && QL_OK(mean) && b.sp[i] > 3 * mean);
      bool known = QL_OK(adx[i]) && QL_OK(trend_slope[i]) && QL_OK(vol_ratio[i]);
      int r = known ? 5 : -1;
      if(known)
      {
         double s = trend_slope[i], c = vol_ratio[i];
         if(dist) r = 6;
         else if(c < 0.7) r = 3;
         else if(c > 1.5) r = 4;
         else if(adx[i] > 25 && s > 0.1) r = 0;
         else if(adx[i] > 25 && s < -0.1) r = 1;
         else if(adx[i] < 20) r = 2;
      }
      raw[i] = r;
   }
   int cur[]; ArrayResize(cur, N);
   int state = -1, pend = -1, cntp = 0;
   for(int i = 0; i < N; i++)
   {
      int r = raw[i];
      if(r == -1) { state = -1; pend = -1; cntp = 0; }
      else if(state == -1) state = r;
      else if(r != state)
      {
         cntp = (r == pend) ? cntp + 1 : 1;
         pend = r;
         if(cntp >= confirm) { state = r; pend = -1; cntp = 0; }
      }
      else { pend = -1; cntp = 0; }
      cur[i] = state;
   }
   QL_Init(bull_trend, N, 0); QL_Init(bear_trend, N, 0); QL_Init(range_, N, 0); QL_Init(compression, N, 0);
   QL_Init(expansion, N, 0); QL_Init(transition, N, 0); QL_Init(disturbed, N, 0); QL_Init(confidence, N, QL_NAN);
   int w = 3 * confirm;
   for(int i = 0; i < N; i++)
   {
      bull_trend[i] = cur[i] == 0 ? 1.0 : 0.0; bear_trend[i] = cur[i] == 1 ? 1.0 : 0.0; range_[i] = cur[i] == 2 ? 1.0 : 0.0; compression[i] = cur[i] == 3 ? 1.0 : 0.0;
      expansion[i] = cur[i] == 4 ? 1.0 : 0.0; transition[i] = cur[i] == 5 ? 1.0 : 0.0; disturbed[i] = cur[i] == 6 ? 1.0 : 0.0;
      if(cur[i] < 0 || i < N - QL_K) continue;
      double m = 0; int k = 0;
      for(int j = MathMax(0, i - w + 1); j <= i; j++) { m += (raw[j] == cur[i]) ? 1 : 0; k++; }
      confidence[i] = m / k * 100.0;
   }
}
// ===================== fin de la bibliothèque QLab =====================
