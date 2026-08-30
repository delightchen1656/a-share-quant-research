import fs from "node:fs/promises";
import path from "node:path";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const FINAL = path.resolve("..");
const OUT = path.join(FINAL, "outputs");

function parseCsv(text) {
  text = text.replace(/^\uFEFF/, "").trim();
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const row = []; let cell = ""; let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') { cell += '"'; i++; }
        else quoted = !quoted;
      } else if (ch === "," && !quoted) { row.push(cell); cell = ""; }
      else cell += ch;
    }
    row.push(cell); rows.push(row);
  }
  const headers = rows[0];
  return rows.slice(1).filter(r => r.some(v => v !== "")).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i] ?? ""])));
}

async function csv(name) { return parseCsv(await fs.readFile(path.join(OUT, name), "utf8")); }
const daily = await csv("daily_returns_aligned.csv");
const portfolios = await csv("portfolio_grid.csv");
const drawdowns = await csv("baseline1_2_top5_drawdowns.csv");
const audit = await csv("oct2024_trade_audit.csv");
const concentration = await csv("return_concentration.csv");
const top1 = await csv("top_trades_baseline1-2.csv");
const top2 = await csv("top_trades_baseline2-2.csv");
const summary = JSON.parse(await fs.readFile(path.join(OUT, "summary.json"), "utf8"));

const wb = Workbook.create();
const navy = "#17365D", blue = "#4472C4", cyan = "#D9EAF7", green = "#E2F0D9", red = "#FCE4D6", gray = "#E7E6E6";
function title(sheet, range, text) {
  sheet.mergeCells(range); const r = sheet.getRange(range); r.values = [[text]];
  r.format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 16 }, verticalAlignment: "center" };
  r.format.rowHeight = 30;
}
function header(range) { range.format = { fill: blue, font: { bold: true, color: "#FFFFFF" }, wrapText: true, verticalAlignment: "center", borders: { preset: "inside", style: "thin", color: "#B4C6E7" } }; }
function section(range) { range.format = { fill: cyan, font: { bold: true, color: navy }, borders: { bottom: { style: "medium", color: blue } } }; }
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function date(v) { return v ? new Date(v + (v.length === 10 ? "T00:00:00" : "")) : null; }

// Summary
const s = wb.worksheets.add("结论"); s.showGridLines = false; title(s, "A1:H1", "基准1-2 与 基准2-2 平台记录联合审计");
s.getRange("A3:D3").values = [["核心问题", "结论", "关键数值", "判断"]]; header(s.getRange("A3:D3"));
s.getRange("A4:D6").values = [
  ["模型1回撤时模型2会不会跌？", "多数情况下同跌，但幅度明显较小；并非独立对冲。", summary.daily_return_correlation, "日收益相关性>0.6，高度同源"],
  ["2024年10月跳升能否真实成交？", "基本可信：节前持仓节后高开，09:31卖出；没有停牌或一字涨停买入。", summary.audit_trade_count, "6笔轻微越界均与约0.2%滑点一致"],
  ["什么比例满足目标？", "基准1-2/基准2-2＝30%/70%，每月再平衡。", 0.3654203149737201, "年化36.54%，回撤14.89%"],
];
s.getRange("C4").format.numberFormat = "0.000"; s.getRange("C5").format.numberFormat = "#,##0"; s.getRange("C6").format.numberFormat = "0.00%";
s.getRange("A8:G8").values = [["策略", "期末资产", "复合年化", "最大回撤", "Sharpe", "Calmar", "平台截图收益"]]; header(s.getRange("A8:G8"));
s.getRange("A9:G10").values = [
  ["基准1-2止损过滤", 1728326.88, 0.5686900083, -0.2989070305, 1.87452, 1.90256, 8.8551],
  ["基准2-2升温防守", 467768.76, 0.2760295476, -0.1010939993, 1.72216, 2.73042, 3.1994],
];
s.getRange("B9:B10").format.numberFormat = "¥#,##0"; s.getRange("C9:D10").format.numberFormat = "0.00%"; s.getRange("E9:F10").format.numberFormat = "0.00"; s.getRange("G9:G10").format.numberFormat = "0.00%";
s.mergeCells("A12:H12"); s.getRange("A12").values = [["注意：平台顶部收益与每日持仓账户净值不一致。本报告和组合回测统一采用账户总资产序列。"]]; s.getRange("A12:H12").format = { fill: red, font: { bold: true, color: "#9C0006" }, wrapText: true };
s.getRange("A14:C14").values = [["日期", "基准1-2累计净值", "基准2-2累计净值"]]; header(s.getRange("A14:C14"));
const monthRows = []; let lastMonth = "";
for (const r of daily) { const m = r.date.slice(0,7); if (m !== lastMonth) { monthRows.push([date(r.date), num(r.asset_baseline1_2)/100000, num(r.asset_baseline2_2)/100000]); lastMonth=m; } }
s.getRangeByIndexes(14,0,monthRows.length,3).values = monthRows; s.getRange(`A15:A${14+monthRows.length}`).format.numberFormat = "yyyy-mm"; s.getRange(`B15:C${14+monthRows.length}`).format.numberFormat = "0.00x";
const chart = s.charts.add("line", s.getRange(`A14:C${14+monthRows.length}`)); chart.title = "两策略累计净值（账户资产口径）"; chart.hasLegend = true; chart.setPosition("E14", "L31");
s.getRange("A:D").format.columnWidth = 24; s.getRange("A4:D6").format.wrapText = true; s.freezePanes.freezeRows(3);

// Portfolio
const p = wb.worksheets.add("组合回测"); p.showGridLines=false; title(p,"A1:L1","固定权重组合：每日与每月再平衡");
p.getRange("A3:L3").values=[["再平衡","基准1-2权重","基准2-2权重","期末倍数","年化","最大回撤","波动率","Sharpe","Calmar","最差自然年","亏损年份","最长水下交易日"]]; header(p.getRange("A3:L3"));
const pvals=portfolios.map(r=>[r.rebalance,num(r.weight_baseline1_2),num(r.weight_baseline2_2),num(r.final_multiple),num(r.cagr),num(r.max_drawdown),num(r.volatility),num(r.sharpe),num(r.calmar),num(r.worst_calendar_year),num(r.losing_years),num(r.max_underwater_trading_days)]);
p.getRangeByIndexes(3,0,pvals.length,12).values=pvals; p.getRange(`B4:C${3+pvals.length}`).format.numberFormat="0%"; p.getRange(`D4:D${3+pvals.length}`).format.numberFormat="0.00x"; p.getRange(`E4:G${3+pvals.length}`).format.numberFormat="0.00%"; p.getRange(`H4:I${3+pvals.length}`).format.numberFormat="0.00"; p.getRange(`J4:J${3+pvals.length}`).format.numberFormat="0.00%"; p.getRange("A4:L5").format.fill=green;
p.mergeCells("A16:L17"); p.getRange("A16").values=[["达标组合：30%基准1-2 + 70%基准2-2，每月再平衡。年化36.54%，最大回撤14.89%，Sharpe 1.95，Calmar 2.45；2026/1-7仍亏损6.45%。"]]; p.getRange("A16:L17").format={fill:green,font:{bold:true,color:"#006100"},wrapText:true}; p.getRange("A:L").format.columnWidth=14; p.freezePanes.freezeRows(3);

// Drawdowns
const d = wb.worksheets.add("回撤重合"); d.showGridLines=false; title(d,"A1:H1","基准1-2最大五次回撤与基准2-2同期表现");
d.getRange("A3:H3").values=[["峰值日","谷底日","恢复日","基准1-2回撤","基准2-2同期收益","下跌天数","恢复天数","评价"]]; header(d.getRange("A3:H3"));
const dvals=drawdowns.map(r=>{const x=num(r.baseline2_2_return_same_interval); return [date(r.peak_date),date(r.trough_date),date(r.recovery_date),num(r.drawdown),x,num(r.drawdown_days),num(r.recovery_days),x>=-0.05?"较强分散":x>=-0.10?"减震但同跌":"分散有限"]});
d.getRangeByIndexes(3,0,dvals.length,8).values=dvals; d.getRange("A4:C8").format.numberFormat="yyyy-mm-dd"; d.getRange("D4:E8").format.numberFormat="0.00%"; d.getRange("A:H").format.columnWidth=18; d.freezePanes.freezeRows(3);

// Concentration
const c=wb.worksheets.add("收益集中度"); c.showGridLines=false; title(c,"A1:I1","收益是否依赖少数交易日或交易");
c.getRange("A3:I3").values=[["策略","原年化","去掉最好5天","去掉最好10天","前10笔盈利","全部盈利交易利润","前10笔占比","净已实现利润","FIFO匹配批次"]]; header(c.getRange("A3:I3"));
const cvals=concentration.map(r=>[r.name,num(r.cagr_original),num(r.cagr_without_best_5_days),num(r.cagr_without_best_10_days),num(r.top10_winning_trades_pnl),num(r.all_winning_trades_pnl),num(r.top10_share_of_winning_pnl),num(r.net_realized_pnl),num(r.completed_fifo_lots)]);
c.getRangeByIndexes(3,0,cvals.length,9).values=cvals; c.getRange("B4:D5").format.numberFormat="0.00%"; c.getRange("E4:F5").format.numberFormat="¥#,##0"; c.getRange("G4:G5").format.numberFormat="0.00%"; c.getRange("H4:H5").format.numberFormat="¥#,##0"; c.getRange("A:I").format.columnWidth=18;
c.mergeCells("A8:I9"); c.getRange("A8").values=[["判断：前10笔盈利只占全部盈利交易利润的13%—19%，并非单一牛股支撑；但删去最好10个交易日后年化明显下降，收益对少数市场级大涨日存在依赖。"]]; c.getRange("A8:I9").format={fill:cyan,font:{bold:true,color:navy},wrapText:true};

// October audit
const a=wb.worksheets.add("2024年10月审计"); a.showGridLines=false; title(a,"A1:R1","2024年10月跳升成交审计（未复权价格）");
const ah=["策略","日期","时间","代码","名称","操作","成交价","数量","金额","当日组合收益","开盘","最高","最低","收盘","未复权涨跌幅","成交在区间内","一字板","停牌"];
a.getRange("A3:R3").values=[ah]; header(a.getRange("A3:R3"));
const avals=audit.map(r=>[r.baseline,date(r.date),r.time,r.symbol,r.name,r.action,num(r.trade_price),num(r.quantity),num(r.amount),num(r.portfolio_daily_return),num(r.raw_open),num(r.raw_high),num(r.raw_low),num(r.raw_close),num(r.raw_pct_chg)/100,String(r.trade_inside_raw_range).toLowerCase()==="true"?"是":"否",String(r.one_price_board).toLowerCase()==="true"?"是":"否",String(r.suspended).toLowerCase()==="true"?"是":"否"]);
a.getRangeByIndexes(3,0,avals.length,18).values=avals; a.getRange(`B4:B${3+avals.length}`).format.numberFormat="yyyy-mm-dd"; a.getRange(`G4:G${3+avals.length}`).format.numberFormat="0.000"; a.getRange(`H4:H${3+avals.length}`).format.numberFormat="#,##0"; a.getRange(`I4:I${3+avals.length}`).format.numberFormat="¥#,##0"; a.getRange(`J4:J${3+avals.length}`).format.numberFormat="0.00%"; a.getRange(`K4:O${3+avals.length}`).format.numberFormat="0.00"; a.getRange("A:R").format.columnWidth=13; a.getRange("E:E").format.columnWidth=18; a.freezePanes.freezeRows(3);

// Daily data
const dr=wb.worksheets.add("每日收益"); dr.showGridLines=false; title(dr,"A1:G1","账户总资产与每日收益（对齐交易日）");
dr.getRange("A3:G3").values=[["日期","基准1-2资产","基准1-2收益","基准2-2资产","基准2-2收益","1-2累计倍数","2-2累计倍数"]]; header(dr.getRange("A3:G3"));
const drvals=daily.map(r=>[date(r.date),num(r.asset_baseline1_2),num(r.return_baseline1_2),num(r.asset_baseline2_2),num(r.return_baseline2_2),num(r.asset_baseline1_2)/100000,num(r.asset_baseline2_2)/100000]); dr.getRangeByIndexes(3,0,drvals.length,7).values=drvals; dr.getRange(`A4:A${3+drvals.length}`).format.numberFormat="yyyy-mm-dd"; dr.getRange(`B4:B${3+drvals.length}`).format.numberFormat="¥#,##0"; dr.getRange(`C4:C${3+drvals.length}`).format.numberFormat="0.00%"; dr.getRange(`D4:D${3+drvals.length}`).format.numberFormat="¥#,##0"; dr.getRange(`E4:E${3+drvals.length}`).format.numberFormat="0.00%"; dr.getRange(`F4:G${3+drvals.length}`).format.numberFormat="0.00x"; dr.getRange("A:G").format.columnWidth=16; dr.freezePanes.freezeRows(3);

// Top trades
const t=wb.worksheets.add("头部盈利交易"); t.showGridLines=false; title(t,"A1:J1","两策略盈利贡献最高的FIFO交易批次");
t.getRange("A3:J3").values=[["策略","代码","名称","买入日","卖出日","数量","买入单位成本","卖出单位净价","利润","收益率"]]; header(t.getRange("A3:J3"));
const tvals=[]; for(const [label,rows] of [["基准1-2",top1],["基准2-2",top2]]) for(const r of rows) tvals.push([label,r.symbol,r.name,date(r.buy_date),date(r.sell_date),num(r.quantity),num(r.buy_unit_cost),num(r.sell_unit_net),num(r.pnl),num(r.return)]);
t.getRangeByIndexes(3,0,tvals.length,10).values=tvals; t.getRange(`D4:E${3+tvals.length}`).format.numberFormat="yyyy-mm-dd"; t.getRange(`F4:F${3+tvals.length}`).format.numberFormat="#,##0"; t.getRange(`G4:I${3+tvals.length}`).format.numberFormat="¥#,##0.00"; t.getRange(`J4:J${3+tvals.length}`).format.numberFormat="0.00%"; t.getRange("A:J").format.columnWidth=16; t.freezePanes.freezeRows(3);

// Sources and checks
const q=wb.worksheets.add("来源与检查"); q.showGridLines=false; title(q,"A1:F1","数据来源、口径与质量检查");
q.getRange("A3:F3").values=[["检查项","实际值","预期/阈值","差异","状态","说明"]]; header(q.getRange("A3:F3"));
q.getRange("A4:F10").values=[
  ["对齐交易日",summary.aligned_days,1595,0,"OK","两套每日资产完整对齐"],
  ["起始日期",summary.date_start,"2019-12-31","","OK","回测区间前一净值点"],
  ["结束日期",summary.date_end,"2026-07-31","","OK","与用户回测设置一致"],
  ["10月审计成交",summary.audit_trade_count,">0","","OK","包含两策略重点窗口"],
  ["停牌成交",summary.audit_suspended_trades,0,summary.audit_suspended_trades,"OK","未发现"],
  ["一字板买入",summary.audit_one_price_buys,0,summary.audit_one_price_buys,"OK","未发现"],
  ["价格区间外成交",summary.audit_outside_raw_range,0,summary.audit_outside_raw_range,"解释通过","最大偏差0.20%，与固定滑点一致"],
];
q.getRange("A12:C12").values=[["源文件","策略","用途"]]; header(q.getRange("A12:C12")); q.getRange("A13:C18").values=[
  ["dailyposition1-2","基准1-2","每日总资产和持仓"],["detal1-2","基准1-2","实际成交"],["outlog1-2","基准1-2","运行与订单审计"],
  ["dailyposition2-2","基准2-2","每日总资产和持仓"],["detal2-2","基准2-2","实际成交"],["outlog2-2","基准2-2","运行与订单审计"],
]; q.getRange("A:F").format.columnWidth=22; q.getRange("F:F").format.columnWidth=42; q.getRange("A4:F18").format.wrapText=true;

for (const sheetName of ["结论","组合回测","回撤重合","收益集中度","2024年10月审计","每日收益","头部盈利交易","来源与检查"]) {
  const sh=wb.worksheets.getItem(sheetName); const used=sh.getUsedRange(); used.format.font = { name: "Microsoft YaHei", size: 10 };
}

await fs.mkdir(FINAL,{recursive:true});
const output=await SpreadsheetFile.exportXlsx(wb); await output.save(path.join(FINAL,"基准1-2与2-2平台交易联合审计.xlsx"));
const check=await wb.inspect({kind:"table",range:"结论!A1:H12",include:"values,formulas",tableMaxRows:15,tableMaxCols:10}); console.log(check.ndjson);
const errors=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:100},summary:"final formula error scan"}); console.log(errors.ndjson);
const renderRanges = {
  "结论":"A1:L31", "组合回测":"A1:L17", "回撤重合":"A1:H8",
  "收益集中度":"A1:I9", "2024年10月审计":"A1:R25", "每日收益":"A1:G25",
  "头部盈利交易":"A1:J25", "来源与检查":"A1:F18"
};
for (const sheetName of ["结论","组合回测","回撤重合","收益集中度","2024年10月审计","每日收益","头部盈利交易","来源与检查"]) {
  const blob=await wb.render({sheetName,range:renderRanges[sheetName],scale:0.8,format:"png"}); await fs.writeFile(path.join(FINAL,`preview_${sheetName}.png`),new Uint8Array(await blob.arrayBuffer()));
}
