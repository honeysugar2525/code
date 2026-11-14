import glob,numpy as np,pandas as pd
from ntsim import *
def load_ex(d,sym='XAUUSDm',gold=True,ym_from='2024_11',ym_to='2026_10',sigsec=900):
    # サーバー時間 = ニューヨーク時間 + 7時間 (XSのレポートと照合して確認済み)
    fs=[f for f in sorted(glob.glob(f'{d}/{sym}_*.npy')) if ym_from<=f[-11:-4]<=ym_to]
    a=np.concatenate([np.load(f) for f in fs]); a=a[np.argsort(a[:,0])]
    t=a[:,0].astype('int64'); ny=pd.to_datetime(t,unit='s',utc=True).tz_convert('America/New_York').tz_localize(None)
    b=a[:,:5].copy(); b[:,0]=ny.values.astype('datetime64[s]').astype('int64')+7*3600
    return Market(None,gold,tz='UTC',arr=b,sp=a[:,5].copy(),sigsec=sigsec),a
F=dict(MaxLevels=1,StopATR=1.5,TP_ATR=8.0,UseRSI=False,UseBreakout=False,CooldownHours=4,BE_ATR=2.0,SlopeBars=6,TrailStart_ATR=4.0,TrailDist_ATR=3.0)
E=dict(MaxLevels=2,StepATR=0.5,StepGrow=1.3,LotMult=1.5,TP_ATR=8.0,TPNanpin_ATR=2.0,StopATR=0.5,CooldownHours=12,BE_ATR=2.0,SlopeBars=6,TrailStart_ATR=6.0,TrailDist_ATR=4.0)
SWL,SWS=0.000218,-0.000047
T0=int(pd.Timestamp('2025-01-01').timestamp())
def pf(x):
    x=np.asarray(x); gp=x[x>0].sum(); gl=-x[x<=0].sum(); return gp/gl if gl>0 else 9.99
def runp(M,kw,t0=None,**o):
    P=dict(DEF); P.update(kw); d,RU,so=M.run(P,swapLong=SWL,swapShort=SWS,tstart=T0 if t0 is None else t0,maxSpreadATR=0.15,**o)
    d['tin']=pd.to_datetime(d.tin,unit='s'); d['tout']=pd.to_datetime(d.tout,unit='s'); return d
