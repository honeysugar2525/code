# NanpinTrio.mq5 と同じロジックを 1 分足で再現するシミュレーター
import numpy as np, pandas as pd
from numba import njit

DEF=dict(RSI_Period=14,RSI_BuyLow=23.,RSI_BuyHigh=30.,RSI_SellLow=70.,RSI_SellHigh=80.,RSI_OnEnterOnly=True,
         UseRSI=True,UseCross=True,UseBreakout=True,MA_Fast=25,MA_Slow=75,
         BO_Lookback=120,BO_Pivot=3,BO_MinTouches=2,BO_ZoneATR=0.5,BO_BufferATR=0.1,
         TrendFilter=1,TrendMAPeriod=200,
         MaxLevels=6,GridATRPeriod=14,StepATR=1.0,StepGrow=1.3,LotMult=1.5,NanpinMinBars=1,
         TP_ATR=0.6,TPNanpin_ATR=0.35,StopATR=2.0,CooldownHours=12.,OneSideOnly=True,
         UseTimeFilter=True,NoEntryFromHour=23,NoEntryToHour=2,FridayStopHour=20,
         ADX_Min=0.,ADX_Period=14,SlopeBars=0,H4MAPeriod=0,D1MAPeriod=0,VolRatioMin=0.,VolRatioMax=0.,VolLong=100,
         HourFrom=-1,HourTo=-1,MaxExtATR=0.,MinExtATR=0.,MinSignals=1,ConfluenceBars=8,NeedBarDir=False,
         BE_ATR=0.,TrailStart_ATR=0.,TrailDist_ATR=0.,CooldownOnLossOnly=True,
         MA_EMA=False,UsePullback=False,PyrATR=0.,PyrLot=1.,PyrMax=0,PyrStopATR=1.5,Dir=0,D1VolMin=0.,D1VolMax=0.,
         CrossAngleATR=0.,PriceBeyond=False,H4RSIMin=0.,SkipDow=-1,D1CandleDir=False,SlowSlopeBars=0,MinSepBars=0,D1RSIMin=0.)

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
def adx_wilder(h,l,c,n):
    N=len(c); out=np.full(N,np.nan); trs=0.0; pds=0.0; mds=0.0; dxs=0.0; adx=0.0; cnt=0
    for i in range(1,N):
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        pdm=up if (up>dn and up>0) else 0.0; mdm=dn if (dn>up and dn>0) else 0.0
        tr=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        if i<=n:
            trs+=tr; pds+=pdm; mds+=mdm
            if i<n: continue
        else:
            trs=trs-trs/n+tr; pds=pds-pds/n+pdm; mds=mds-mds/n+mdm
        if trs<=0: continue
        pdi=100*pds/trs; mdi=100*mds/trs; den=pdi+mdi
        dx=100*abs(pdi-mdi)/den if den>0 else 0.0
        cnt+=1
        if cnt<=n:
            dxs+=dx
            if cnt==n: adx=dxs/n; out[i]=adx
        else:
            adx=(adx*(n-1)+dx)/n; out[i]=adx
    return out

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
def simulate(mt,mo,mh,ml,mc,msp,first15,sigB,sigS,atrH,okEntry,maxSpreadATR,tstart,swapLong,swapShort,
             MaxLevels,StepATR,StepGrow,LotMult,TP_ATR,TPN_ATR,StopATR,cooldownSec,minAddSec,oneSide,BE_ATR,TrailStart,TrailDist,PyrATR,PyrLot,PyrMax,PyrStop):
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
    lastAdd=np.zeros(2,np.int64); tin=np.zeros(2,np.int64); tag=np.zeros(2,np.int64); swp=np.zeros(2); minF=np.zeros(2); dyn=np.zeros(2); npyr=np.zeros(2,np.int64)
    cool=0; prevDay=mt[0]//86400
    pts=np.zeros(4)
    for k in range(N):
        t=mt[k]; o=mo[k]; h=mh[k]; l=ml[k]; c=mc[k]; sp=msp[k]
        day=t//86400
        if day!=prevDay:
            nights=3.0 if (day+3)%7==3 else 1.0
            if n[0]>0: swp[0]+=lots[0]*swapLong*o*nights
            if n[1]>0: swp[1]+=lots[1]*swapShort*o*nights
            prevDay=day
        j=first15[k]
        if j>=0 and t>=cool and t>=tstart and okEntry[j] and atrH[j]>0 and (maxSpreadATR<=0 or sp<=maxSpreadATR*atrH[j]):
            if sigB[j]>0 and n[0]==0 and (not oneSide or n[1]==0):
                n[0]=1; lots[0]=1.0; cost[0]=o+sp; first[0]=o+sp; atrb[0]=atrH[j]; lastAdd[0]=t; tin[0]=t; tag[0]=sigB[j]; swp[0]=0.0; minF[0]=0.0; dyn[0]=o+sp-atrH[j]*stopOff; npyr[0]=0
            elif sigS[j]>0 and n[1]==0 and (not oneSide or n[0]==0):
                n[1]=1; lots[1]=1.0; cost[1]=o; first[1]=o; atrb[1]=atrH[j]; lastAdd[1]=t; tin[1]=t; tag[1]=sigS[j]; swp[1]=0.0; minF[1]=0.0; dyn[1]=o+atrH[j]*stopOff; npyr[1]=0
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
                        if p1<=lvl-sp and t-lastAdd[0]>=minAddSec and (maxSpreadATR<=0 or sp<=maxSpreadATR*atrb[0]):
                            fa=min(lvl,p0+sp); cost[0]+=lotf[n[0]]*fa; lots[0]+=lotf[n[0]]; n[0]+=1; lastAdd[0]=t
                            if minAddSec>0: break
                        else: break
                    stop=dyn[0]
                    if p1<=stop: ex=min(stop,p0); et=-1
                    else:
                        f=(lots[0]*p1-cost[0]-swp[0])/(atrb[0]*RU)
                        if f<minF[0]: minF[0]=f
                elif p1>p0:
                    # 増し玉(含み益方向に買い増し)
                    while npyr[0]<PyrMax and n[0]==1:
                        trig=first[0]+PyrATR*(npyr[0]+1)*atrb[0]
                        if p1+sp>=trig:
                            fa=max(trig,p0+sp); cost[0]+=PyrLot*fa; lots[0]+=PyrLot; npyr[0]+=1
                            ns=fa-sp-PyrStop*atrb[0]
                            if ns>dyn[0]: dyn[0]=ns
                        else: break
                    if npyr[0]>0: tp=first[0]+atrb[0]*TP_ATR
                    else: tp=cost[0]/lots[0]+atrb[0]*(TP_ATR if n[0]<=1 else TPN_ATR)
                    if p1>=tp: ex=max(tp,p0); et=1
                    else:
                        avg=cost[0]/lots[0]
                        if BE_ATR>0 and p1-avg>=BE_ATR*atrb[0] and avg>dyn[0]: dyn[0]=avg
                        if TrailStart>0 and p1-avg>=TrailStart*atrb[0] and p1-TrailDist*atrb[0]>=dyn[0]+0.1*atrb[0]: dyn[0]=p1-TrailDist*atrb[0]
                if et!=0:
                    pnl=lots[0]*ex-cost[0]-swp[0]
                    rec[nr,0]=tin[0]; rec[nr,1]=t; rec[nr,2]=1; rec[nr,3]=tag[0]; rec[nr,4]=n[0]; rec[nr,5]=pnl/(atrb[0]*RU)
                    rec[nr,6]=atrb[0]; rec[nr,7]=first[0]; rec[nr,8]=et; rec[nr,9]=min(minF[0],rec[nr,5]); nr+=1
                    n[0]=0
                    if et<0 and dyn[0]<=first[0]-atrb[0]*stopOff+1e-9: cool=t+cooldownSec   # 初期の損切りの時だけ休む
            # ---- 売りバスケット
            if n[1]>0:
                ex=0.0; et=0
                if p1>p0:
                    while n[1]<MaxLevels:
                        lvl=first[1]+atrb[1]*off[n[1]]
                        if p1>=lvl and t-lastAdd[1]>=minAddSec and (maxSpreadATR<=0 or sp<=maxSpreadATR*atrb[1]):
                            fb=max(lvl,p0); cost[1]+=lotf[n[1]]*fb; lots[1]+=lotf[n[1]]; n[1]+=1; lastAdd[1]=t
                            if minAddSec>0: break
                        else: break
                    stop=dyn[1]
                    if p1+sp>=stop: ex=max(stop,p0+sp); et=-1
                    else:
                        f=(cost[1]-lots[1]*(p1+sp)-swp[1])/(atrb[1]*RU)
                        if f<minF[1]: minF[1]=f
                elif p1<p0:
                    while npyr[1]<PyrMax and n[1]==1:
                        trig=first[1]-PyrATR*(npyr[1]+1)*atrb[1]
                        if p1<=trig:
                            fb=min(trig,p0); cost[1]+=PyrLot*fb; lots[1]+=PyrLot; npyr[1]+=1
                            ns=fb+sp+PyrStop*atrb[1]
                            if ns<dyn[1]: dyn[1]=ns
                        else: break
                    if npyr[1]>0: tp=first[1]-atrb[1]*TP_ATR
                    else: tp=cost[1]/lots[1]-atrb[1]*(TP_ATR if n[1]<=1 else TPN_ATR)
                    if p1+sp<=tp: ex=min(tp,p0+sp); et=1
                    else:
                        avg=cost[1]/lots[1]; a1=p1+sp
                        if BE_ATR>0 and avg-a1>=BE_ATR*atrb[1] and avg<dyn[1]: dyn[1]=avg
                        if TrailStart>0 and avg-a1>=TrailStart*atrb[1] and a1+TrailDist*atrb[1]<=dyn[1]-0.1*atrb[1]: dyn[1]=a1+TrailDist*atrb[1]
                if et!=0:
                    pnl=cost[1]-lots[1]*ex-swp[1]
                    rec[nr,0]=tin[1]; rec[nr,1]=t; rec[nr,2]=-1; rec[nr,3]=tag[1]; rec[nr,4]=n[1]; rec[nr,5]=pnl/(atrb[1]*RU)
                    rec[nr,6]=atrb[1]; rec[nr,7]=first[1]; rec[nr,8]=et; rec[nr,9]=min(minF[1],rec[nr,5]); nr+=1
                    n[1]=0
                    if et<0 and dyn[1]>=first[1]+atrb[1]*stopOff-1e-9: cool=t+cooldownSec
    return rec[:nr],RU,stopOff

class Market:
    def __init__(self,path,gold,tz='Europe/Athens',arr=None,sp=None,sigsec=900):
        a=np.load(path) if arr is None else arr; t=a[:,0].astype('int64')
        srv=pd.to_datetime(t,unit='s',utc=True).tz_convert(tz).tz_localize(None)   # サーバー時間(GMT+2/+3)
        ts=srv.values.astype('datetime64[s]').astype('int64')
        keep=np.ones(len(t),bool)
        if gold: keep=srv.weekday.values<5       # 金は土日を除く
        self.gold=gold
        self.mt=ts[keep]; self.mo=a[keep,1]; self.mh=a[keep,2]; self.ml=a[keep,3]; self.mc=a[keep,4]
        self.msp=None if sp is None else sp[keep]
        df=pd.DataFrame(dict(t=self.mt,o=self.mo,h=self.mh,l=self.ml,c=self.mc))
        def agg(sec):
            g=df.groupby(df.t//sec)
            r=pd.DataFrame(dict(t=g.t.first()//sec*sec,o=g.o.first(),h=g.h.max(),l=g.l.min(),c=g.c.last(),i0=g.apply(lambda x:x.index[0],include_groups=False)))
            return r.reset_index(drop=True)
        self.sigsec=sigsec; self.b15=agg(sigsec); self.b60=agg(3600); self.b240=agg(14400); self.bD=agg(86400)
        self.h4idx=None
        self.first15=np.full(len(self.mt),-1,np.int64); self.first15[self.b15.i0.values]=np.arange(len(self.b15))
        # 各M15足の開始時点で確定済みの最後のH1足
        self.h1idx=np.searchsorted(self.b60.t.values+3600,self.b15.t.values,side='right')-1
        self.h4idx=np.searchsorted(self.b240.t.values+14400,self.b15.t.values,side='right')-1
        self.didx=np.searchsorted(self.bD.t.values+86400,self.b15.t.values,side='right')-1
        self._z={}; self._atr15=atr_sma(self.b15.h.values,self.b15.l.values,self.b15.c.values,14)
    def signals(self,P):
        b=self.b15; c=b.c.values; N=len(c)
        r=rsi_wilder(c,P['RSI_Period']); mf=ema if P['MA_EMA'] else sma; f=mf(c,P['MA_Fast']); s=mf(c,P['MA_Slow'])
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
        c2=sh(c,2)
        pbb=(f1>s1)&(c2<f2)&(c1>f1)&P['UsePullback']; pbs=(f1<s1)&(c2>f2)&(c1<f1)&P['UsePullback']
        tb=rb*1+cb*2+bb*4+pbb*8; tsl=rs*1+cs*2+bs*4+pbs*8
        if P['MinSignals']>1:
            W=P['ConfluenceBars']; roll=lambda x: pd.Series(x.astype(float)).rolling(W,min_periods=1).max().values
            nb=roll(rb)+roll(cb)+roll(bb); ns=roll(rs)+roll(cs)+roll(bs)
            tb=np.where(nb>=P['MinSignals'],tb,0); tsl=np.where(ns>=P['MinSignals'],tsl,0)
        if P['NeedBarDir']:
            o1=sh(b.o.values,1); tb=np.where(c1>o1,tb,0); tsl=np.where(c1<o1,tsl,0)
        hb=self.b60; e=ema(hb.c.values,P['TrendMAPeriod']); a=atr_sma(hb.h.values,hb.l.values,hb.c.values,P['GridATRPeriod'])
        ok=self.h1idx>=max(P['TrendMAPeriod'],P['GridATRPeriod'])
        hi=np.clip(self.h1idx,0,None); eJ=e[hi]; aJ=np.where(ok,a[hi],0.0)
        if P['TrendFilter']==1:
            tb=np.where(c1>eJ,tb,0); tsl=np.where(c1<eJ,tsl,0)
        hh,hl,hc=hb.h.values,hb.l.values,hb.c.values
        if P['ADX_Min']>0:
            ad=adx_wilder(hh,hl,hc,P['ADX_Period'])[hi]; m=np.nan_to_num(ad)>=P['ADX_Min']; tb=np.where(m,tb,0); tsl=np.where(m,tsl,0)
        if P['SlopeBars']>0:
            ep=e[np.clip(hi-P['SlopeBars'],0,None)]; tb=np.where(eJ>ep,tb,0); tsl=np.where(eJ<ep,tsl,0)
        if P['H4MAPeriod']>0:
            e4=ema(self.b240.c.values,P['H4MAPeriod'])[np.clip(self.h4idx,0,None)]; ok4=self.h4idx>=P['H4MAPeriod']
            tb=np.where(ok4&(c1>e4),tb,0); tsl=np.where(ok4&(c1<e4),tsl,0)
        if P['D1MAPeriod']>0:
            eD=ema(self.bD.c.values,P['D1MAPeriod'])[np.clip(self.didx,0,None)]; okD=self.didx>=P['D1MAPeriod']
            tb=np.where(okD&(c1>eD),tb,0); tsl=np.where(okD&(c1<eD),tsl,0)
        if P['VolRatioMin']>0 or P['VolRatioMax']>0:
            al=atr_sma(hh,hl,hc,P['VolLong'])[hi]; vr=np.nan_to_num(a[hi]/al)
            m=np.ones(N,bool)
            if P['VolRatioMin']>0: m&=vr>=P['VolRatioMin']
            if P['VolRatioMax']>0: m&=vr<=P['VolRatioMax']
            tb=np.where(m,tb,0); tsl=np.where(m,tsl,0)
        if P['MaxExtATR']>0 or P['MinExtATR']>0:
            ext=np.nan_to_num((c1-eJ)/np.where(aJ>0,aJ,np.nan))
            if P['MaxExtATR']>0: tb=np.where(ext<=P['MaxExtATR'],tb,0); tsl=np.where(-ext<=P['MaxExtATR'],tsl,0)
            if P['MinExtATR']>0: tb=np.where(ext>=P['MinExtATR'],tb,0); tsl=np.where(-ext>=P['MinExtATR'],tsl,0)
        both=(tb>0)&(tsl>0); tb=np.where(both,0,tb); tsl=np.where(both,0,tsl)
        if P['D1VolMin']>0 or P['D1VolMax']>0:
            Dd=self.bD; dv=atr_sma(Dd.h.values,Dd.l.values,Dd.c.values,14)/Dd.c.values*100   # 日足ATR(14)÷終値×100 (確定済みの前日まで)
            v=np.nan_to_num(dv[np.clip(self.didx,0,None)]); okv=self.didx>=14
            if P['D1VolMin']>0: okv=okv&(v>=P['D1VolMin'])
            if P['D1VolMax']>0: okv=okv&(v<P['D1VolMax'])
            tb=np.where(okv,tb,0); tsl=np.where(okv,tsl,0)
        a15=sh(self._atr15,1)
        if P['CrossAngleATR']>0:      # クロスの勢い: 1本でMAの差がどれだけ開いたか
            ang=np.nan_to_num(((f1-s1)-(f2-s2))/np.where(a15>0,a15,np.nan)); tb=np.where(ang>=P['CrossAngleATR'],tb,0); tsl=np.where(-ang>=P['CrossAngleATR'],tsl,0)
        if P['PriceBeyond']:          # 終値が両方のMAの外にある
            tb=np.where((c1>f1)&(c1>s1),tb,0); tsl=np.where((c1<f1)&(c1<s1),tsl,0)
        if P['SlowSlopeBars']>0:      # 長期MA自体が同じ向き
            sp_=sh(s,1+P['SlowSlopeBars']); tb=np.where(s1>sp_,tb,0); tsl=np.where(s1<sp_,tsl,0)
        if P['H4RSIMin']>0:
            r4=rsi_wilder(self.b240.c.values,14)[np.clip(self.h4idx,0,None)]; r4=np.nan_to_num(r4,nan=50.0)
            tb=np.where(r4>=P['H4RSIMin'],tb,0); tsl=np.where(r4<=100-P['H4RSIMin'],tsl,0)
        if P['D1RSIMin']>0:
            rD=rsi_wilder(self.bD.c.values,14)[np.clip(self.didx,0,None)]; rD=np.nan_to_num(rD,nan=50.0)
            tb=np.where(rD>=P['D1RSIMin'],tb,0); tsl=np.where(rD<=100-P['D1RSIMin'],tsl,0)
        if P['D1CandleDir']:          # 前日の日足が同じ向き
            Dd=self.bD; up=(Dd.c.values>Dd.o.values)[np.clip(self.didx,0,None)]; tb=np.where(up,tb,0); tsl=np.where(~up,tsl,0)
        if P['SkipDow']>=0:
            wd0=((b.t.values//86400)+3)%7; m_=wd0!=P['SkipDow']; tb=np.where(m_,tb,0); tsl=np.where(m_,tsl,0)
        if P['Dir']>0: tsl=np.zeros_like(tsl)
        if P['Dir']<0: tb=np.zeros_like(tb)
        okE=np.ones(N,bool)
        if P['HourFrom']>=0 and P['HourFrom']!=P['HourTo']:
            hr0=(b.t.values%86400)//3600; A,B=P['HourFrom'],P['HourTo']
            okE&=((hr0>=A)&(hr0<B)) if A<B else ((hr0>=A)|(hr0<B))
        if self.gold:
            hr=(b.t.values%86400)//3600; wd=((b.t.values//86400)+3)%7
            if P['UseTimeFilter'] and P['NoEntryFromHour']!=P['NoEntryToHour']:
                A,B=P['NoEntryFromHour'],P['NoEntryToHour']
                okE&=~(((hr>=A)&(hr<B)) if A<B else ((hr>=A)|(hr<B)))
            if P['FridayStopHour']<24: okE&=~((wd==4)&(hr>=P['FridayStopHour']))
        return tb.astype('int64'),tsl.astype('int64'),np.nan_to_num(aJ),okE
    def run(self,P,spreadFrac=0.0,swapLong=0.0,swapShort=0.0,spMult=1.0,spAdd=0.0,tstart=0,maxSpreadATR=0.0):
        tb,tsl,aJ,okE=self.signals(P)
        msp=self.mo*spreadFrac if self.msp is None else self.msp*spMult+spAdd
        rec,RU,stopOff=simulate(self.mt,self.mo,self.mh,self.ml,self.mc,msp,self.first15,tb,tsl,aJ,okE,maxSpreadATR,tstart,swapLong,swapShort,
            P['MaxLevels'],P['StepATR'],P['StepGrow'],P['LotMult'],P['TP_ATR'],P['TPNanpin_ATR'],P['StopATR'],
            int(P['CooldownHours']*3600),int(self.sigsec*P['NanpinMinBars']),P['OneSideOnly'],P['BE_ATR'],P['TrailStart_ATR'],P['TrailDist_ATR'],P['PyrATR'],P['PyrLot'],P['PyrMax'],P['PyrStopATR'])
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
