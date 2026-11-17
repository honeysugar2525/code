"""Exness が公開しているティック履歴を落として、1分足(+スプレッド)に変換する。

使い方: python3 sim/fx_fetch.py 出力フォルダ 2016_01 2026_10 EURUSDm USDJPYm ...
  出力: 出力フォルダ/{通貨ペア}_{年}_{月}.npy
  列: 0=時刻(UTC, 秒) 1-4=Bid の始値/高値/安値/終値 5=平均スプレッド 6=最大スプレッド
      7=Ask 高値 8=Ask 安値 9=ティック数
"""
import io, os, sys, time, zipfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np, polars as pl

URL = "https://ticks.ex2archive.com/ticks/{s}/{y}/{m:02d}/Exness_{s}_{y}_{m:02d}.zip"


def months(a, b):
    y, m = map(int, a.split("_")); y2, m2 = map(int, b.split("_"))
    while (y, m) <= (y2, m2):
        yield y, m
        m += 1
        if m > 12: y, m = y + 1, 1


def convert(raw: bytes) -> np.ndarray:
    z = zipfile.ZipFile(io.BytesIO(raw))
    csv = z.read(z.namelist()[0])
    df = pl.read_csv(io.BytesIO(csv), columns=["Timestamp", "Bid", "Ask"],
                     schema_overrides={"Timestamp": pl.Utf8, "Bid": pl.Float64, "Ask": pl.Float64})
    df = df.with_columns(
        pl.col("Timestamp").str.slice(0, 16).str.strptime(pl.Datetime("ms"), "%Y-%m-%d %H:%M").alias("k"),
        (pl.col("Ask") - pl.col("Bid")).alias("sp"))
    g = (df.group_by("k", maintain_order=True)
           .agg(o=pl.col("Bid").first(), h=pl.col("Bid").max(), l=pl.col("Bid").min(), c=pl.col("Bid").last(),
                sp=pl.col("sp").mean(), spmax=pl.col("sp").max(), ah=pl.col("Ask").max(), al=pl.col("Ask").min(),
                n=pl.len())
           .sort("k"))
    t = g["k"].dt.epoch("s").to_numpy().astype("float64")
    cols = [g[c].to_numpy().astype("float64") for c in ("o", "h", "l", "c", "sp", "spmax", "ah", "al", "n")]
    return np.column_stack([t] + cols)


def job(out, s, y, m):
    fn = f"{out}/{s}_{y}_{m:02d}.npy"
    if os.path.exists(fn):
        return fn, "skip"
    for k in range(5):
        try:
            with urllib.request.urlopen(URL.format(s=s, y=y, m=m), timeout=120) as r:
                raw = r.read()
            a = convert(raw)
            np.save(fn + ".tmp.npy", a); os.replace(fn + ".tmp.npy", fn)
            return fn, f"{len(a)} bars"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return fn, "404"
            time.sleep(2 ** k)
        except Exception as e:  # 通信の切断など
            time.sleep(2 ** k); err = e
    return fn, f"FAILED {err!r}"


def main():
    out, a, b, *syms = sys.argv[1:]
    os.makedirs(out, exist_ok=True)
    jobs = [(out, s, y, m) for s in syms for (y, m) in months(a, b)]
    with ThreadPoolExecutor(4) as ex:
        for fn, msg in ex.map(lambda j: job(*j), jobs):
            print(os.path.basename(fn), msg, flush=True)


if __name__ == "__main__":
    main()
