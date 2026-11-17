"""NanpinTrio.mq5 から、既定値を書き換えただけの派生EAを作る。
設定ファイルを読み込まなくても、チャートに載せるだけで動くようにするためのもの。
使い方: python3 tools/make_variants.py
"""
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "NanpinTrio.mq5"

NANPIN = dict(MaxLevels="2", StepPrice="3.5", StepGrow="1.3", LotMult="1.0", TPNanpin_ATR="8.0")
VARIANTS = {
    "NanpinTrio_Slow_Nanpin.mq5": dict(
        title="遅い設定・ナンピン1回あり",
        values=dict(NANPIN, MagicNumber="20261113", MA_Fast="75", MA_Slow="225", StopATR="2.0",
                    BE_ATR="3.0", TrailStart_ATR="0.0", TrailDist_ATR="3.0", MinDailyATRpct="0.0"),
    ),
    "NanpinTrio_Fast_Nanpin.mq5": dict(
        title="速い設定・ナンピン1回あり",
        values=dict(NANPIN, MagicNumber="20261114", MA_Fast="25", MA_Slow="75", StopATR="1.0",
                    BE_ATR="2.0", TrailStart_ATR="4.0", TrailDist_ATR="3.0", MinDailyATRpct="1.6"),
    ),
}

def build(text, title, values):
    for name, val in values.items():
        pat = re.compile(r"^(input\s+\S+\s+" + re.escape(name) + r"\s*=\s*)([^;]+)(;)", re.M)
        text, n = pat.subn(lambda m: m.group(1) + val + m.group(3), text)
        if n != 1:
            raise SystemExit(f"{name}: {n} 件ヒット (1件のはず)")
    old = 'string txt="NanpinTrio  "+_Symbol'
    if text.count(old) != 1:
        raise SystemExit("パネルの見出しが見つからない")
    text = text.replace(old, f'string txt="NanpinTrio [{title}]  "+_Symbol')
    old = '#property description "ヘッジ口座専用。テスターは「全ティック(リアルティック)」で検証してください。"'
    if text.count(old) != 1:
        raise SystemExit("description が見つからない")
    return text.replace(old, f'#property description "【{title}】設定を変えずにそのまま金のチャートに載せて使う版。ヘッジ口座専用。"')

def main():
    src = SRC.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    for fname, v in VARIANTS.items():
        out = build(src, v["title"], v["values"])
        (ROOT / fname).write_text(out.replace("\n", "\r\n"), encoding="utf-8-sig", newline="")
        print("wrote", fname)

if __name__ == "__main__":
    main()
