"""NanpinFX の検証(README の表を作ったスクリプト)。

  データ: python3 sim/fx_fetch.py DATA 2016_01 2026_10 EURUSDm USDJPYm ...
  総当たり: python3 sim/fx_research.py screen DATA out.pkl EURUSDm USDJPYm ...
  既定設定: python3 sim/fx_research.py full   DATA out.pkl EURUSDm USDJPYm ...
  飛ぶまで: python3 sim/fx_research.py ruin   DATA out.pkl EURUSDm USDJPYm ...

「攻め度 rf」= 耐えるラインで全決済した時の損失 ÷ 残高 (EA の RiskPct / 100)。
rf>1 は「ナンピン10回に耐えられない」ロット(耐えるラインより手前で口座がなくなる)。
"""
import sys, os
from multiprocessing import Pool
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gridsim import (load, swap_tables, resample, atr_sma, rsi_wilder, ema, grid_shape, unit_loss,
                     run_grid, summarize, pip_of)

DEFAULT = ("rsi25", 0.6, 1.2, 1.7, 1.0)   # (エントリー, 1回目の幅[日足ATR], 幅の拡大率, ロット倍率, 利確[1回目の幅の倍率])
T_SPLIT = int(pd.Timestamp("2021-07-01").timestamp())
DATA = None


def prep(sym):
    m = load(sym, DATA)
    day0, swl, sws = swap_tables(sym[:6], m["t"])
    d1, prevd, _ = resample(m, 1440)
    atrd = atr_sma(d1["h"], d1["l"], d1["c"], 14)
    pdx = np.clip(prevd, 0, None)
    scale = np.nan_to_num(np.where(prevd >= 0, atrd[pdx], np.nan), nan=0.0)   # 確定済みの日足ATR(14)
    h1, prevh, _ = resample(m, 60)
    rsi = rsi_wilder(h1["c"], 14)
    r = np.nan_to_num(np.where(prevh >= 0, rsi[np.clip(prevh, 0, None)], 50.0), nan=50.0)  # 確定済みの1時間足RSI
    e200 = ema(d1["c"], 200)
    up = (prevd >= 5) & (d1["c"][pdx] > e200[pdx]); dn = (prevd >= 5) & (d1["c"][pdx] < e200[pdx])
    hour = (m["t"] // 3600) % 24; dow = ((m["t"] // 86400) + 4) % 7   # サーバー時間, 0=日曜
    m.update(N=len(m["t"]), day0=day0, swl=swl, sws=sws, scale=scale, rsi=r, up=up, dn=dn, hour=hour, dow=dow)
    t0, t1 = pd.to_datetime(m["t"][[0, -1]], unit="s")
    m["months"] = (t1.year - t0.year) * 12 + (t1.month - t0.month) + 1
    return m


def entries(m, en):
    ones = np.ones(m["N"], bool)
    return {
        "always": (ones, ones, ones),
        "always_trend": (m["up"], m["dn"], ones),
        "rsi30": (m["rsi"] < 30, m["rsi"] > 70, ones),
        "rsi25": (m["rsi"] < 25, m["rsi"] > 75, ones),
        "rsi30_trend": ((m["rsi"] < 30) & m["up"], (m["rsi"] > 70) & m["dn"], ones),
        "asia": (ones, ones, (m["hour"] >= 2) & (m["hour"] < 9)),
    }[en]


def ea_filter(m, from_h=23, to_h=1, fri=20):
    """EA の既定: 23時〜1時(サーバー時間)と金曜20時以降は新規なし"""
    hr = m["hour"]
    blocked = (hr >= from_h) | (hr < to_h) if from_h > to_h else (hr >= from_h) & (hr < to_h)
    return ~blocked & ~((m["dow"] == 5) & (hr >= fri))


def run(m, cfg, rf, filt=True, maxsp_pips=3.0, a=0, bal0=1.0, nanpin=10):
    en, step, grow, lm, tpr = cfg
    sb, ss, ok = entries(m, en)
    if filt:
        ok = ok & ea_filter(m)
    off, mult = grid_shape(nanpin, step, grow, lm)
    surv = off[-1] + step * grow ** nanpin      # 耐えるライン = 最後のナンピン + 次の1段
    sp = maxsp_pips * pip_of(m["sym"]) if (filt and maxsp_pips > 0) else 0.0
    S = slice(a, None)
    return run_grid(m["t"][S], m["o"][S], m["h"][S], m["l"][S], m["c"][S], m["sp"][S], m["ah"][S], m["al"][S],
                    m["day0"], m["swl"], m["sws"], sb[S], ss[S], ok[S], m["scale"][S], off, mult, step * tpr, surv,
                    True, rf, 0.0, 100000.0, 1000.0, 0.2, bal0, True, 0, sp, 0.0, 0.0)


# ---------------------------------------------------------------- 総当たり
RFS = np.array([0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0])


def grids():
    for en in ["always", "always_trend", "rsi30", "rsi25", "rsi30_trend", "asia"]:
        for step in [0.05, 0.1, 0.15, 0.25, 0.4, 0.6, 1.0]:
            for grow in [1.0, 1.2, 1.4]:
                for lm in [1.0, 1.2, 1.4, 1.7]:
                    for tpr in [0.5, 1.0, 1.5]:
                        yield (en, step, grow, lm, tpr)


def screen_one(sym):
    """小さい攻め度(0.1%)で回し、1回ごとの損益を「耐えるライン損失=1」の単位にして、どの攻め度でも複利を計算する。
    攻め度は最大 1.0 まで(=耐えるラインで口座全損)。"""
    m = prep(sym); out = []
    months = m["months"]
    for cfg in grids():
        rec = run(m, cfg, 0.001, filt=False)[0]
        if len(rec) == 0:
            continue
        R = rec[:, 5] / 0.001; late = rec[:, 1] >= T_SPLIT
        g = []
        for rf in RFS:
            x = 1.0 + rf * R
            g.append(-1.0 if (x <= 0).any() else np.exp(np.log(x).sum() / months) - 1.0)
        g = np.array(g)
        out.append(dict(sym=sym, entry=cfg[0], step=cfg[1], grow=cfg[2], lm=cfg[3], tpr=cfg[4], trades=len(rec),
                        stops=int((rec[:, 6] == -1).sum()), Rm=R.sum() / months, R1=R[~late].sum(), R2=R[late].sum(),
                        gbest=g.max(), rfbest=RFS[g.argmax()], g30=g[5], g100=g[8]))
    print(sym, "done", flush=True)
    return out


# ---------------------------------------------------------------- 既定設定
def full_one(sym):
    m = prep(sym); out = []
    off, mult = grid_shape(10, *DEFAULT[1:4]); surv = off[-1] + DEFAULT[1] * DEFAULT[2] ** 10
    u = unit_loss(off, mult, surv)
    d1, _, _ = resample(m, 1440); atr = atr_sma(d1["h"], d1["l"], d1["c"], 14)
    for rf in [0.1, 0.3, 0.6, 1.0]:
        rec, dday, dbal, deq, be, ru = run(m, DEFAULT, rf, bal0=10000.0)
        s, mret = summarize(m, rec, dday, dbal, deq, be, ru, 10000.0)
        dur = (rec[:, 1] - rec[:, 0]) / 86400
        out.append(dict(sym=sym, rf=rf, **s, max_days=dur.max(),
                        need_for_001lot=u * np.nanmedian(atr) * 1e5 * 0.01 / rf,   # 決済通貨建て
                        atr_pips=np.nanmedian(atr) / pip_of(sym)))
    return out


# ---------------------------------------------------------------- 飛ぶまでの月数
def ruin_one(args):
    sym, cfg, rfs = args
    m = prep(sym); out = []
    for rf in rfs:
        for st in pd.date_range("2016-03-01", "2025-09-01", freq="6MS"):
            a = int(np.searchsorted(m["t"], int(st.timestamp())))
            rec, dday, dbal, deq, be, ru = run(m, cfg, rf, filt=False, a=a)
            me = pd.Series(dbal, index=pd.to_datetime(dday * 86400, unit="s")).resample("ME").last().dropna()
            dead = np.flatnonzero(me.values < 0.1)          # 残高が最初の10%未満 = 飛んだ
            mdead = int(dead[0]) + 1 if len(dead) else None
            mr = me.values / np.r_[1.0, me.values[:-1]] - 1
            if mdead:
                mr = mr[:mdead - 1]                          # 飛ぶ前の月だけ
            v12 = me.values[min(11, len(me) - 1)]
            out.append(dict(sym=sym, cfg=str(cfg), rf=rf, start=st, dead=mdead is not None, months_alive=mdead or len(me),
                            geo12=max(v12, 1e-9) ** (1 / 12) - 1, had50=bool((mr >= 0.5).any()),
                            hits=int((rec[:, 6] < 0).sum())))
    return out


def main():
    global DATA
    cmd, DATA, outp, *syms = sys.argv[1:]
    with Pool(min(4, len(syms))) as p:
        if cmd == "screen":
            df = pd.DataFrame(sum(p.map(screen_one, syms, chunksize=1), []))
            df["bothpos"] = (df.R1 > 0) & (df.R2 > 0)
            print("50%/月に届いた組み合わせ:", int((df.gbest >= 0.5).sum()), "/", len(df),
                  " 5%/月以上:", int((df.gbest >= 0.05).sum()), " 最大:", round(df.gbest.max() * 100, 2), "%/月")
        elif cmd == "full":
            df = pd.DataFrame(sum(p.map(full_one, syms, chunksize=1), []))
            print(df.groupby("rf")[["geo_month", "maxdd", "worst_month", "stops", "stopouts"]].agg(["median", "min", "max"]).round(4))
        elif cmd == "ruin":
            jobs = [(s, c, [0.3, 1, 3, 10, 30, 100, 300]) for s in syms for c in [DEFAULT]]
            jobs += [(s, ("always", 0.25, 1.0, 1.5, 0.5), [0.1, 0.3, 1.0, 3.0]) for s in syms]   # よくある形(約20pips・1.5倍・利確10pips)
            df = pd.DataFrame(sum(p.map(ruin_one, jobs, chunksize=1), []))
            print(df.groupby(["cfg", "rf"]).agg(dead=("dead", "mean"), alive=("months_alive", "median"), geo12=("geo12", "median"),
                                         had50=("had50", "mean"), hits=("hits", "sum")).round(3))
        else:
            raise SystemExit(__doc__)
    df.to_pickle(outp)


if __name__ == "__main__":
    main()
