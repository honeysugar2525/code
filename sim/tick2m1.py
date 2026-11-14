import sys,zipfile,numpy as np,pandas as pd
zp,out=sys.argv[1],sys.argv[2]
z=zipfile.ZipFile(zp); parts=[]
with z.open(z.namelist()[0]) as f:
    for ch in pd.read_csv(f,usecols=[2,3,4],names=['ts','bid','ask'],header=0,chunksize=2_000_000,dtype={'ts':str,'bid':'float64','ask':'float64'}):
        m=pd.to_datetime(ch.ts.str.slice(0,16),format='%Y-%m-%d %H:%M',cache=True)
        ch['k']=m.values.astype('datetime64[s]').astype('int64'); ch['sp']=ch.ask-ch.bid
        g=ch.groupby('k',sort=True)
        parts.append(pd.DataFrame(dict(o=g.bid.first(),h=g.bid.max(),l=g.bid.min(),c=g.bid.last(),sps=g.sp.sum(),n=g.sp.size(),spmax=g.sp.max(),ah=g.ask.max(),al=g.ask.min())))
d=pd.concat(parts); g=d.groupby(level=0,sort=True)
r=pd.DataFrame(dict(o=g.o.first(),h=g.h.max(),l=g.l.min(),c=g.c.last(),sps=g.sps.sum(),n=g.n.sum(),spmax=g.spmax.max(),ah=g.ah.max(),al=g.al.min()))
r['sp']=r.sps/r.n
a=np.column_stack([r.index.values,r.o,r.h,r.l,r.c,r.sp,r.spmax,r.ah,r.al,r.n]).astype('float64')
np.save(out,a); print(zp.split('/')[-1],len(a),'bars',int(r.n.sum()),'ticks  spread mean',round(float((r.sps.sum()/r.n.sum())),3),'median/min-bar',round(float(r.sp.median()),3))
