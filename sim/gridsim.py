"""FX ナンピン EA (NanpinFX.mq5) と同じルールを 1 分足で再現するシミュレーター。

口座通貨はその通貨ペアの決済通貨(EURUSD ならドル、USDJPY なら円)として計算する。
ロットは連続値(0.01 単位の切り捨てはしない)。
"""
import glob
import numpy as np, pandas as pd
from numba import njit

# ---------------------------------------------------------------- データ
def pip_of(sym):
    return 0.01 if "JPY" in sym else 0.0001


def load(sym, d, ym_from="2016_01", ym_to="2026_10"):
    fs = [f for f in sorted(glob.glob(f"{d}/{sym}_*.npy")) if ym_from <= f[-11:-4] <= ym_to]
    a = np.concatenate([np.load(f) for f in fs])
    a = a[np.argsort(a[:, 0], kind="stable")]
    t = a[:, 0].astype("int64")
    # サーバー時間 = ニューヨーク時間 + 7 時間 (NY 17時 = サーバー 0時 で日付が変わる)
    ny = pd.to_datetime(t, unit="s", utc=True).tz_convert("America/New_York").tz_localize(None)
    st = ny.values.astype("datetime64[s]").astype("int64") + 7 * 3600
    m = dict(sym=sym, t=st, o=a[:, 1].copy(), h=a[:, 2].copy(), l=a[:, 3].copy(), c=a[:, 4].copy(),
             sp=a[:, 5].copy(), spmax=a[:, 6].copy(), ah=a[:, 7].copy(), al=a[:, 8].copy())
    # 壊れた足(Ask の極値が Bid と矛盾)を補正
    m["ah"] = np.maximum(m["ah"], m["h"] + m["sp"] * 0.5)
    m["al"] = np.maximum(np.minimum(m["al"], m["l"] + m["sp"]), m["l"])
    return m


# ---------------------------------------------------------------- スワップ(年率%, 政策金利のおおよその年平均)
RATES = {  # 2016 .. 2026
    "USD": [0.40, 1.00, 1.80, 2.20, 0.40, 0.10, 1.70, 5.00, 5.10, 4.20, 3.70],
    "EUR": [-0.35, -0.40, -0.40, -0.45, -0.50, -0.50, 0.10, 3.30, 3.60, 2.20, 2.00],
    "JPY": [-0.10, -0.10, -0.10, -0.10, -0.10, -0.10, -0.10, -0.10, 0.10, 0.50, 0.75],
    "GBP": [0.40, 0.30, 0.60, 0.75, 0.20, 0.10, 1.50, 4.70, 5.10, 4.20, 3.80],
    "AUD": [1.60, 1.50, 1.50, 1.10, 0.30, 0.10, 1.30, 3.90, 4.35, 3.90, 3.60],
    "NZD": [2.10, 1.75, 1.75, 1.30, 0.40, 0.40, 2.50, 5.40, 5.20, 3.50, 2.50],
    "CAD": [0.50, 0.70, 1.40, 1.75, 0.50, 0.25, 2.00, 4.80, 4.50, 2.80, 2.25],
    "CHF": [-0.75, -0.75, -0.75, -0.75, -0.75, -0.75, -0.20, 1.50, 1.30, 0.20, 0.00],
}
SWAP_MARKUP = 1.5   # 証券会社の上乗せ(年率%, 買い・売りそれぞれ)


def swap_tables(sym, t):
    """日ごとのスワップ(建玉の想定元本に対する1泊あたりの比率, マイナス=支払い)。"""
    base, quote = sym[:3], sym[3:6]
    day0 = int(t[0] // 86400)
    days = np.arange(day0, int(t[-1] // 86400) + 2)
    yr = pd.to_datetime(days * 86400, unit="s").year.values
    yi = np.clip(yr - 2016, 0, 10)
    rb = np.array(RATES[base])[yi]; rq = np.array(RATES[quote])[yi]
    swl = (rb - rq - SWAP_MARKUP) / 100.0 / 365.0
    sws = (rq - rb - SWAP_MARKUP) / 100.0 / 365.0
    return day0, swl, sws


# ---------------------------------------------------------------- 指標
def sma(x, n): return pd.Series(x).rolling(n).mean().values
def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values


def rsi_wilder(c, n):
    d = np.diff(c, prepend=c[0]); g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
    ag = pd.Series(g).ewm(alpha=1.0 / n, adjust=False).mean().values
    al = pd.Series(l).ewm(alpha=1.0 / n, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100.0 - 100.0 / (1.0 + ag / al)
    r[al == 0] = 100.0
    r[:n] = np.nan
    return r


def atr_sma(h, l, c, n):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return sma(tr, n)


def resample(m, minutes):
    """1分足 → minutes 分足。戻り値: 足の配列と、1分足ごとの「直前に確定した足」の番号、足の最初の1分足フラグ。"""
    key = m["t"] // (minutes * 60)
    first = np.ones(len(key), bool); first[1:] = key[1:] != key[:-1]
    gid = np.cumsum(first) - 1
    idx = np.flatnonzero(first)
    o = m["o"][idx]
    h = np.maximum.reduceat(m["h"], idx); l = np.minimum.reduceat(m["l"], idx)
    last = np.r_[idx[1:] - 1, len(key) - 1]; c = m["c"][last]
    bt = key[idx] * minutes * 60
    prev = gid - 1   # 1分足 k の時点で確定している最新の足
    return dict(t=bt, o=o, h=h, l=l, c=c), prev, first


# ---------------------------------------------------------------- 本体
@njit(cache=True)
def run_grid(t, o, h, l, c, sp, ah, al, day0, swl, sws,
             sigB, sigS, okNew, scale,
             off, mult, tpd, surv, use_stop,
             risk_frac, fixed_lot, contract, leverage, stopout, bal0,
             both_sides, min_add_sec, max_sp, maxdd_frac, cut_frac):
    """
    off[j]  : j 本目(0 始まり)の建値の、初回建値からの距離 (scale 倍して価格に)
    mult[j] : j 本目のロット倍率
    tpd     : 平均建値から利確までの距離 (scale 倍)
    surv    : 初回建値から「耐えるライン」までの距離 (scale 倍)。use_stop なら ここで全決済
    risk_frac: 耐えるラインで全決済した時の損失 = 残高 × risk_frac になるよう初回ロットを決める
    cut_frac: バスケットの含み損が残高の cut_frac を超えたら全決済 (0=無効)
    """
    N = len(t); NL = len(off)
    unit = 0.0
    for j in range(NL):
        unit += mult[j] * (surv - off[j])
    unit *= contract                 # 初回 1 ロット・scale=1 の時の、耐えるラインでの損失
    bal = bal0; peak = bal0
    n = np.zeros(2, np.int64); SL = np.zeros(2); SP = np.zeros(2); first = np.zeros(2); L0 = np.zeros(2)
    sc = np.zeros(2); sw = np.zeros(2); tin = np.zeros(2, np.int64); lastAdd = np.zeros(2, np.int64)
    mae = np.zeros(2)
    rec = np.zeros((200000, 9)); nr = 0
    ndays = int((t[N - 1] - t[0]) // 86400) + 3
    dbal = np.zeros(ndays); deq = np.zeros(ndays); dday = np.zeros(ndays, np.int64); nd = 0
    curDay = t[0] // 86400; dayMinEq = bal
    halted = False; ruined = False
    bp = np.zeros(4); ap = np.zeros(4)
    for k in range(N):
        tk = t[k]; day = tk // 86400
        if day != curDay:
            dday[nd] = curDay; dbal[nd] = bal; deq[nd] = dayMinEq; nd += 1
            nights = 3.0 if (day + 3) % 7 == 3 else 1.0
            di = day - day0
            if n[0] > 0: sw[0] += SL[0] * contract * o[k] * swl[di] * nights
            if n[1] > 0: sw[1] += SL[1] * contract * o[k] * sws[di] * nights
            curDay = day
            fl = 0.0
            if n[0] > 0: fl += SL[0] * contract * o[k] - SP[0] * contract + sw[0]
            if n[1] > 0: fl += SP[1] * contract - SL[1] * contract * (o[k] + sp[k]) + sw[1]
            dayMinEq = bal + fl
        if ruined:
            continue
        s = sp[k]
        # ---- 新規
        if not halted and okNew[k] and (max_sp <= 0.0 or s <= max_sp) and scale[k] > 0.0:
            for side in range(2):
                if n[side] > 0: continue
                if side == 0 and not sigB[k]: continue
                if side == 1 and not sigS[k]: continue
                if not both_sides and n[1 - side] > 0: continue
                lot = fixed_lot if fixed_lot > 0.0 else bal * risk_frac / (unit * scale[k])
                px = o[k] + s if side == 0 else o[k]
                n[side] = 1; L0[side] = lot; SL[side] = lot; SP[side] = lot * px; first[side] = px
                sc[side] = scale[k]; sw[side] = 0.0; tin[side] = tk; lastAdd[side] = tk; mae[side] = 0.0
        if n[0] == 0 and n[1] == 0:
            if bal < dayMinEq: dayMinEq = bal
            continue
        # ---- 足の中の値動き (陽線: 始→安→高→終、陰線: 始→高→安→終)
        if c[k] >= o[k]:
            bp[0] = o[k]; bp[1] = l[k]; bp[2] = h[k]; bp[3] = c[k]
            ap[0] = o[k] + s; ap[1] = al[k]; ap[2] = ah[k]; ap[3] = c[k] + s
        else:
            bp[0] = o[k]; bp[1] = h[k]; bp[2] = l[k]; bp[3] = c[k]
            ap[0] = o[k] + s; ap[1] = ah[k]; ap[2] = al[k]; ap[3] = c[k] + s
        for g in range(1, 4):
            b0 = bp[g - 1]; b1 = bp[g]; a0 = ap[g - 1]; a1 = ap[g]
            for side in range(2):
                if n[side] == 0: continue
                d = 1.0 if side == 0 else -1.0
                scl = sc[side]
                ex = 0.0; why = 0
                if side == 0:
                    # 買い: ナンピン(Ask が下がる)
                    if a1 < a0:
                        while n[0] < NL and (max_sp <= 0.0 or s <= max_sp):
                            lvl = first[0] - off[n[0]] * scl
                            if a1 <= lvl and tk - lastAdd[0] >= min_add_sec:
                                fp = lvl if a0 > lvl else a0
                                lt = L0[0] * mult[n[0]]
                                SL[0] += lt; SP[0] += lt * fp; n[0] += 1; lastAdd[0] = tk
                                if min_add_sec > 0: break
                            else:
                                break
                    if b1 < b0 and use_stop:
                        stp = first[0] - surv * scl
                        if b1 <= stp: ex = stp if b0 > stp else b0; why = -1
                    if why == 0 and b1 > b0:
                        tp = SP[0] / SL[0] + tpd * scl
                        if b1 >= tp: ex = tp if b0 < tp else b0; why = 1
                    px_exit = b1
                else:
                    # 売り: ナンピン(Bid が上がる)
                    if b1 > b0:
                        while n[1] < NL and (max_sp <= 0.0 or s <= max_sp):
                            lvl = first[1] + off[n[1]] * scl
                            if b1 >= lvl and tk - lastAdd[1] >= min_add_sec:
                                fp = lvl if b0 < lvl else b0
                                lt = L0[1] * mult[n[1]]
                                SL[1] += lt; SP[1] += lt * fp; n[1] += 1; lastAdd[1] = tk
                                if min_add_sec > 0: break
                            else:
                                break
                    if a1 > a0 and use_stop:
                        stp = first[1] + surv * scl
                        if a1 >= stp: ex = stp if a0 < stp else a0; why = -1
                    if why == 0 and a1 < a0:
                        tp = SP[1] / SL[1] - tpd * scl
                        if a1 <= tp: ex = tp if a0 > tp else a0; why = 1
                    px_exit = a1
                # 含み損の上限(残高比)
                if why == 0 and cut_frac > 0.0:
                    fl = (SL[side] * px_exit - SP[side]) * contract * d + sw[side]
                    if fl <= -cut_frac * bal: ex = px_exit; why = -3
                if why != 0:
                    pnl = (SL[side] * ex - SP[side]) * contract * d + sw[side]
                    fl = (SL[side] * px_exit - SP[side]) * contract * d + sw[side]
                    if fl < mae[side]: mae[side] = fl
                    if nr < rec.shape[0]:
                        rec[nr, 0] = tin[side]; rec[nr, 1] = tk; rec[nr, 2] = side; rec[nr, 3] = n[side]
                        rec[nr, 4] = pnl; rec[nr, 5] = pnl / bal; rec[nr, 6] = why
                        rec[nr, 7] = min(mae[side], pnl) / bal; rec[nr, 8] = SL[side] / L0[side]; nr += 1
                    bal += pnl; n[side] = 0; SL[side] = 0.0; SP[side] = 0.0
                    if bal > peak: peak = bal
            # ---- 口座全体: 含み損益・証拠金維持率
            fl = 0.0
            if n[0] > 0:
                f0 = (SL[0] * b1 - SP[0]) * contract + sw[0]; fl += f0
                if f0 < mae[0]: mae[0] = f0
            if n[1] > 0:
                f1 = (SP[1] - SL[1] * a1) * contract + sw[1]; fl += f1
                if f1 < mae[1]: mae[1] = f1
            eq = bal + fl
            if eq < dayMinEq: dayMinEq = eq
            mg = max(SL[0], SL[1]) * contract * b1 / leverage
            so = mg > 0.0 and eq <= stopout * mg
            dd = maxdd_frac > 0.0 and eq <= peak * (1.0 - maxdd_frac)
            if so or dd:
                for side in range(2):
                    if n[side] == 0: continue
                    d = 1.0 if side == 0 else -1.0
                    px = b1 if side == 0 else a1
                    pnl = (SL[side] * px - SP[side]) * contract * d + sw[side]
                    if nr < rec.shape[0]:
                        rec[nr, 0] = tin[side]; rec[nr, 1] = tk; rec[nr, 2] = side; rec[nr, 3] = n[side]
                        rec[nr, 4] = pnl; rec[nr, 5] = pnl / bal; rec[nr, 6] = -2 if so else -4
                        rec[nr, 7] = min(mae[side], pnl) / bal; rec[nr, 8] = SL[side] / L0[side]; nr += 1
                    bal += pnl; n[side] = 0; SL[side] = 0.0; SP[side] = 0.0
                if bal < dayMinEq: dayMinEq = bal
                if dd: halted = True
                if bal <= bal0 * 0.02:
                    ruined = True
                    break
    dday[nd] = curDay; dbal[nd] = bal; deq[nd] = dayMinEq; nd += 1
    return rec[:nr], dday[:nd], dbal[:nd], deq[:nd], bal, ruined


# ---------------------------------------------------------------- グリッドの形
def grid_shape(nanpin, step, grow, lotmult, lot_add=0.0):
    """初回 + ナンピン nanpin 回。step=1回目の幅, grow=回ごとの幅の拡大率。
    lotmult=回ごとのロット倍率(掛け算)、lot_add>0 なら 1,1+a,1+2a... の足し算。"""
    NL = nanpin + 1
    off = np.zeros(NL); mult = np.ones(NL)
    for j in range(1, NL):
        off[j] = off[j - 1] + step * grow ** (j - 1)
        mult[j] = (1.0 + lot_add * j) if lot_add > 0 else lotmult ** j
    return off, mult


def unit_loss(off, mult, surv):
    return float(np.sum(mult * (surv - off)))


# ---------------------------------------------------------------- 集計
def summarize(m, rec, dday, dbal, deq, bal_end, ruined, bal0=1.0):
    days = pd.to_datetime(dday * 86400, unit="s")
    s = pd.Series(dbal, index=days)
    me = s.resample("ME").last().dropna()
    prev = np.r_[bal0, me.values[:-1]]
    mret = me.values / prev - 1.0
    eqmin = pd.Series(deq, index=days)
    peak = np.maximum.accumulate(np.maximum(s.values, bal0))
    dd = 1.0 - eqmin.values / peak
    nmon = len(mret)
    gm = (bal_end / bal0) ** (1.0 / max(nmon, 1)) - 1.0 if bal_end > 0 else -1.0
    why = rec[:, 6] if len(rec) else np.zeros(0)
    return dict(
        months=nmon, final=bal_end / bal0, geo_month=gm, med_month=float(np.median(mret)) if nmon else 0.0,
        best_month=float(mret.max()) if nmon else 0.0, worst_month=float(mret.min()) if nmon else 0.0,
        neg_months=float((mret < 0).mean()) if nmon else 0.0, maxdd=float(dd.max()) if len(dd) else 0.0,
        trades=len(rec), stops=int((why == -1).sum()), cuts=int((why == -3).sum()),
        stopouts=int((why == -2).sum()), halts=int((why == -4).sum()), ruined=bool(ruined),
        maxlev=int(rec[:, 3].max()) if len(rec) else 0,
    ), pd.Series(mret, index=me.index)
