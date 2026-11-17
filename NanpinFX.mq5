//+------------------------------------------------------------------+
//|                                                     NanpinFX.mq5 |
//|   FX 用ナンピン EA                                                |
//|   ナンピン上限まで入ってもさらに耐えられるロットを、残高から自動計算  |
//+------------------------------------------------------------------+
#property copyright "NanpinFX"
#property version   "1.00"
#property description "RSI(1時間足)の売られすぎ・買われすぎで入り、逆行したらナンピン(最大10回)、平均建値から利確します。"
#property description "初回ロットは「ナンピンを全部入れ、さらに1段分逆行した耐えるラインで全決済した時の損失 = 残高の RiskPct%」になるよう自動で決まります。"
#property description "既定値は15通貨ペア・11年分の実データで、耐えるラインに一度も届かなかった設定です。期待できる月利は0.1%前後です(README参照)。"
#property description "ヘッジ口座専用。テスターは「全ティック(リアルティック)」で検証してください。"

#include <Trade/Trade.mqh>

enum ENUM_STEP_BASE
  {
   STEP_BASE_ATR  = 0, // 日足ATR(14)の倍率
   STEP_BASE_PIPS = 1  // pips で固定
  };

enum ENUM_ENTRY_MODE
  {
   ENTRY_ALWAYS = 0, // 常時(決済したらすぐ次を建てる)
   ENTRY_RSI    = 1  // RSI が売られすぎ・買われすぎの時だけ
  };

//--- 基本
input group "◎ 基本設定(まずはここだけ)"
input double          RiskPct          = 30.0;          // 攻め度: 耐えるラインで全決済した時の損失(残高の%)
input double          FixedBaseLot     = 0.0;           // 初回ロット固定(0=上の%から自動計算)
input bool            UseMinLotIfSmall = false;         // 自動ロットが最小ロット未満でも最小ロットで入る(損失が上の%を超える)
input long            MagicNumber      = 20261117;      // マジックナンバー
input bool            ShowPanel        = true;          // 状態パネルを表示

//--- ナンピン
input group "◎ ナンピン"
input int             MaxNanpin        = 10;            // ナンピン回数の上限(初回は含まない。10なら最大11本)
input ENUM_STEP_BASE  StepBase         = STEP_BASE_ATR; // ナンピン幅の基準
input double          StepATR          = 0.6;           // 1回目のナンピン幅(日足ATRの倍率)
input double          StepPips         = 20.0;          // 1回目のナンピン幅(pips。幅の基準=pips の時)
input double          StepGrow         = 1.2;           // ナンピン幅の拡大率(回ごと。20→24→28.8…)
input double          LotMult          = 1.7;           // ロット倍率(回ごと。1.0なら同じロット)
input double          TPRatio          = 1.0;           // 利確幅 = 1回目のナンピン幅 × この値(平均建値から)
input double          SurviveSteps     = 1.0;           // 最後のナンピンの先に取る余裕(次のナンピン幅の何回分か)
input bool            CutAtSurvive     = true;          // 耐えるラインで全決済する(false=持ち続ける。口座ごと飛ぶ危険)
input int             NanpinMinMinutes = 0;             // ナンピン同士の最低間隔(分。0=制限なし)

//--- エントリー
input group "◎ エントリー"
input ENUM_ENTRY_MODE EntryMode        = ENTRY_RSI;     // いつ入るか
input ENUM_TIMEFRAMES RSI_TF           = PERIOD_H1;     // RSI を見る足
input int             RSI_Period       = 14;            // RSI 期間
input double          RSI_BuyBelow     = 25.0;          // RSI がこの値未満なら買い
input double          RSI_SellAbove    = 75.0;          // RSI がこの値を超えたら売り
input int             TrendMAPeriod    = 0;             // 日足EMAの期間(0=無効)。EMAより上なら買いだけ、下なら売りだけ
input bool            BothSides        = true;          // 買いと売りを同時に持てる(別々のバスケット)

//--- フィルター・安全装置
input group "◎ フィルター・安全装置"
input double          MaxSpreadPips    = 3.0;           // 許容スプレッド(pips。0=無制限)。新規とナンピンの両方
input bool            UseTimeFilter    = true;          // ロールオーバー前後は新規停止
input int             NoEntryFromHour  = 23;            // 新規停止の開始時(サーバー時間)
input int             NoEntryToHour    = 1;             // 新規停止の終了時(サーバー時間)
input int             FridayStopHour   = 20;            // 金曜この時刻以降は新規停止(24=無効)
input bool            ServerStops      = true;          // 証券会社側にも利確・損切りを置く
input double          MaxLotPerOrder   = 0.0;           // 1注文の最大ロット(0=制限なし)
input double          MaxDDStopPct     = 0.0;           // 残高ピークからこの%減ったら全決済して停止(0=無効)
input bool            ResetHalt        = false;         // 停止状態を解除する(一度trueで起動→falseに戻す)

//--- グローバル
CTrade   trade;
int      hRSI    = INVALID_HANDLE;
int      hAtrD1  = INVALID_HANDLE;
int      hTrend  = INVALID_HANDLE;

string   g_prefix        = "";
datetime g_lastMinute    = 0;
bool     g_closing[2]    = {false,false};
datetime g_lastAddTry[2] = {0,0};
datetime g_modFail[2]    = {0,0};
bool     g_halted        = false;
double   g_lastRSI       = 0.0;
string   g_lastNote      = "";
datetime g_lastPanel     = 0;

struct Basket
  {
   int      n;          // 本数
   double   lots;       // 合計ロット
   double   avg;        // 平均建値
   double   firstPrice; // 初回の建値
   double   firstLots;  // 初回のロット
   double   profit;     // 含み損益(スワップ込み)
   datetime lastTime;   // 最後に建てた時刻
  };

//+------------------------------------------------------------------+
//| 小物                                                             |
//+------------------------------------------------------------------+
int Idx(ENUM_POSITION_TYPE type) { return (type==POSITION_TYPE_BUY) ? 0 : 1; }

string GVName(string key) { return g_prefix+key; }

string ScaleKey(ENUM_POSITION_TYPE type) { return (type==POSITION_TYPE_BUY) ? "scB" : "scS"; }

double Pip() { return (_Digits==3 || _Digits==5) ? _Point*10.0 : _Point; }

bool GetBuf(int handle,int start,int count,double &out[])
  {
   ArraySetAsSeries(out,true);
   return (CopyBuffer(handle,0,start,count,out)==count);
  }

// 確定済みの日足 ATR(14)
double DailyATR()
  {
   double a[];
   if(!GetBuf(hAtrD1,1,1,a))
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

bool SpreadOK()
  {
   if(MaxSpreadPips<=0.0)
      return true;
   double spread=SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID);
   return (spread<=MaxSpreadPips*Pip()+_Point*0.5);
  }

//+------------------------------------------------------------------+
//| グリッドの形(すべて価格の幅で返す)                                 |
//+------------------------------------------------------------------+
// scale = バスケット開始時の日足ATR(幅の基準が pips の時は使わない)
double Step1(double scale)
  {
   if(StepBase==STEP_BASE_PIPS)
      return StepPips*Pip();
   return StepATR*scale;
  }

// 初回建値から j 回目のナンピン(j=0 は初回)までの距離
double LevelDist(int j,double scale)
  {
   double s=Step1(scale), off=0.0;
   for(int i=0;i<j;i++)
      off+=s*MathPow(StepGrow,i);
   return off;
  }

// 初回建値から「耐えるライン」までの距離 = 最後のナンピン + 次のナンピン幅 × SurviveSteps
double SurviveDist(double scale)
  {
   return LevelDist(MaxNanpin,scale)+SurviveSteps*Step1(scale)*MathPow(StepGrow,MaxNanpin);
  }

double TPDist(double scale) { return TPRatio*Step1(scale); }

//+------------------------------------------------------------------+
//| ロット                                                           |
//+------------------------------------------------------------------+
// 1.0 ロットで価格が dist 逆行した時の損失(口座通貨, 正の値)
double MoneyPerLot(double dist)
  {
   if(dist<=0.0)
      return 0.0;
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double pr=0.0, loss=0.0;
   if(ask>0.0 && OrderCalcProfit(ORDER_TYPE_BUY,_Symbol,1.0,ask,ask+dist,pr) && pr>0.0)
      loss=pr;
   else
     {
      double tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
      double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tv>0.0 && ts>0.0)
         loss=dist/ts*tv;
     }
   // 口座通貨が基軸通貨の時(ドル口座で USDJPY など)、損益は決済時の価格で口座通貨に直るので、
   // 下がった先の価格で割る分だけ損失が大きくなる。安全側に補正する
   if(AccountInfoString(ACCOUNT_CURRENCY)==SymbolInfoString(_Symbol,SYMBOL_CURRENCY_BASE) && bid-dist>0.0)
      loss*=bid/(bid-dist);
   return loss;
  }

double VolStep()
  {
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   return (step>0.0) ? step : 0.01;
  }

// ロットを証券会社の刻みにそろえる(四捨五入)。最小ロット未満は最小ロット、上限を超える分は上限まで
double RoundLot(double lot)
  {
   double step=VolStep();
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double mx=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(MaxLotPerOrder>0.0 && lot>MaxLotPerOrder)
      lot=MaxLotPerOrder;
   if(mx>0.0 && lot>mx)
      lot=mx;
   double v=MathRound(lot/step)*step;
   if(v<mn-1e-9)
      v=mn;
   return NormalizeDouble(v,8);
  }

// j 回目のナンピン(j=0 は初回)のロット
double LevelLot(double base,int j)
  {
   if(j==0)
      return RoundLot(base);
   return RoundLot(base*MathPow(LotMult,j));
  }

// 初回ロット base で全段入り、耐えるラインで決済した時の損失(口座通貨)
double LossAtSurvive(double base,double scale)
  {
   double surv=SurviveDist(scale), loss=0.0;
   for(int j=0;j<=MaxNanpin;j++)
      loss+=LevelLot(base,j)*MoneyPerLot(surv-LevelDist(j,scale));
   return loss;
  }

// 同じ損失を、ロットの丸めなしで計算(初回1ロットあたり)
double LossAtSurvivePerLot(double scale)
  {
   double surv=SurviveDist(scale), loss=0.0;
   for(int j=0;j<=MaxNanpin;j++)
      loss+=MathPow(LotMult,j)*MoneyPerLot(surv-LevelDist(j,scale));
   return loss;
  }

// 初回ロット。tooSmall=自動計算が最小ロット未満だった
double CalcBaseLot(double scale,bool &tooSmall)
  {
   tooSmall=false;
   if(FixedBaseLot>0.0)
      return RoundLot(FixedBaseLot);
   double per=LossAtSurvivePerLot(scale);
   if(per<=0.0)
      return 0.0;
   double budget=AccountInfoDouble(ACCOUNT_BALANCE)*RiskPct/100.0;
   double step=VolStep();
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double base=MathFloor(budget/per/step+1e-9)*step;
   // ロットの丸めで予算を超える時は、刻み1つずつ下げる
   for(int i=0;i<500 && base>=mn-1e-9;i++)
     {
      if(LossAtSurvive(base,scale)<=budget)
         break;
      base-=step;
     }
   if(base<mn-1e-9)
     {
      tooSmall=true;
      if(!UseMinLotIfSmall)
         return 0.0;
      return RoundLot(mn);
     }
   return RoundLot(base);
  }

// 最小ロットで入っても損失が RiskPct% に収まる残高(口座通貨)
double MinBalanceForMinLot(double scale)
  {
   if(RiskPct<=0.0)
      return 0.0;
   double mn=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   return LossAtSurvive(mn,scale)/(RiskPct/100.0);
  }

// 全段入った時の必要証拠金(口座通貨)
double MarginAllLevels(double base)
  {
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double m1=0.0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY,_Symbol,1.0,ask,m1))
      return 0.0;
   double lots=0.0;
   for(int j=0;j<=MaxNanpin;j++)
      lots+=LevelLot(base,j);
   return m1*lots;
  }

//+------------------------------------------------------------------+
//| バスケット(同じ向きのポジションのまとまり)                          |
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
      Print("NanpinFX: 証拠金不足のため注文を見送り lot=",DoubleToString(lot,2));
      return false;
     }
   bool ok=(type==POSITION_TYPE_BUY) ? trade.Buy(lot,_Symbol,0.0,0.0,0.0,cmt) : trade.Sell(lot,_Symbol,0.0,0.0,0.0,cmt);
   uint rc=trade.ResultRetcode();
   if(!ok || (rc!=TRADE_RETCODE_DONE && rc!=TRADE_RETCODE_DONE_PARTIAL && rc!=TRADE_RETCODE_PLACED))
     {
      Print("NanpinFX: 注文失敗 ",cmt," lot=",DoubleToString(lot,2)," ",rc," ",trade.ResultRetcodeDescription());
      return false;
     }
   Print("NanpinFX: 発注 ",cmt," ",(type==POSITION_TYPE_BUY ? "BUY " : "SELL "),DoubleToString(lot,2));
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
         Print("NanpinFX: 決済失敗(",why,") #",tk," ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
     }
  }

// 証券会社側の TP/SL をバスケットの値にそろえる(sl=0 なら損切りは置かない)
void SyncStops(ENUM_POSITION_TYPE type,double sl,double tp)
  {
   int ix=Idx(type);
   if(TimeCurrent()-g_modFail[ix]<15)
      return;
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double minDist=((double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)+2.0)*_Point;
   double tol=MathMax(_Point,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE))*1.5;
   if(sl>0.0)
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
         if(newSL>0.0 && newSL>bid-minDist) newSL=curSL;
        }
      else
        {
         if(newTP>ask-minDist) newTP=curTP;
         if(newSL>0.0 && newSL<ask+minDist) newSL=curSL;
        }
      if(MathAbs(newSL-curSL)<tol && MathAbs(newTP-curTP)<tol)
         continue;
      if(!trade.PositionModify(tk,newSL,newTP))
        {
         g_modFail[ix]=TimeCurrent();
         Print("NanpinFX: TP/SL変更失敗 #",tk," ",trade.ResultRetcode()," ",trade.ResultRetcodeDescription());
         return;
        }
     }
  }

// バスケット開始時の日足ATR(幅の基準)。なければ今の値を記録して使う
double BasketScale(ENUM_POSITION_TYPE type)
  {
   string key=GVName(ScaleKey(type));
   double sc=GlobalVariableCheck(key) ? GlobalVariableGet(key) : 0.0;
   if(sc<=0.0)
     {
      sc=DailyATR();
      if(sc>0.0)
         GlobalVariableSet(key,sc);
     }
   return sc;
  }

// 毎ティック: 利確・耐えるラインでの決済・ナンピン・TP/SL同期
void ManageBasket(ENUM_POSITION_TYPE type)
  {
   int ix=Idx(type);
   Basket b;
   ReadBasket(type,b);
   string key=GVName(ScaleKey(type));
   if(b.n==0)
     {
      g_closing[ix]=false;
      if(GlobalVariableCheck(key))
         GlobalVariableDel(key);
      return;
     }
   if(g_closing[ix])
     {
      CloseBasket(type,"再試行");
      return;
     }
   double scale=BasketScale(type);
   if(StepBase==STEP_BASE_ATR && scale<=0.0)
      return;
   double dir=(type==POSITION_TYPE_BUY) ? 1.0 : -1.0;
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double exitPx=(type==POSITION_TYPE_BUY) ? bid : ask;   // 決済される側の価格
   double addPx =(type==POSITION_TYPE_BUY) ? ask : bid;   // 追加で建つ側の価格
   double tpPrice=b.avg+dir*TPDist(scale);
   double survPrice=b.firstPrice-dir*SurviveDist(scale);

   bool hitTP=(dir>0.0) ? (exitPx>=tpPrice) : (exitPx<=tpPrice);
   bool hitSurv=(dir>0.0) ? (exitPx<=survPrice) : (exitPx>=survPrice);
   if(hitTP)
     {
      Print("NanpinFX: 利確 ",(dir>0.0 ? "BUY" : "SELL")," 本数=",b.n," 損益=",DoubleToString(b.profit,2));
      CloseBasket(type,"TP");
      return;
     }
   if(hitSurv && CutAtSurvive)
     {
      Print("NanpinFX: 耐えるラインに到達。全決済 ",(dir>0.0 ? "BUY" : "SELL")," 本数=",b.n," 損益=",DoubleToString(b.profit,2));
      CloseBasket(type,"SURVIVE");
      return;
     }
   // ナンピン(耐えるラインを越えた後は追加しない)
   if(b.n<=MaxNanpin && !g_halted && !hitSurv)
     {
      double levelPrice=b.firstPrice-dir*LevelDist(b.n,scale);
      bool reach=(dir>0.0) ? (addPx<=levelPrice) : (addPx>=levelPrice);
      long minGap=(long)NanpinMinMinutes*60;
      if(reach && (long)(TimeCurrent()-b.lastTime)>=minGap && TimeCurrent()-g_lastAddTry[ix]>=5 && SpreadOK())
        {
         g_lastAddTry[ix]=TimeCurrent();
         double base=b.firstLots;
         double lot=LevelLot(base,b.n);
         if(OpenOrder(type,lot,"NF-"+IntegerToString(b.n)))
            return;   // 次のティックで平均建値を取り直す
        }
     }
   if(ServerStops)
      SyncStops(type,CutAtSurvive ? survPrice : 0.0,tpPrice);
  }

//+------------------------------------------------------------------+
//| 新規エントリー                                                    |
//+------------------------------------------------------------------+
bool TimeOK()
  {
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

// 確定済みの足で、買い・売りそれぞれ入ってよいか
void EntrySignals(bool &buy,bool &sell)
  {
   buy=false;
   sell=false;
   if(EntryMode==ENTRY_ALWAYS)
     {
      buy=true;
      sell=true;
     }
   else
     {
      double r[];
      if(!GetBuf(hRSI,1,1,r))
         return;
      g_lastRSI=r[0];
      buy=(r[0]<RSI_BuyBelow);
      sell=(r[0]>RSI_SellAbove);
     }
   if(TrendMAPeriod>0 && (buy || sell))
     {
      double e[];
      double c1=iClose(_Symbol,PERIOD_D1,1);
      if(!GetBuf(hTrend,1,1,e) || c1<=0.0)
        {
         buy=false;
         sell=false;
         return;
        }
      if(c1<=e[0]) buy=false;
      if(c1>=e[0]) sell=false;
     }
  }

void OpenFirst(ENUM_POSITION_TYPE type)
  {
   double scale=DailyATR();
   if(StepBase==STEP_BASE_ATR && scale<=0.0)
      return;
   bool tooSmall=false;
   double lot=CalcBaseLot(scale,tooSmall);
   if(lot<=0.0)
     {
      g_lastNote="残高が小さく、最小ロットでも損失が RiskPct を超えるため見送り";
      return;
     }
   if(tooSmall)
      Print("NanpinFX: 自動ロットが最小未満のため最小ロットで発注。耐えるラインでの損失=残高の",
            DoubleToString(LossAtSurvive(lot,scale)/AccountInfoDouble(ACCOUNT_BALANCE)*100.0,1),"%");
   GlobalVariableSet(GVName(ScaleKey(type)),scale);
   if(OpenOrder(type,lot,"NF-0"))
      g_lastNote="";
  }

// 1分足が替わるたびに1回
void CheckEntry()
  {
   if(g_halted)
      return;
   bool buy=false, sell=false;
   EntrySignals(buy,sell);
   if(!buy && !sell)
      return;
   if(!TimeOK())
     {
      g_lastNote="時間フィルターで見送り";
      return;
     }
   if(!SpreadOK())
     {
      g_lastNote="スプレッド拡大で見送り";
      return;
     }
   Basket bb, sb;
   ReadBasket(POSITION_TYPE_BUY,bb);
   ReadBasket(POSITION_TYPE_SELL,sb);
   if(buy && bb.n==0 && !g_closing[0] && (BothSides || (sb.n==0 && !g_closing[1])))
     {
      OpenFirst(POSITION_TYPE_BUY);
      ReadBasket(POSITION_TYPE_BUY,bb);
     }
   if(sell && sb.n==0 && !g_closing[1] && (BothSides || (bb.n==0 && !g_closing[0])))
      OpenFirst(POSITION_TYPE_SELL);
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
      Alert("NanpinFX: 残高ピークから ",DoubleToString(MaxDDStopPct,0),"% 減少。全決済して停止しました (",_Symbol,")");
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
   string key=GVName(ScaleKey(type));
   double scale=GlobalVariableCheck(key) ? GlobalVariableGet(key) : DailyATR();
   double dir=(type==POSITION_TYPE_BUY) ? 1.0 : -1.0;
   double tpPrice=b.avg+dir*TPDist(scale);
   double survPrice=b.firstPrice-dir*SurviveDist(scale);
   string txt=label+": ナンピン "+IntegerToString(b.n-1)+"/"+IntegerToString(MaxNanpin)+"回  "+DoubleToString(b.lots,2)+"ロット  含み "+DoubleToString(b.profit,2)+"\n";
   txt+="   平均 "+DoubleToString(b.avg,_Digits)+"  利確 "+DoubleToString(tpPrice,_Digits)+"  耐えるライン "+DoubleToString(survPrice,_Digits)+"\n";
   if(b.n<=MaxNanpin)
      txt+="   次のナンピン "+DoubleToString(b.firstPrice-dir*LevelDist(b.n,scale),_Digits)+"  ロット "+DoubleToString(LevelLot(b.firstLots,b.n),2)+"\n";
   return txt;
  }

void UpdatePanel()
  {
   if(!ShowPanel)
      return;
   if(TimeCurrent()==g_lastPanel)
      return;
   g_lastPanel=TimeCurrent();
   double scale=DailyATR();
   bool tooSmall=false;
   double lot=(StepBase==STEP_BASE_PIPS || scale>0.0) ? CalcBaseLot(scale,tooSmall) : 0.0;
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   string txt="NanpinFX  "+_Symbol+"  "+AccountInfoString(ACCOUNT_CURRENCY)+"\n";
   if(g_halted)
      txt+="★ 停止中(DD上限)。ResetHalt=true で解除\n";
   txt+="日足ATR "+DoubleToString(scale/Pip(),1)+"pips  1回目の幅 "+DoubleToString(Step1(scale)/Pip(),1)+"pips  利確 "+DoubleToString(TPDist(scale)/Pip(),1)+"pips\n";
   txt+="ナンピン"+IntegerToString(MaxNanpin)+"回目まで "+DoubleToString(LevelDist(MaxNanpin,scale)/Pip(),0)+"pips  耐えるライン "+DoubleToString(SurviveDist(scale)/Pip(),0)+"pips 逆行\n";
   if(lot>0.0)
     {
      double loss=LossAtSurvive(lot,scale);
      txt+="次の初回ロット "+DoubleToString(lot,2)+"  最終ロット "+DoubleToString(LevelLot(lot,MaxNanpin),2)+"  耐えるラインでの損失 "+DoubleToString(loss,0)+"("+DoubleToString((bal>0.0) ? loss/bal*100.0 : 0.0,1)+"%)\n";
      txt+="全段入った時の必要証拠金 "+DoubleToString(MarginAllLevels(lot),0)+"\n";
     }
   else
      txt+="次の初回ロット: 残高不足(最小ロットでも損失が "+DoubleToString(RiskPct,0)+"% を超える)\n";
   if(FixedBaseLot<=0.0 && (StepBase==STEP_BASE_PIPS || scale>0.0))
      txt+="最小ロットで動かすのに必要な残高 "+DoubleToString(MinBalanceForMinLot(scale),0)+"\n";
   if(EntryMode==ENTRY_RSI)
      txt+="RSI "+DoubleToString(g_lastRSI,1)+"(買い<"+DoubleToString(RSI_BuyBelow,0)+" / 売り>"+DoubleToString(RSI_SellAbove,0)+")\n";
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
      Alert("NanpinFX: ヘッジ口座専用です(この口座はネッティング方式のため動かせません)");
      return INIT_FAILED;
     }
   if(MaxNanpin<0 || MaxNanpin>30 || LotMult<1.0 || StepGrow<=0.0 || StepATR<=0.0 || StepPips<=0.0 ||
      TPRatio<=0.0 || SurviveSteps<0.0 || RSI_Period<2 || RSI_BuyBelow>=RSI_SellAbove || TrendMAPeriod<0 ||
      NanpinMinMinutes<0 || (FixedBaseLot<=0.0 && RiskPct<=0.0) || RiskPct>100.0)
     {
      Alert("NanpinFX: パラメータが不正です。値を見直してください");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_prefix="NF_"+IntegerToString(MagicNumber)+"_"+_Symbol+"_";
   trade.SetExpertMagicNumber((ulong)MagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   hRSI  =iRSI(_Symbol,RSI_TF,RSI_Period,PRICE_CLOSE);
   hAtrD1=iATR(_Symbol,PERIOD_D1,14);
   if(TrendMAPeriod>0)
      hTrend=iMA(_Symbol,PERIOD_D1,TrendMAPeriod,0,MODE_EMA,PRICE_CLOSE);
   if(hRSI==INVALID_HANDLE || hAtrD1==INVALID_HANDLE || (TrendMAPeriod>0 && hTrend==INVALID_HANDLE))
     {
      Alert("NanpinFX: インジケーターの作成に失敗しました");
      return INIT_FAILED;
     }
   if(ResetHalt)
     {
      GlobalVariableDel(GVName("halt"));
      GlobalVariableDel(GVName("peak"));
     }
   g_halted=GlobalVariableCheck(GVName("halt"));
   g_lastMinute=0;
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(hRSI!=INVALID_HANDLE)   IndicatorRelease(hRSI);
   if(hAtrD1!=INVALID_HANDLE) IndicatorRelease(hAtrD1);
   if(hTrend!=INVALID_HANDLE) IndicatorRelease(hTrend);
   Comment("");
  }

void OnTick()
  {
   CheckAccountStop();
   ManageBasket(POSITION_TYPE_BUY);
   ManageBasket(POSITION_TYPE_SELL);
   datetime m=iTime(_Symbol,PERIOD_M1,0);
   if(m!=0 && m!=g_lastMinute)
     {
      g_lastMinute=m;
      CheckEntry();
     }
   UpdatePanel();
  }
//+------------------------------------------------------------------+
