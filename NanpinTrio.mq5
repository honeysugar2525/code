//+------------------------------------------------------------------+
//|                                                   NanpinTrio.mq5 |
//|   RSI / ゴールデンクロス / 抵抗帯ブレイク + ナンピン(バスケット決済)   |
//|   ゴールド(XS セント口座)・BTC(Exness スタンダード) 共用             |
//+------------------------------------------------------------------+
#property copyright "NanpinTrio"
#property version   "1.60"
#property description "遅いMAクロス(75/225)でトレンド方向に入り(RSI・抵抗帯ブレイク・ナンピンは任意でオン)、"
#property description "広めの損切りと遠い利確で、含み益が乗ったら損切りを建値へ移します。既定値は金の実データ6年分で検証した設定です。"
#property description "幅はすべてATR基準なので、ゴールドでもBTCでも同じ設定で動きます。"
#property description "ヘッジ口座専用。テスターは「全ティック(リアルティック)」で検証してください。"

#include <Trade/Trade.mqh>

enum ENUM_TREND_FILTER
  {
   TREND_OFF   = 0, // なし(買いも売りも入る)
   TREND_ALIGN = 1  // 上位足MAの方向だけ入る
  };

//--- 基本
input group "◎ 基本設定(まずはここだけ)"
input double          BasketRiskPct     = 3.0;         // 1回の最大損失(残高の%) ※攻め度
input double          FixedBaseLot      = 0.0;         // 初回ロット固定(0=上の%から自動計算)
input bool            UseMinLotIfSmall  = true;        // 自動ロットが最小未満でも最小ロットで入る
input ENUM_TIMEFRAMES SignalTF          = PERIOD_M15;  // シグナルを見る足
input bool            OneSideOnly       = true;        // 買いと売りを同時に持たない
input long            MagicNumber       = 20261113;    // マジックナンバー
input bool            ShowPanel         = true;        // 状態パネルを表示
input bool            DrawZones         = true;        // 抵抗帯・支持帯のラインを描く

//--- シグナル1
input group "◎ シグナル① RSI(ゾーンに入ったら逆張り)"
input bool            UseRSI            = false;       // RSIシグナルを使う(実データでは優位性なし)
input int             RSI_Period        = 14;          // RSI期間
input double          RSI_BuyLow        = 23.0;        // 買いゾーン下限
input double          RSI_BuyHigh       = 30.0;        // 買いゾーン上限
input double          RSI_SellLow       = 70.0;        // 売りゾーン下限
input double          RSI_SellHigh      = 80.0;        // 売りゾーン上限
input bool            RSI_OnEnterOnly   = true;        // ゾーンに入った最初の足だけ反応

//--- シグナル2
input group "◎ シグナル② ゴールデンクロス / デッドクロス"
input bool            UseCross          = true;        // MAクロスを使う
input int             MA_Fast           = 75;          // 短期MA
input int             MA_Slow           = 225;         // 長期MA
input ENUM_MA_METHOD  MA_Method         = MODE_SMA;    // MAの種類

//--- シグナル3
input group "◎ シグナル③ 抵抗帯・支持帯ブレイク"
input bool            UseBreakout       = false;       // ブレイクを使う(実データでは優位性なし)
input int             BO_Lookback       = 120;         // 何本前まで高値・安値を探すか
input int             BO_Pivot          = 3;           // 山・谷と見なす左右の本数
input int             BO_MinTouches     = 2;           // 帯と見なす最低タッチ回数
input double          BO_ZoneATR        = 0.5;         // 同じ帯と見なす幅(シグナル足ATRの倍率)
input double          BO_BufferATR      = 0.1;         // 帯をどれだけ超えたらブレイクか(同上)

//--- トレンド
input group "◎ トレンドフィルター"
input ENUM_TREND_FILTER TrendFilter     = TREND_ALIGN; // フィルターの使い方
input ENUM_TIMEFRAMES TrendTF           = PERIOD_H1;   // トレンドを見る足
input int             TrendMAPeriod     = 200;         // トレンドEMA期間
input int             TrendSlopeBars    = 6;           // EMAの傾きを確認する本数(0=無効)。この本数前より上向きなら買いだけ
input int             DailyMAPeriod     = 60;          // 日足EMAの期間(0=無効)。日足EMAより上なら買いだけ、下なら売りだけ

//--- ナンピン
input group "◎ ナンピン(幅は ATR × 倍率)"
input int             MaxLevels         = 1;           // 最大ポジション数(1=ナンピンなし。実データではナンピンは逆効果)
input ENUM_TIMEFRAMES GridTF            = PERIOD_H1;   // 幅の基準にするATRの足
input int             GridATRPeriod     = 14;          // ATR期間
input double          StepATR           = 0.5;         // ナンピン幅(1回目)
input double          StepGrow          = 1.3;         // ナンピン幅の拡大率(回ごと)
input double          LotMult           = 1.5;         // ロット倍率(回ごと)
input int             NanpinMinBars     = 1;           // ナンピン同士の最低間隔(シグナル足の本数)
input double          TP_ATR            = 8.0;         // 利確幅(初回のみ保有時)
input double          TPNanpin_ATR      = 2.0;         // 利確幅(ナンピン後・平均建値から)
input double          StopATR           = 3.0;         // 損切り幅(ナンピンありの時は最終ナンピンから)
input double          CooldownHours     = 4.0;         // 損切り後に新規を休む時間

//--- 決済の追加ロジック
input group "◎ 含み益が乗った後の損切り引き上げ(幅は ATR × 倍率)"
input double          BE_ATR            = 3.0;         // 建値ストップ: 含み益がこの幅になったら損切りを平均建値へ(0=無効)
input double          TrailStart_ATR    = 0.0;         // トレール開始: 含み益がこの幅になったら追従を始める(0=無効)
input double          TrailDist_ATR     = 3.0;         // トレール幅: 現在値からこの幅だけ離して損切りを追従

//--- フィルター・安全装置
input group "◎ フィルター・安全装置"
input double          MaxSpreadATR      = 0.15;        // 許容スプレッド(ATRの倍率, 0=無制限)
input double          MinDailyATRpct    = 0.0;         // 日足ATR(14)÷価格×100 がこの値以上の時だけ新規(0=無効)。速い設定では1.6
input bool            UseTimeFilter     = true;        // ロールオーバー前後は新規停止(土日も動く銘柄では無効)
input int             NoEntryFromHour   = 23;          // 新規停止の開始時(サーバー時間)
input int             NoEntryToHour     = 2;           // 新規停止の終了時(サーバー時間)
input int             FridayStopHour    = 20;          // 金曜この時刻以降は新規停止(24=無効)
input bool            ServerStops       = true;        // 証券会社側にもTP/SLを置く
input double          MaxLotPerOrder    = 0.0;         // 1注文の最大ロット(0=制限なし)
input double          MaxDDStopPct      = 60.0;        // 残高ピークからこの%減ったら全決済して停止(0=無効)
input bool            ResetHalt         = false;       // 停止状態を解除する(一度trueで起動→falseに戻す)

//--- グローバル
CTrade   trade;
int      hRSI     = INVALID_HANDLE;
int      hFast    = INVALID_HANDLE;
int      hSlow    = INVALID_HANDLE;
int      hTrend   = INVALID_HANDLE;
int      hAtrSig  = INVALID_HANDLE;
int      hAtrGrid = INVALID_HANDLE;
int      hAtrD1   = INVALID_HANDLE;
int      hD1MA    = INVALID_HANDLE;

string   g_prefix          = "";
datetime g_lastBar         = 0;
bool     g_closing[2]      = {false,false};
datetime g_lastAddTry[2]   = {0,0};
datetime g_modFail[2]      = {0,0};
bool     g_stopMoved[2]    = {false,false};   // 損切りを引き上げ済みか(引き上げ後の決済では休止しない)
datetime g_cooldownUntil   = 0;
bool     g_halted          = false;
bool     g_weekendTrading  = false;
double   g_resLevel        = 0.0;
double   g_supLevel        = 0.0;
double   g_lastRSI         = 0.0;
double   g_dayVol          = 0.0;             // 日足ATR(14)÷前日終値×100
string   g_lastSignal      = "-";
string   g_lastNote        = "";
datetime g_lastPanel       = 0;

struct Basket
  {
   int      n;
   double   lots;
   double   avg;
   double   firstPrice;
   double   firstLots;
   double   profit;
   datetime lastTime;
  };

//+------------------------------------------------------------------+
//| 小物                                                             |
//+------------------------------------------------------------------+
int Idx(ENUM_POSITION_TYPE type) { return (type==POSITION_TYPE_BUY) ? 0 : 1; }

string GVName(string key) { return g_prefix+key; }

string AtrKey(ENUM_POSITION_TYPE type) { return (type==POSITION_TYPE_BUY) ? "atrB" : "atrS"; }

string StopKey(ENUM_POSITION_TYPE type) { return (type==POSITION_TYPE_BUY) ? "stpB" : "stpS"; }

bool GetBuf(int handle,int start,int count,double &out[])
  {
   ArraySetAsSeries(out,true);
   return (CopyBuffer(handle,0,start,count,out)==count);
  }

double GridATR()
  {
   double a[];
   if(!GetBuf(hAtrGrid,1,1,a))
      return 0.0;
   return a[0];
  }

double NormPrice(double p)
  {
   double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(ts>0.0)
      p=MathRound(p/ts)*ts;
   return NormalizeDouble(p,_Digits);
  }

bool SpreadOK(double atr)
  {
   if(MaxSpreadATR<=0.0 || atr<=0.0)
      return true;
   double spread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
   return (spread<=MaxSpreadATR*atr);
  }

//+------------------------------------------------------------------+
//| グリッドの形(すべて ATR 倍率)                                     |
//+------------------------------------------------------------------+
// 初回建値から k 本目(0始まり)のエントリーまでの距離
double LevelOffset(int k)
  {
   double off=0.0;
   for(int i=0;i<k;i++)
      off+=StepATR*MathPow(StepGrow,i);
   return off;
  }

// 初回建値から損切りラインまでの距離
double StopOffset() { return LevelOffset(MaxLevels-1)+StopATR; }

// 全段入って損切りになった時の損失(初回1ロットあたり, ATR×ロット単位)
double RiskUnits()
  {
   double u=0.0, stop=StopOffset();
   for(int k=0;k<MaxLevels;k++)
      u+=MathPow(LotMult,k)*(stop-LevelOffset(k));
   return u;
  }

//+------------------------------------------------------------------+
//| ロット計算(口座通貨・契約サイズは証券会社の値をそのまま使う)        |
//+------------------------------------------------------------------+
// 1.0ロットで価格が dist 動いた時の損益(口座通貨。セント口座ならセント)
double MoneyPerLot(double dist)
  {
   if(dist<=0.0)
      return 0.0;
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double pr=0.0;
   if(ask>0.0 && OrderCalcProfit(ORDER_TYPE_BUY,_Symbol,1.0,ask,ask+dist,pr) && pr>0.0)
      return pr;
   double tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tv>0.0 && ts>0.0)
      return dist/ts*tv;
   return 0.0;
  }

double NormLot(double lot,bool roundNearest)
  {
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(step<=0.0)
      step=0.01;
   if(MaxLotPerOrder>0.0 && lot>MaxLotPerOrder)
      lot=MaxLotPerOrder;
   if(mx>0.0 && lot>mx)
      lot=mx;
   double q=roundNearest ? MathRound(lot/step) : MathFloor(lot/step+1e-9);
   double v=q*step;
   if(v<mn)
      v=mn;
   return NormalizeDouble(v,8);
  }

// 初回ロット。tooSmall=自動計算が最小ロット未満だった
double CalcBaseLot(double atr,bool &tooSmall)
  {
   tooSmall=false;
   if(FixedBaseLot>0.0)
      return NormLot(FixedBaseLot,false);
   double perLot=MoneyPerLot(atr*RiskUnits());
   if(perLot<=0.0)
      return 0.0;
   double raw=AccountInfoDouble(ACCOUNT_BALANCE)*BasketRiskPct/100.0/perLot;
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   if(raw<mn)
     {
      tooSmall=true;
      if(!UseMinLotIfSmall)
         return 0.0;
      return mn;
     }
   return NormLot(raw,false);
  }

// 初回ロット lot で全段損切りになった時の想定損失(残高の%)
double EstRiskPct(double lot,double atr)
  {
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal<=0.0)
      return 0.0;
   return MoneyPerLot(atr*RiskUnits())*lot/bal*100.0;
  }

//+------------------------------------------------------------------+
//| バスケット(同方向ポジションのまとまり)                            |
//+------------------------------------------------------------------+
void ReadBasket(ENUM_POSITION_TYPE type,Basket &b)
  {
   b.n=0; b.lots=0.0; b.avg=0.0; b.firstPrice=0.0; b.firstLots=0.0; b.profit=0.0; b.lastTime=0;
   double sum=0.0;
   long firstMsc=LONG_MAX;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i);
      if(tk==0)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=type)
         continue;
      double v=PositionGetDouble(POSITION_VOLUME);
      double p=PositionGetDouble(POSITION_PRICE_OPEN);
      long msc=PositionGetInteger(POSITION_TIME_MSC);
      datetime t=(datetime)PositionGetInteger(POSITION_TIME);
      b.n++;
      b.lots+=v;
      sum+=v*p;
      b.profit+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
      if(msc<firstMsc)
        {
         firstMsc=msc;
         b.firstPrice=p;
         b.firstLots=v;
        }
      if(t>b.lastTime)
         b.lastTime=t;
     }
   if(b.lots>0.0)
      b.avg=sum/b.lots;
  }

bool OpenOrder(ENUM_POSITION_TYPE type,double lot,string cmt)
  {
   if(lot<=0.0)
      return false;
   ENUM_ORDER_TYPE ot=(type==POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double price=(type==POSITION_TYPE_BUY) ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double margin=0.0;
   if(OrderCalcMargin(ot,_Symbol,lot,price,margin) && margin>AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      g_lastNote="証拠金不足で見送り";
      Print("NanpinTrio: 証拠金不足のため注文を見送り lot=",DoubleToString(lot,2));
      return false;
     }
   bool ok=(type==POSITION_TYPE_BUY) ? trade.Buy(lot,_Symbol,0.0,0.0,0.0,cmt) : trade.Sell(lot,_Symbol,0.0,0.0,0.0,cmt);
   uint rc=trade.ResultRetcode();
   if(!ok || (rc!=TRADE_RETCODE_DONE && rc!=TRADE_RETCODE_DONE_PARTIAL && rc!=TRADE_RETCODE_PLACED))
     {
      Print("NanpinTrio: 注文失敗 ",cmt," lot=",DoubleToString(lot,2)," ",rc," ",trade.ResultRetcodeDescription());
      return false;
     }
   Print("NanpinTrio: 発注 ",cmt," ",(type==POSITION_TYPE_BUY ? "BUY " : "SELL "),DoubleToString(lot,2));
   return true;
  }

void CloseBasket(ENUM_POSITION_TYPE type,string why)
  {
   g_closing[Idx(type)]=true;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i);
      if(tk==0)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=type)
         continue;
      if(!trade.PositionClose(tk))
         Print("NanpinTrio: 決済失敗(",why,") #",tk," ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
     }
  }

void StartCooldown(string why)
  {
   if(CooldownHours<=0.0)
      return;
   g_cooldownUntil=TimeCurrent()+(int)(CooldownHours*3600.0);
   GlobalVariableSet(GVName("cool"),(double)g_cooldownUntil);
   Print("NanpinTrio: 損切り(",why,")。",TimeToString(g_cooldownUntil,TIME_DATE|TIME_MINUTES)," まで新規停止");
  }

// 証券会社側の TP/SL をバスケットの値にそろえる
void SyncStops(ENUM_POSITION_TYPE type,double sl,double tp)
  {
   int ix=Idx(type);
   if(TimeCurrent()-g_modFail[ix]<15)
      return;
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double minDist=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double tol=MathMax(_Point,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE))*1.5;
   sl=NormPrice(sl);
   tp=NormPrice(tp);
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong tk=PositionGetTicket(i);
      if(tk==0)
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=type)
         continue;
      double curSL=PositionGetDouble(POSITION_SL);
      double curTP=PositionGetDouble(POSITION_TP);
      double newSL=sl, newTP=tp;
      if(type==POSITION_TYPE_BUY)
        {
         if(newTP<bid+minDist) newTP=curTP;
         if(newSL>bid-minDist) newSL=curSL;
        }
      else
        {
         if(newTP>ask-minDist) newTP=curTP;
         if(newSL<ask+minDist) newSL=curSL;
        }
      if(MathAbs(newSL-curSL)<tol && MathAbs(newTP-curTP)<tol)
         continue;
      if(!trade.PositionModify(tk,newSL,newTP))
        {
         g_modFail[ix]=TimeCurrent();
         Print("NanpinTrio: TP/SL変更失敗 #",tk," ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
         return;
        }
     }
  }

// 現在の損切り価格。引き上げ済みならその値、まだなら最初の損切りライン
double CurrentStop(ENUM_POSITION_TYPE type,double baseStop)
  {
   string key=GVName(StopKey(type));
   if(!GlobalVariableCheck(key))
      return baseStop;
   double v=GlobalVariableGet(key);
   if(v<=0.0)
      return baseStop;
   if(type==POSITION_TYPE_BUY)
      return MathMax(v,baseStop);
   return MathMin(v,baseStop);
  }

// 毎ティック: 利確・損切り・ナンピン・損切り引き上げ・TP/SL同期
void ManageBasket(ENUM_POSITION_TYPE type)
  {
   int ix=Idx(type);
   Basket b;
   ReadBasket(type,b);
   string key=GVName(AtrKey(type));
   if(b.n==0)
     {
      g_closing[ix]=false;
      if(GlobalVariableCheck(key))
         GlobalVariableDel(key);
      if(GlobalVariableCheck(GVName(StopKey(type))))
         GlobalVariableDel(GVName(StopKey(type)));
      return;
     }
   if(g_closing[ix])
     {
      CloseBasket(type,"再試行");
      return;
     }
   // バスケット開始時のATRで幅を固定する
   double atrb=0.0;
   if(GlobalVariableCheck(key))
      atrb=GlobalVariableGet(key);
   if(atrb<=0.0)
     {
      atrb=GridATR();
      if(atrb<=0.0)
         return;
      GlobalVariableSet(key,atrb);
     }
   double dir=(type==POSITION_TYPE_BUY) ? 1.0 : -1.0;
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double exitPx=(type==POSITION_TYPE_BUY) ? bid : ask;   // 決済される側の価格
   double addPx =(type==POSITION_TYPE_BUY) ? ask : bid;   // 追加で建つ側の価格
   double baseStop=b.firstPrice-dir*atrb*StopOffset();
   double stopPrice=CurrentStop(type,baseStop);
   double tpPrice=b.avg+dir*atrb*((b.n<=1) ? TP_ATR : TPNanpin_ATR);
   g_stopMoved[ix]=((stopPrice-baseStop)*dir>_Point*0.5);

   bool hitTP=(dir>0.0) ? (exitPx>=tpPrice) : (exitPx<=tpPrice);
   bool hitSL=(dir>0.0) ? (exitPx<=stopPrice) : (exitPx>=stopPrice);
   if(hitTP)
     {
      Print("NanpinTrio: 利確 ",(dir>0.0 ? "BUY" : "SELL")," 段数=",b.n," 損益=",DoubleToString(b.profit,2));
      CloseBasket(type,"TP");
      return;
     }
   if(hitSL)
     {
      Print("NanpinTrio: ",(g_stopMoved[ix] ? "引き上げた損切りで決済 " : "損切り "),(dir>0.0 ? "BUY" : "SELL")," 段数=",b.n," 損益=",DoubleToString(b.profit,2));
      CloseBasket(type,"SL");
      if(!g_stopMoved[ix])
         StartCooldown("損切りライン到達");
      return;
     }
   // 含み益が乗ったら損切りを引き上げる(建値ストップ → トレール)。一度上げたら下げない
   double gain=(exitPx-b.avg)*dir;
   double newStop=stopPrice;
   if(BE_ATR>0.0 && gain>=BE_ATR*atrb && (b.avg-newStop)*dir>0.0)
      newStop=b.avg;
   if(TrailStart_ATR>0.0 && TrailDist_ATR>0.0 && gain>=TrailStart_ATR*atrb)
     {
      double cand=exitPx-dir*TrailDist_ATR*atrb;
      if((cand-newStop)*dir>=0.1*atrb)   // 細かく動かしすぎない
         newStop=cand;
     }
   if(newStop!=stopPrice)
     {
      stopPrice=newStop;
      GlobalVariableSet(GVName(StopKey(type)),stopPrice);
      g_stopMoved[ix]=true;
     }
   // ナンピン
   if(b.n<MaxLevels && !g_halted)
     {
      double levelPrice=b.firstPrice-dir*atrb*LevelOffset(b.n);
      bool reach=(dir>0.0) ? (addPx<=levelPrice) : (addPx>=levelPrice);
      long minGap=(long)PeriodSeconds(SignalTF)*MathMax(0,NanpinMinBars);
      if(reach && (long)(TimeCurrent()-b.lastTime)>=minGap && TimeCurrent()-g_lastAddTry[ix]>=5 && SpreadOK(atrb))
        {
         g_lastAddTry[ix]=TimeCurrent();
         double lot=NormLot(b.firstLots*MathPow(LotMult,b.n),true);
         if(OpenOrder(type,lot,"NT-N"+IntegerToString(b.n+1)))
            return;   // 次のティックで平均建値を取り直す
        }
     }
   if(ServerStops)
      SyncStops(type,stopPrice,tpPrice);
  }

//+------------------------------------------------------------------+
//| 抵抗帯・支持帯                                                    |
//+------------------------------------------------------------------+
void DrawLine(string name,double price,color clr)
  {
   if(!DrawZones || price<=0.0)
     {
      ObjectDelete(0,name);
      return;
     }
   if(ObjectFind(0,name)<0)
     {
      ObjectCreate(0,name,OBJ_HLINE,0,0,price);
      ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
      ObjectSetInteger(0,name,OBJPROP_STYLE,STYLE_DASH);
      ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(0,name,OBJPROP_BACK,true);
     }
   ObjectSetDouble(0,name,OBJPROP_PRICE,price);
  }

// 山(谷)が BO_MinTouches 回以上そろった価格帯を探し、直近の確定足が終値で抜けたかを見る
void ScanZones(double atrSig,bool &boBuy,bool &boSell)
  {
   boBuy=false;
   boSell=false;
   g_resLevel=0.0;
   g_supLevel=0.0;
   MqlRates r[];
   ArraySetAsSeries(r,true);
   int want=BO_Lookback+BO_Pivot+2;
   int got=CopyRates(_Symbol,SignalTF,0,want,r);
   if(got<BO_Pivot*2+10 || atrSig<=0.0)
      return;
   double tol=BO_ZoneATR*atrSig;
   double buf=BO_BufferATR*atrSig;
   double c1=r[1].close;
   double c2=r[2].close;
   double ph[], pl[];
   ArrayResize(ph,got);
   ArrayResize(pl,got);
   int nh=0, nl=0;
   int last=got-1-BO_Pivot;
   for(int i=BO_Pivot+2;i<=last;i++)
     {
      bool isH=true, isL=true;
      for(int k=1;k<=BO_Pivot && (isH || isL);k++)
        {
         if(r[i].high<r[i-k].high || r[i].high<=r[i+k].high) isH=false;
         if(r[i].low>r[i-k].low || r[i].low>=r[i+k].low)     isL=false;
        }
      if(isH)
        {
         bool broken=false;   // 2本前までに終値で抜かれた山は対象外
         for(int j=i-1;j>=2;j--)
            if(r[j].close>r[i].high) { broken=true; break; }
         if(!broken)
            ph[nh++]=r[i].high;
        }
      if(isL)
        {
         bool broken=false;
         for(int j=i-1;j>=2;j--)
            if(r[j].close<r[i].low) { broken=true; break; }
         if(!broken)
            pl[nl++]=r[i].low;
        }
     }
   // 抵抗帯
   for(int a=0;a<nh;a++)
     {
      int touches=0;
      double top=ph[a];
      for(int q=0;q<nh;q++)
         if(MathAbs(ph[q]-ph[a])<=tol)
           {
            touches++;
            if(ph[q]>top) top=ph[q];
           }
      if(touches<BO_MinTouches)
         continue;
      if(c2<=top && c1>top+buf)
         boBuy=true;
      if(top>=c1 && (g_resLevel==0.0 || top<g_resLevel))
         g_resLevel=top;
     }
   // 支持帯
   for(int a=0;a<nl;a++)
     {
      int touches=0;
      double bottom=pl[a];
      for(int q=0;q<nl;q++)
         if(MathAbs(pl[q]-pl[a])<=tol)
           {
            touches++;
            if(pl[q]<bottom) bottom=pl[q];
           }
      if(touches<BO_MinTouches)
         continue;
      if(c2>=bottom && c1<bottom-buf)
         boSell=true;
      if(bottom<=c1 && (g_supLevel==0.0 || bottom>g_supLevel))
         g_supLevel=bottom;
     }
   DrawLine(g_prefix+"RES",g_resLevel,clrTomato);
   DrawLine(g_prefix+"SUP",g_supLevel,clrDodgerBlue);
  }

//+------------------------------------------------------------------+
//| 新規エントリー                                                    |
//+------------------------------------------------------------------+
bool TimeOK()
  {
   if(g_weekendTrading)
      return true;   // BTCなど土日も動く銘柄は時間で止めない
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(),dt);
   if(UseTimeFilter && NoEntryFromHour!=NoEntryToHour)
     {
      bool blocked=(NoEntryFromHour<NoEntryToHour)
                   ? (dt.hour>=NoEntryFromHour && dt.hour<NoEntryToHour)
                   : (dt.hour>=NoEntryFromHour || dt.hour<NoEntryToHour);
      if(blocked)
         return false;
     }
   if(FridayStopHour<24 && dt.day_of_week==5 && dt.hour>=FridayStopHour)
      return false;
   return true;
  }

void OpenFirst(ENUM_POSITION_TYPE type,string tag)
  {
   double atr=GridATR();
   if(atr<=0.0)
      return;
   if(!SpreadOK(atr))
     {
      g_lastNote="スプレッド拡大で見送り";
      return;
     }
   bool tooSmall=false;
   double lot=CalcBaseLot(atr,tooSmall);
   if(lot<=0.0)
     {
      g_lastNote="残高不足(最小ロット未満)で見送り";
      return;
     }
   if(tooSmall)
      Print("NanpinTrio: 自動ロットが最小未満のため最小ロットで発注。想定最大損失=残高の",
            DoubleToString(EstRiskPct(lot,atr),1),"%");
   GlobalVariableSet(GVName(AtrKey(type)),atr);
   GlobalVariableDel(GVName(StopKey(type)));
   g_stopMoved[Idx(type)]=false;
   if(OpenOrder(type,lot,"NT-"+tag))
      g_lastNote="";
  }

// シグナル足が確定するたびに1回
void CheckSignals()
  {
   int needBars=MathMax(MathMax(MA_Slow,RSI_Period)+5,BO_Lookback+BO_Pivot+5);
   if(Bars(_Symbol,SignalTF)<needBars)
      return;
   double rsi[], f[], s[], atrS[], tm[];
   if(!GetBuf(hRSI,1,2,rsi) || !GetBuf(hFast,1,2,f) || !GetBuf(hSlow,1,2,s) || !GetBuf(hAtrSig,1,1,atrS))
      return;
   double c1=iClose(_Symbol,SignalTF,1);
   if(c1<=0.0)
      return;
   g_lastRSI=rsi[0];
   // 値動きの大きさ(確定済みの前日までの日足で計算)
   double da[];
   double dc=iClose(_Symbol,PERIOD_D1,1);
   bool dayVolOK=(GetBuf(hAtrD1,1,1,da) && dc>0.0);
   if(dayVolOK)
      g_dayVol=da[0]/dc*100.0;

   // ① RSI
   bool inBuy1 =(rsi[0]>=RSI_BuyLow  && rsi[0]<=RSI_BuyHigh);
   bool inBuy2 =(rsi[1]>=RSI_BuyLow  && rsi[1]<=RSI_BuyHigh);
   bool inSell1=(rsi[0]>=RSI_SellLow && rsi[0]<=RSI_SellHigh);
   bool inSell2=(rsi[1]>=RSI_SellLow && rsi[1]<=RSI_SellHigh);
   bool rsiBuy =UseRSI && inBuy1  && (!RSI_OnEnterOnly || !inBuy2);
   bool rsiSell=UseRSI && inSell1 && (!RSI_OnEnterOnly || !inSell2);

   // ② MAクロス
   bool crossBuy =UseCross && f[1]<=s[1] && f[0]>s[0];
   bool crossSell=UseCross && f[1]>=s[1] && f[0]<s[0];

   // ③ ブレイク(ラインの更新も兼ねる)
   bool boBuy=false, boSell=false;
   ScanZones(atrS[0],boBuy,boSell);
   if(!UseBreakout)
     {
      boBuy=false;
      boSell=false;
     }

   string buyTag="", sellTag="";
   if(rsiBuy)    buyTag+="RSI";
   if(crossBuy)  buyTag+="GC";
   if(boBuy)     buyTag+="BO";
   if(rsiSell)   sellTag+="RSI";
   if(crossSell) sellTag+="DC";
   if(boSell)    sellTag+="BO";
   bool buy=(buyTag!=""), sell=(sellTag!="");
   if(!buy && !sell)
      return;

   // トレンドフィルター
   if(TrendFilter==TREND_ALIGN)
     {
      if(!GetBuf(hTrend,1,1,tm))
         return;
      if(c1<=tm[0]) buy=false;
      if(c1>=tm[0]) sell=false;
     }
   // EMAの傾き: 上向きなら買いだけ、下向きなら売りだけ
   if(TrendSlopeBars>0)
     {
      double sl[];
      if(!GetBuf(hTrend,1,TrendSlopeBars+1,sl))
         return;
      if(sl[0]<=sl[TrendSlopeBars]) buy=false;
      if(sl[0]>=sl[TrendSlopeBars]) sell=false;
     }
   // 日足のトレンド: 確定済みの日足EMAより上なら買いだけ、下なら売りだけ
   if(DailyMAPeriod>0)
     {
      double dm[];
      if(!GetBuf(hD1MA,1,1,dm))
         return;
      if(c1<=dm[0]) buy=false;
      if(c1>=dm[0]) sell=false;
     }
   if(buy && sell)
     {
      g_lastSignal="買い("+buyTag+")と売り("+sellTag+")が同時→見送り";
      return;
     }
   if(!buy && !sell)
     {
      g_lastSignal=((buyTag!="") ? "買い("+buyTag+")" : "売り("+sellTag+")")+" トレンドが合わず見送り";
      return;
     }
   g_lastSignal=buy ? "買い("+buyTag+")" : "売り("+sellTag+")";
   g_lastSignal+=" "+TimeToString(TimeCurrent(),TIME_DATE|TIME_MINUTES);

   if(g_halted)
      return;
   if(MinDailyATRpct>0.0 && (!dayVolOK || g_dayVol<MinDailyATRpct))
     {
      g_lastNote="値動きが小さいため見送り(日足ATR "+DoubleToString(g_dayVol,2)+"% < "+DoubleToString(MinDailyATRpct,2)+"%)";
      return;
     }
   if(TimeCurrent()<g_cooldownUntil)
     {
      g_lastNote="損切り後の休止中";
      return;
     }
   if(!TimeOK())
     {
      g_lastNote="時間フィルターで見送り";
      return;
     }
   Basket bb, sb;
   ReadBasket(POSITION_TYPE_BUY,bb);
   ReadBasket(POSITION_TYPE_SELL,sb);
   if(buy)
     {
      if(bb.n>0 || g_closing[0])
         return;
      if(OneSideOnly && (sb.n>0 || g_closing[1]))
         return;
      OpenFirst(POSITION_TYPE_BUY,buyTag);
     }
   else
     {
      if(sb.n>0 || g_closing[1])
         return;
      if(OneSideOnly && (bb.n>0 || g_closing[0]))
         return;
      OpenFirst(POSITION_TYPE_SELL,sellTag);
     }
  }

//+------------------------------------------------------------------+
//| 口座全体の安全装置                                                |
//+------------------------------------------------------------------+
void CheckAccountStop()
  {
   if(MaxDDStopPct<=0.0 || g_halted)
      return;
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   string key=GVName("peak");
   double peak=GlobalVariableCheck(key) ? GlobalVariableGet(key) : 0.0;
   if(bal>peak)
     {
      peak=bal;
      GlobalVariableSet(key,peak);
     }
   if(peak>0.0 && (peak-eq)/peak*100.0>=MaxDDStopPct)
     {
      g_halted=true;
      GlobalVariableSet(GVName("halt"),1.0);
      CloseBasket(POSITION_TYPE_BUY,"DD停止");
      CloseBasket(POSITION_TYPE_SELL,"DD停止");
      Alert("NanpinTrio: 残高ピークから ",DoubleToString(MaxDDStopPct,0),"% 減少。全決済して停止しました (",_Symbol,")");
     }
  }

//+------------------------------------------------------------------+
//| パネル                                                           |
//+------------------------------------------------------------------+
string BasketLine(ENUM_POSITION_TYPE type,string label)
  {
   Basket b;
   ReadBasket(type,b);
   if(b.n==0)
      return label+": なし\n";
   string key=GVName(AtrKey(type));
   double atrb=GlobalVariableCheck(key) ? GlobalVariableGet(key) : GridATR();
   double dir=(type==POSITION_TYPE_BUY) ? 1.0 : -1.0;
   double baseStop=b.firstPrice-dir*atrb*StopOffset();
   double stopPrice=CurrentStop(type,baseStop);
   bool moved=((stopPrice-baseStop)*dir>_Point*0.5);
   double tpPrice=b.avg+dir*atrb*((b.n<=1) ? TP_ATR : TPNanpin_ATR);
   string txt=label+": "+IntegerToString(b.n)+"/"+IntegerToString(MaxLevels)+"段  "+DoubleToString(b.lots,2)+"ロット  含み "+DoubleToString(b.profit,2)+"\n";
   txt+="   平均 "+DoubleToString(b.avg,_Digits)+"  利確 "+DoubleToString(tpPrice,_Digits)+"  損切り "+DoubleToString(stopPrice,_Digits)+(moved ? "(引き上げ済み)" : "")+"\n";
   if(b.n<MaxLevels)
      txt+="   次のナンピン "+DoubleToString(b.firstPrice-dir*atrb*LevelOffset(b.n),_Digits)+"\n";
   return txt;
  }

void UpdatePanel()
  {
   if(!ShowPanel)
      return;
   if(TimeCurrent()==g_lastPanel)
      return;
   g_lastPanel=TimeCurrent();
   double atr=GridATR();
   bool tooSmall=false;
   double lot=(atr>0.0) ? CalcBaseLot(atr,tooSmall) : 0.0;
   string txt="NanpinTrio  "+_Symbol+"  "+AccountInfoString(ACCOUNT_CURRENCY)+"\n";
   if(g_halted)
      txt+="★ 停止中(DD上限)。ResetHalt=true で解除\n";
   else if(TimeCurrent()<g_cooldownUntil)
      txt+="損切り後の休止中 → "+TimeToString(g_cooldownUntil,TIME_DATE|TIME_MINUTES)+"\n";
   txt+="初回ロット "+DoubleToString(lot,2)+"  全段損切り時の想定損失 "+DoubleToString(EstRiskPct(lot,atr),1)+"%";
   if(tooSmall)
      txt+="  ※残高が小さく設定%を超えています";
   txt+="\n";
   txt+="ATR "+DoubleToString(atr,_Digits)+"  損切りまで "+DoubleToString(atr*StopOffset(),_Digits)+"  日足ATR "+DoubleToString(g_dayVol,2)+"%"+((MinDailyATRpct>0.0) ? ((g_dayVol>=MinDailyATRpct) ? "(稼働)" : "(待機)") : "")+"\n";
   txt+="抵抗帯 "+((g_resLevel>0.0) ? DoubleToString(g_resLevel,_Digits) : "-")+"  支持帯 "+((g_supLevel>0.0) ? DoubleToString(g_supLevel,_Digits) : "-")+"\n";
   txt+="直近シグナル: "+g_lastSignal+"\n";
   if(g_lastNote!="")
      txt+="メモ: "+g_lastNote+"\n";
   txt+=BasketLine(POSITION_TYPE_BUY,"買い");
   txt+=BasketLine(POSITION_TYPE_SELL,"売り");
   Comment(txt);
  }

//+------------------------------------------------------------------+
//| イベント                                                         |
//+------------------------------------------------------------------+
int OnInit()
  {
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      Alert("NanpinTrio: ヘッジ口座専用です(この口座はネッティング方式のため動かせません)");
      return INIT_FAILED;
     }
   if(MaxLevels<1 || MaxLevels>15 || LotMult<1.0 || StepATR<=0.0 || StepGrow<=0.0 || StopATR<=0.0 ||
      TP_ATR<=0.0 || TPNanpin_ATR<=0.0 || MA_Fast<1 || MA_Slow<=MA_Fast || RSI_Period<2 ||
      BO_Pivot<1 || BO_Lookback<BO_Pivot*2+10 || BO_MinTouches<1 || TrendMAPeriod<2 || GridATRPeriod<2 ||
      TrendSlopeBars<0 || BE_ATR<0.0 || TrailStart_ATR<0.0 || (TrailStart_ATR>0.0 && TrailDist_ATR<=0.0) ||
      MinDailyATRpct<0.0 || DailyMAPeriod<0 || (FixedBaseLot<=0.0 && BasketRiskPct<=0.0))
     {
      Alert("NanpinTrio: パラメータが不正です。値を見直してください");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_prefix="NT_"+IntegerToString(MagicNumber)+"_"+_Symbol+"_";
   trade.SetExpertMagicNumber((ulong)MagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   hRSI    =iRSI(_Symbol,SignalTF,RSI_Period,PRICE_CLOSE);
   hFast   =iMA(_Symbol,SignalTF,MA_Fast,0,MA_Method,PRICE_CLOSE);
   hSlow   =iMA(_Symbol,SignalTF,MA_Slow,0,MA_Method,PRICE_CLOSE);
   hTrend  =iMA(_Symbol,TrendTF,TrendMAPeriod,0,MODE_EMA,PRICE_CLOSE);
   hAtrSig =iATR(_Symbol,SignalTF,14);
   hAtrGrid=iATR(_Symbol,GridTF,GridATRPeriod);
   hAtrD1  =iATR(_Symbol,PERIOD_D1,14);
   if(DailyMAPeriod>0)
      hD1MA=iMA(_Symbol,PERIOD_D1,DailyMAPeriod,0,MODE_EMA,PRICE_CLOSE);
   if(hRSI==INVALID_HANDLE || hFast==INVALID_HANDLE || hSlow==INVALID_HANDLE ||
      hTrend==INVALID_HANDLE || hAtrSig==INVALID_HANDLE || hAtrGrid==INVALID_HANDLE || hAtrD1==INVALID_HANDLE ||
      (DailyMAPeriod>0 && hD1MA==INVALID_HANDLE))
     {
      Alert("NanpinTrio: インジケーターの作成に失敗しました");
      return INIT_FAILED;
     }
   // 土曜にも取引時間がある銘柄(BTCなど)か
   datetime from=0, to=0;
   g_weekendTrading=(SymbolInfoSessionTrade(_Symbol,SATURDAY,0,from,to) && to>from);

   if(ResetHalt)
     {
      GlobalVariableDel(GVName("halt"));
      GlobalVariableDel(GVName("peak"));
      GlobalVariableDel(GVName("cool"));
     }
   g_halted=GlobalVariableCheck(GVName("halt"));
   g_cooldownUntil=GlobalVariableCheck(GVName("cool")) ? (datetime)GlobalVariableGet(GVName("cool")) : 0;
   g_lastBar=0;
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(hRSI!=INVALID_HANDLE)     IndicatorRelease(hRSI);
   if(hFast!=INVALID_HANDLE)    IndicatorRelease(hFast);
   if(hSlow!=INVALID_HANDLE)    IndicatorRelease(hSlow);
   if(hTrend!=INVALID_HANDLE)   IndicatorRelease(hTrend);
   if(hAtrSig!=INVALID_HANDLE)  IndicatorRelease(hAtrSig);
   if(hAtrGrid!=INVALID_HANDLE) IndicatorRelease(hAtrGrid);
   if(hAtrD1!=INVALID_HANDLE)   IndicatorRelease(hAtrD1);
   if(hD1MA!=INVALID_HANDLE)    IndicatorRelease(hD1MA);
   ObjectDelete(0,g_prefix+"RES");
   ObjectDelete(0,g_prefix+"SUP");
   Comment("");
  }

void OnTick()
  {
   CheckAccountStop();
   ManageBasket(POSITION_TYPE_BUY);
   ManageBasket(POSITION_TYPE_SELL);
   datetime t=iTime(_Symbol,SignalTF,0);
   if(t!=0 && t!=g_lastBar)
     {
      // 起動直後の1本目は「すでに過ぎたシグナル」なので入らない
      if(g_lastBar!=0)
         CheckSignals();
      g_lastBar=t;
     }
   UpdatePanel();
  }

// 証券会社側のSLで決済された時も、損切り後の休止を始める
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
  {
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD)
      return;
   ulong deal=trans.deal;
   if(deal==0 || !HistoryDealSelect(deal))
      return;
   if(HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol)
      return;
   if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY)!=DEAL_ENTRY_OUT)
      return;
   if((ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON)!=DEAL_REASON_SL)
      return;
   long magic=HistoryDealGetInteger(deal,DEAL_MAGIC);
   long posId=HistoryDealGetInteger(deal,DEAL_POSITION_ID);
   // 売りの約定で閉じた=買いバスケット
   int side=((ENUM_DEAL_TYPE)HistoryDealGetInteger(deal,DEAL_TYPE)==DEAL_TYPE_SELL) ? 0 : 1;
   if(magic!=MagicNumber)
     {
      // 決済側の約定にマジックが付かない証券会社向けに、建てた側の約定で確認する
      bool mine=false;
      if(HistorySelectByPosition(posId))
        {
         int total=HistoryDealsTotal();
         for(int i=0;i<total;i++)
           {
            ulong d=HistoryDealGetTicket(i);
            if(d==0)
               continue;
            if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(d,DEAL_ENTRY)==DEAL_ENTRY_IN &&
               HistoryDealGetInteger(d,DEAL_MAGIC)==MagicNumber)
              {
               mine=true;
               break;
              }
           }
        }
      if(!mine)
         return;
     }
   // 損切りを引き上げた後の決済なら休止しない
   if(!g_stopMoved[side] && TimeCurrent()>=g_cooldownUntil)
      StartCooldown("証券会社側SL");
  }
//+------------------------------------------------------------------+
