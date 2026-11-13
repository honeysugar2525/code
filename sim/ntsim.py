# NanpinTrio.mq5 と同じロジックを 1 分足で再現するシミュレーター
import numpy as np, pandas as pd
from numba import njit

DEF=dict(RSI_Period=14,RSI_BuyLow=23.,RSI_BuyHigh=30.,RSI_SellLow=70.,RSI_SellHigh=80.,RSI_OnEnterOnly=True,
         UseRSI=True,UseCross=True,UseBreakout=True,MA_Fast=25,MA_Slow=75,
         BO_Lookback=120,BO_Pivot=3,BO_MinTouches=2,BO_ZoneATR=0.5,BO_BufferATR=0.1,
         TrendFilter=1,TrendMAPeriod=200,
         MaxLevels=6,GridATRPeriod=14,StepATR=1.0,StepGrow=1.3,LotMult=1.5,NanpinMinBars=1,
         TP_ATR=0.6,TPNanpin_ATR=0.35,StopATR=2.0,CooldownHours=12.,OneSideOnly=True,
         UseTimeFilter=True,NoEntryFromHour=23,NoEntryToHour=2,FridayStopHour=20)

@njit(cache=True)
def rsi_wilder(c,n):
    N=len(c); out=np.full(N,np.nan); ag=0.0; al=0.0
    for i in range(1,N):
        d=c[i]-c[i-1]; g=d if d>0 else 0.0; l=-d if d<0 else 0.0
        if i<=n:
            ag+=g; al+=l
            if i==n:
                ag/=n; al/=n
                out[i]=100.0 if al==0 else 100.0-100.0/(1.0+ag/al)
        else:
            ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n
            out[i]=100.0 if al==0 else 100.0-100.0/(1.0+ag/al)
    return out

def sma(x,n): return pd.Series(x).rolling(n).mean().values
def ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().values
def atr_sma(h,l,c,n):
    pc=np.roll(c,1); pc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    return sma(tr,n)

@njit(cache=True)
def zones(h,l,c,atr,Lookback,Pivot,MinT,ZoneATR,BufATR):
    N=len(c); bb=np.zeros(N,np.bool_); bs=np.zeros(N,np.bool_)
    ph=np.zeros(Lookback+Pivot+5); pl=np.zeros(Lookback+Pivot+5)
    want=Lookback+Pivot+2
    for j in range(3,N):               # j = これから始まる足(MQLの index 0)
        got=min(want,j+1)
        a=atr[j-1]
        if got<Pivot*2+10 or not (a>0): continue
        tol=ZoneATR*a; buf=BufATR*a; c1=c[j-1]; c2=c[j-2]
        nh=0; nl=0; last=got-1-Pivot
        for i in range(Pivot+2,last+1):
            x=j-i; isH=True; isL=True
            for k in range(1,Pivot+1):
                if h[x]<h[x+k] or h[x]<=h[x-k]: isH=False
                if l[x]>l[x+k] or l[x]>=l[x-k]: isL=False
                if not isH and not isL: break
            if isH:
                br=False
                for q in range(i-1,1,-1):
                    if c[j-q]>h[x]: br=True; break
                if not br: ph[nh]=h[x]; nh+=1
            if isL:
                br=False
                for q in range(i-1,1,-1):
                    if c[j-q]<l[x]: br=True; break
                if not br: pl[nl]=l[x]; nl+=1
        for a1 in range(nh):
            t=0; top=ph[a1]
            for q in range(nh):
                if abs(ph[q]-ph[a1])<=tol:
                    t+=1
                    if ph[q]>top: top=ph[q]
            if t>=MinT and c2<=top and c1>top+buf: bb[j]=True; break
        for a1 in range(nl):
            t=0; bot=pl[a1]
            for q in range(nl):
                if abs(pl[q]-pl[a1])<=tol:
                    t+=1
                    if pl[q]<bot: bot=pl[q]
            if t>=MinT and c2>=bot and c1<bot-buf: bs[j]=True; break
    return bb,bs

@njit(cache=True)
def simulate(mt,mo,mh,ml,mc,first15,sigB,sigS,atrH,okEntry,spreadFrac,swapLong,swapShort,
             MaxLevels,StepATR,StepGrow,LotMult,TP_ATR,TPN_ATR,StopATR,cooldownSec,minAddSec,oneSide):
    N=len(mt)
    off=np.zeros(MaxLevels); lotf=np.zeros(MaxLevels)
    for k in range(MaxLevels):
        s=0.0
        for i in range(k): s+=StepATR*StepGrow**i
        off[k]=s; lotf[k]=LotMult**k
    stopOff=off[MaxLevels-1]+StopATR
    RU=0.0
    for k in range(MaxLevels): RU+=lotf[k]*(stopOff-off[k])
    rec=np.zeros((300000,10)); nr=0
    n=np.zeros(2,np.int64); lots=np.zeros(2); cost=np.zeros(2); first=np.zeros(2); atrb=np.zeros(2)
    lastAdd=np.zeros(2,np.int64); tin=np.zeros(2,np.int64); tag=np.zeros(2,np.int64); swp=np.zeros(2); minF=np.zeros(2)
    cool=0; prevDay=mt[0]//86400
    pts=np.zeros(4)
    for k in range(N):
        t=mt[k]; o=mo[k]; h=mh[k]; l=ml[k]; c=mc[k]; sp=spreadFrac*o
        day=t//86400
        if day!=prevDay:
            nights=3.0 if (day+3)%7==3 else 1.0
            if n[0]>0: swp[0]+=lots[0]*swapLong*o*nights
            if n[1]>0: swp[1]+=lots[1]*swapShort*o*nights
            prevDay=day
        j=first15[k]
        if j>=0 and t>=cool and okEntry[j] and atrH[j]>0:
            if sigB[j]>0 and n[0]==0 and (not oneSide or n[1]==0):
                n[0]=1; lots[0]=1.0; cost[0]=o+sp; first[0]=o+sp; atrb[0]=atrH[j]; lastAdd[0]=t; tin[0]=t; tag[0]=sigB[j]; swp[0]=0.0; minF[0]=0.0
            elif sigS[j]>0 and n[1]==0 and (not oneSide or n[0]==0):
                n[1]=1; lots[1]=1.0; cost[1]=o; first[1]=o; atrb[1]=atrH[j]; lastAdd[1]=t; tin[1]=t; tag[1]=sigS[j]; swp[1]=0.0; minF[1]=0.0
        if n[0]==0 and n[1]==0: continue
        if c>=o: pts[0]=o; pts[1]=l; pts[2]=h; pts[3]=c
        else:    pts[0]=o; pts[1]=h; pts[2]=l; pts[3]=c
        for g in range(3):
            p0=pts[g]; p1=pts[g+1]
            # ---- 買いバスケット
            if n[0]>0:
                ex=0.0; et=0
                if p1<p0:
                    while n[0]<MaxLevels:
                        lvl=first[0]-atrb[0]*off[n[0]]
                        if p1<=lvl-sp and t-lastAdd[0]>=minAddSec:
                            fa=min(lvl,p0+sp); cost[0]+=lotf[n[0]]*fa; lots[0]+=lotf[n[0]]; n[0]+=1; lastAdd[0]=t
                            if minAddSec>0: break
                        else: break
                    stop=first[0]-atrb[0]*stopOff
                    if p1<=stop: ex=min(stop,p0); et=-1
                    else:
                        f=(lots[0]*p1-cost[0]-swp[0])/(atrb[0]*RU)
                        if f<minF[0]: minF[0]=f
                elif p1>p0:
                    tp=cost[0]/lots[0]+atrb[0]*(TP_ATR if n[0]<=1 else TPN_ATR)
                    if p1>=tp: ex=max(tp,p0); et=1
                if et!=0:
                    pnl=lots[0]*ex-cost[0]-swp[0]
                    rec[nr,0]=tin[0]; rec[nr,1]=t; rec[nr,2]=1; rec[nr,3]=tag[0]; rec[nr,4]=n[0]; rec[nr,5]=pnl/(atrb[0]*RU)
                    rec[nr,6]=atrb[0]; rec[nr,7]=first[0]; rec[nr,8]=et; rec[nr,9]=min(minF[0],rec[nr,5]); nr+=1
                    n[0]=0
                    if et<0: cool=t+cooldownSec
            # ---- 売りバスケット
            if n[1]>0:
                ex=0.0; et=0
                if p1>p0:
                    while n[1]<MaxLevels:
                        lvl=first[1]+atrb[1]*off[n[1]]
                        if p1>=lvl and t-lastAdd[1]>=minAddSec:
                            fb=max(lvl,p0); cost[1]+=lotf[n[1]]*fb; lots[1]+=lotf[n[1]]; n[1]+=1; lastAdd[1]=t
                            if minAddSec>0: break
                        else: break
                    stop=first[1]+atrb[1]*stopOff
                    if p1+sp>=stop: ex=max(stop,p0+sp); et=-1
                    else:
                        f=(cost[1]-lots[1]*(p1+sp)-swp[1])/(atrb[1]*RU)
                        if f<minF[1]: minF[1]=f
                elif p1<p0:
                    tp=cost[1]/lots[1]-atrb[1]*(TP_ATR if n[1]<=1 else TPN_ATR)
                    if p1+sp<=tp: ex=min(tp,p0+sp); et=1
                if et!=0:
                    pnl=cost[1]-lots[1]*ex-swp[1]
                    rec[nr,0]=tin[1]; rec[nr,1]=t; rec[nr,2]=-1; rec[nr,3]=tag[1]; rec[nr,4]=n[1]; rec[nr,5]=pnl/(atrb[1]*RU)
                    rec[nr,6]=atrb[1]; rec[nr,7]=first[1]; rec[nr,8]=et; rec[nr,9]=min(minF[1],rec[nr,5]); nr+=1
                    n[1]=0
                    if et<0: cool=t+cooldownSec
    return rec[:nr],RU,stopOff

class Market:
    def __init__(self,path,gold):
        a=np.load(path); t=a[:,0].astype('int64')
        srv=pd.to_datetime(t,unit='s',utc=True).tz_convert('Europe/Athens').tz_localize(None)   # サーバー時間(GMT+2/+3)
        ts=srv.values.astype('datetime64[s]').astype('int64')
        keep=np.ones(len(t),bool)
        if gold: keep=srv.weekday.values<5       # 金は土日を除く
        self.gold=gold
        self.mt=ts[keep]; self.mo=a[keep,1]; self.mh=a[keep,2]; self.ml=a[keep,3]; self.mc=a[keep,4]
        df=pd.DataFrame(dict(t=self.mt,o=self.mo,h=self.mh,l=self.ml,c=self.mc))
        def agg(sec):
            g=df.groupby(df.t//sec)
            r=pd.DataFrame(dict(t=g.t.first()//sec*sec,o=g.o.first(),h=g.h.max(),l=g.l.min(),c=g.c.last(),i0=g.apply(lambda x:x.index[0],include_groups=False)))
            return r.reset_index(drop=True)
        self.b15=agg(900); self.b60=agg(3600)
        self.first15=np.full(len(self.mt),-1,np.int64); self.first15[self.b15.i0.values]=np.arange(len(self.b15))
        # 各M15足の開始時点で確定済みの最後のH1足
        self.h1idx=np.searchsorted(self.b60.t.values+3600,self.b15.t.values,side='right')-1
        self._z={}; self._atr15=atr_sma(self.b15.h.values,self.b15.l.values,self.b15.c.values,14)
    def signals(self,P):
        b=self.b15; c=b.c.values; N=len(c)
        r=rsi_wilder(c,P['RSI_Period']); f=sma(c,P['MA_Fast']); s=sma(c,P['MA_Slow'])
        sh=lambda x,k: np.concatenate([np.full(k,np.nan),x[:-k]])
        r1,r2,f1,f2,s1,s2,c1=sh(r,1),sh(r,2),sh(f,1),sh(f,2),sh(s,1),sh(s,2),sh(c,1)
        inB1=(r1>=P['RSI_BuyLow'])&(r1<=P['RSI_BuyHigh']); inB2=(r2>=P['RSI_BuyLow'])&(r2<=P['RSI_BuyHigh'])
        inS1=(r1>=P['RSI_SellLow'])&(r1<=P['RSI_SellHigh']); inS2=(r2>=P['RSI_SellLow'])&(r2<=P['RSI_SellHigh'])
        en=P['RSI_OnEnterOnly']
        rb=inB1&(~inB2 if en else True)&P['UseRSI']; rs=inS1&(~inS2 if en else True)&P['UseRSI']
        cb=(f2<=s2)&(f1>s1)&P['UseCross']; cs=(f2>=s2)&(f1<s1)&P['UseCross']
        zk=(P['BO_Lookback'],P['BO_Pivot'],P['BO_MinTouches'],P['BO_ZoneATR'],P['BO_BufferATR'])
        if zk not in self._z: self._z[zk]=zones(b.h.values,b.l.values,c,self._atr15,*zk)
        bb,bs=self._z[zk]; bb=bb&P['UseBreakout']; bs=bs&P['UseBreakout']
        tb=rb*1+cb*2+bb*4; tsl=rs*1+cs*2+bs*4
        hb=self.b60; e=ema(hb.c.values,P['TrendMAPeriod']); a=atr_sma(hb.h.values,hb.l.values,hb.c.values,P['GridATRPeriod'])
        ok=self.h1idx>=max(P['TrendMAPeriod'],P['GridATRPeriod'])
        hi=np.clip(self.h1idx,0,None); eJ=e[hi]; aJ=np.where(ok,a[hi],0.0)
        if P['TrendFilter']==1:
            tb=np.where(c1>eJ,tb,0); tsl=np.where(c1<eJ,tsl,0)
        both=(tb>0)&(tsl>0); tb=np.where(both,0,tb); tsl=np.where(both,0,tsl)
        okE=np.ones(N,bool)
        if self.gold:
            hr=(b.t.values%86400)//3600; wd=((b.t.values//86400)+3)%7
            if P['UseTimeFilter'] and P['NoEntryFromHour']!=P['NoEntryToHour']:
                A,B=P['NoEntryFromHour'],P['NoEntryToHour']
                okE&=~(((hr>=A)&(hr<B)) if A<B else ((hr>=A)|(hr<B)))
            if P['FridayStopHour']<24: okE&=~((wd==4)&(hr>=P['FridayStopHour']))
        return tb.astype('int64'),tsl.astype('int64'),np.nan_to_num(aJ),okE
    def run(self,P,spreadFrac,swapLong=0.0,swapShort=0.0):
        tb,tsl,aJ,okE=self.signals(P)
        rec,RU,stopOff=simulate(self.mt,self.mo,self.mh,self.ml,self.mc,self.first15,tb,tsl,aJ,okE,spreadFrac,swapLong,swapShort,
            P['MaxLevels'],P['StepATR'],P['StepGrow'],P['LotMult'],P['TP_ATR'],P['TPNanpin_ATR'],P['StopATR'],
            int(P['CooldownHours']*3600),int(900*P['NanpinMinBars']),P['OneSideOnly'])
        d=pd.DataFrame(rec,columns=['tin','tout','dir','tag','n','R','atr','first','exit','minF'])
        return d,RU,stopOff

def stats(d,p=0.30,label=''):
    if len(d)==0: return dict(label=label,n=0)
    R=d.R.values; m=pd.to_datetime(d.tout,unit='s').dt.to_period('M')
    gp=R[R>0].sum(); gl=-R[R<=0].sum()
    eq=np.cumprod(1+p*R); pk=np.maximum.accumulate(np.concatenate([[1],eq]))[1:]
    flo=np.concatenate([[1],eq[:-1]])*(1+p*d.minF.values); pk0=np.maximum.accumulate(np.concatenate([[1],eq[:-1]]))
    dd=max(((pk-eq)/pk).max(),((pk0-flo)/pk0).max())
    mon=pd.Series(np.log1p(p*R)).groupby(m.values).sum(); nm=len(pd.period_range(m.min(),m.max(),freq='M'))
    mret=np.expm1(mon.reindex(pd.period_range(m.min(),m.max(),freq='M'),fill_value=0))
    return dict(label=label,n=len(d),win=round((R>0).mean()*100,1),SL=int((d.exit<0).sum()),PF=round(gp/gl,2) if gl>0 else 99,
                sumR=round(R.sum(),2),avgLv=round(d.n.mean(),2),monMed=round(mret.median()*100,1),monAvgGeo=round(np.expm1(np.log(eq[-1])/nm)*100,1),
                monMin=round(mret.min()*100,1),negMon=int((mret<0).sum()),nMon=nm,DD=round(dd*100,1),final=round(eq[-1],2))
