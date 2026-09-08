const pptxgen = require("pptxgenjs");
const path = require("path");

// 方案A · 工业青蓝 — replaces the earlier dark-instrumentation palette wholesale.
const INK = "16465A"; // cover dark (P1, P17)
const SECTION = "123B4D"; // section-break dark (P7, P14) — deeper than cover
const NAVY = "1B4F63"; // card/panel fill on dark backgrounds
const TEAL = "16A6C4"; // primary teal — chapter 01, general accents, bright-on-dark uses
const TEAL_LT = "087F99"; // deep teal — chapter 03 badge/accent on light pages
const AMBER = "F2A20B";
const RUST = "D55D55";
const PAPER = "F4F7F8";
const CARD = "FFFFFF";
const TXT = "183C4C"; // primary text / headings on light backgrounds
const MUTE = "405866"; // body text on light backgrounds
const INV_MUTE = "B9CDD6"; // secondary text on dark backgrounds
const STRONG_DARK = "F6FAFC"; // primary text directly on dark page backgrounds
const GREEN = "34A879";
const TINT_TEAL = "EAF6F8"; // light-teal card fill — important/reference cards
const TINT_AMBER = "FFF6DF"; // light-amber card fill — key conclusions
const TINT_RUST = "FFF0EE"; // light-red card fill — risk/failure cards

// Design-exploration font pass — HarmonyOS Sans SC (locally installed).
// NOTE: swap HEAD/BODY back to "Microsoft YaHei" before the file that actually
// gets submitted — it is not preinstalled on judges' machines and its
// license forbids subsetting, so embedding it would blow the 20M cap.
const HEAD = "HarmonyOS Sans SC";
const BODY = "HarmonyOS Sans SC";
const MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "IndusOpt";
pres.title = "IndusOpt 项目简介 — A14 初赛提交";

const W = 13.3;
const H = 7.5;
const M = 0.7;
const ASSETS = path.join(__dirname, "..", "assets");
const SHOTS = path.join(__dirname, "..", "..", "..", "artifacts", "layout-refactor");

const CHAPTERS = [TEAL, AMBER, TEAL_LT, RUST];

function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: INK };
  return s;
}
function sectionSlide() {
  const s = pres.addSlide();
  s.background = { color: SECTION };
  return s;
}
function lightSlide() {
  const s = pres.addSlide();
  s.background = { color: PAPER };
  return s;
}

function badge(s, n, color) {
  s.addShape(pres.ShapeType.ellipse, { x: M, y: 0.52, w: 0.52, h: 0.52, fill: { color } });
  s.addText(String(n), {
    x: M, y: 0.52, w: 0.52, h: 0.52, align: "center", valign: "middle",
    fontFace: HEAD, fontSize: 18, bold: true, color: "FFFFFF", margin: 0,
  });
}

function pageTitle(s, text, fontSize, color) {
  s.addText(text, {
    x: M + 0.75, y: 0.4, w: W - M * 2 - 0.75, h: 0.6,
    fontFace: HEAD, fontSize: fontSize || 22, bold: true, color: color || TXT, margin: 0, valign: "middle",
  });
}

// chapterIdx: 0-3, draws a 4-segment progress strip so evaluators always know where they are.
// dark: true on section-break pages (P7/P14) so the divider line, footer text and the
// "future" chapter segment stay legible against the SECTION background.
function footer(s, n, chapterIdx, dark) {
  const lineColor = dark ? "2A5A6E" : "DDE6EA";
  const textColor = dark ? INV_MUTE : MUTE;
  const futureColor = dark ? "2A5A6E" : "DDE6EA";
  s.addShape(pres.ShapeType.line, { x: M, y: H - 0.5, w: W - 2 * M, h: 0, line: { color: lineColor, width: 0.75 } });
  s.addText("IndusOpt · A14 项目简介", {
    x: M, y: H - 0.42, w: 5, h: 0.3, fontFace: BODY, fontSize: 10, color: textColor, margin: 0,
  });
  s.addText(String(n), {
    x: W - M - 1, y: H - 0.42, w: 1, h: 0.3, align: "right", fontFace: BODY, fontSize: 10, color: textColor, margin: 0,
  });
  if (chapterIdx !== undefined) {
    const segW = 0.55, gap = 0.08, totalW = 4 * segW + 3 * gap;
    const startX = W - M - 1 - 0.15 - totalW;
    for (let i = 0; i < 4; i++) {
      s.addShape(pres.ShapeType.roundRect, {
        x: startX + i * (segW + gap), y: H - 0.6, w: segW, h: 0.06, rectRadius: 0.03,
        fill: { color: i <= chapterIdx ? CHAPTERS[i] : futureColor },
      });
    }
  }
}

// card-style panel for dark (SECTION) backgrounds — mirrors card() but tuned for dark contexts
function darkCard(s, opt) {
  s.addShape(pres.ShapeType.roundRect, {
    x: opt.x, y: opt.y, w: opt.w, h: opt.h, rectRadius: opt.r !== undefined ? opt.r : 0.08,
    fill: { color: opt.fill || NAVY }, line: { color: opt.line || "2A5A6E", width: opt.lineW !== undefined ? opt.lineW : 1 },
  });
}

function card(s, opt) {
  s.addShape(pres.ShapeType.roundRect, {
    x: opt.x, y: opt.y, w: opt.w, h: opt.h, rectRadius: opt.r !== undefined ? opt.r : 0.08,
    fill: { color: opt.fill || CARD }, line: { color: opt.line || "E2E8ED", width: opt.lineW !== undefined ? opt.lineW : 1 },
  });
}

/* ================================================================= P1 cover */
{
  const s = darkSlide();

  // 65:35 split — left = brand + copy + KPIs, right = floating mark
  const leftW = 0.65 * (W - 2 * M), leftX = M;
  const rightX = leftX + leftW, rightW = (W - 2 * M) - leftW, rightCx = rightX + rightW / 2;

  // --- background texture: ultra-faint grid + sweeping waveform + loop arcs/nodes — drawn
  // first so it sits behind everything else. Kept deliberately weak (4-10% opacity).
  const texColor = TEAL;
  for (let gx = 0; gx <= W; gx += 0.95) {
    s.addShape(pres.ShapeType.line, { x: gx, y: 0, w: 0, h: H, line: { color: texColor, width: 0.5, transparency: 96 } });
  }
  for (let gy = 0; gy <= H; gy += 0.95) {
    s.addShape(pres.ShapeType.line, { x: 0, y: gy, w: W, h: 0, line: { color: texColor, width: 0.5, transparency: 96 } });
  }
  const waveY = 6.05, amp = 0.4, waveSegs = 16;
  let prev = [0, waveY];
  for (let i = 1; i <= waveSegs; i++) {
    const x = (W / waveSegs) * i;
    const y = waveY + Math.sin(i * 0.85) * amp * (i / waveSegs);
    const [x1, y1] = prev, x2 = x, y2 = y;
    s.addShape(pres.ShapeType.line, {
      x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
      flipV: y2 < y1, line: { color: texColor, width: 1, transparency: 93 },
    });
    prev = [x2, y2];
  }
  [1.9, 2.5].forEach((r, i) => {
    s.addShape(pres.ShapeType.ellipse, {
      x: rightCx - r, y: 2.85 - r, w: r * 2, h: r * 2,
      line: { color: texColor, width: 0.75, transparency: 90 - i * 3 },
    });
  });
  [[rightCx - 2.3, 1.55], [rightCx + 2.1, 1.9], [rightCx - 2.0, 4.25], [rightCx + 2.25, 3.95]].forEach(([nx, ny]) => {
    s.addShape(pres.ShapeType.ellipse, { x: nx - 0.035, y: ny - 0.035, w: 0.07, h: 0.07, fill: { color: texColor, transparency: 82 } });
  });

  s.addText([
    { text: "— ", options: { color: TEAL } },
    { text: "2026「数字马力杯」第十三届浙江省大学生服务外包创新应用大赛 · A14（和利时）", options: { color: INV_MUTE } },
  ], { x: leftX, y: 0.95, w: leftW, h: 0.3, fontFace: BODY, fontSize: 12.5, margin: 0 });

  // brand wordmark — native dark-background rendition (proper shading, not a color remap)
  const logoW = 7.9, logoH = logoW / 7.836;
  s.addImage({ path: path.join(ASSETS, "logo-wordmark-dark.png"), x: leftX, y: 1.45, w: logoW, h: logoH });

  // subtitle — restrained: base grey-blue with light-teal emphasis on the three key phrases,
  // a thin left accent line (echoes the KPI strip below), slight letter spacing. No second font.
  const subY = 1.45 + logoH + 0.32;
  s.addShape(pres.ShapeType.rect, { x: leftX, y: subY + 0.04, w: 0.025, h: 0.72, fill: { color: TEAL } });
  const subBase = INV_MUTE, subEmph = TEAL;
  s.addText([
    { text: "基于 ", options: { color: subBase } },
    { text: "Agent", options: { color: subEmph } },
    { text: " 的流程工业建模", options: { color: subBase } },
    { text: "数据智能优选", options: { color: subEmph, breakLine: true } },
    { text: "与", options: { color: subBase } },
    { text: "闭环寻优", options: { color: subEmph } },
    { text: "系统", options: { color: subBase } },
  ], { x: leftX + 0.22, y: subY, w: leftW - 0.22, h: 0.75, fontFace: HEAD, fontSize: 19, margin: 0, lineSpacingMultiple: 1.35, charSpacing: 0.6 });

  // KPI strip — thin accent line instead of boxed cards, single-line captions
  const stats = [
    ["14.3%", "数据量 · 全量精度"],
    ["200", "工作点 · 稳健性验证"],
    ["237", "自动化测试通过"],
  ];
  const kpiY = subY + 0.98, itemGap = 0.4, itemW = (leftW - 2 * itemGap) / 3;
  stats.forEach(([big, small], i) => {
    const x = leftX + i * (itemW + itemGap);
    s.addShape(pres.ShapeType.rect, { x, y: kpiY, w: 0.03, h: 0.82, fill: { color: TEAL } });
    s.addText(big, { x: x + 0.2, y: kpiY, w: itemW - 0.2, h: 0.5, fontFace: MONO, fontSize: 25, bold: true, color: AMBER, margin: 0 });
    s.addText(small, { x: x + 0.2, y: kpiY + 0.53, w: itemW - 0.2, h: 0.3, fontFace: BODY, fontSize: 10.5, color: INV_MUTE, margin: 0 });
  });

  // floating mark — no backing disc, smaller, shifted into the right 35% column
  const iconD = 2.7, iconCy = 2.85;
  s.addImage({ path: path.join(ASSETS, "icon-floating.png"), x: rightCx - iconD / 2, y: iconCy - iconD / 2, w: iconD, h: iconD });

  s.addText("团队昵称【待填】  ·  提交日期【待填】", {
    x: leftX, y: 6.6, w: 7.0, h: 0.35, fontFace: BODY, fontSize: 11, color: "829FAF", margin: 0,
  });

  s.addNotes(
    "封面一句话带过：这套系统解决赛题原文点出的痛点——有效辨识样本被海量稳态数据淹没。三个数字先摆出来，后面每一页都会回来对应其中一个。\n" +
      "团队昵称不可含校名/学院名，指导教师姓名不能出现在任何一页——原创承诺要求。\n" +
      "建议动画（手动加，间隔见括号）：赛事信息 Fade（0.0s）→ 品牌字标 Fade+上移 8px（0.25s）→ 副标题 Fade（0.55s）→ 三个 KPI 依次 Fade，每个间隔 0.12s（0.8s 起）→ 右侧闭环标志 Fade（1.25s）。"
  );
}

/* ================================================================= P2 目录：四段式进度条 */
{
  const s = lightSlide();
  s.addText("内容导览", { x: M, y: 0.7, w: 6, h: 0.4, fontFace: HEAD, fontSize: 13, color: MUTE, margin: 0 });

  const chapters = [
    ["01", "背景与需求", "P3–P4", "为什么做，做给谁用"],
    ["02", "方法与技术", "P5–P9", "我们做了什么不一样的事"],
    ["03", "演示与验证", "P10–P13", "系统真的跑得动、结果站得住"],
    ["04", "工程与收尾", "P14–P17", "能不能交付，接下来怎么走"],
  ];
  const segW = (W - 2 * M - 3 * 0.2) / 4, segY = 1.9, segH = 3.4;
  chapters.forEach(([num, name, pages, sub], i) => {
    const x = M + i * (segW + 0.2);
    s.addShape(pres.ShapeType.roundRect, { x, y: segY, w: segW, h: segH, rectRadius: 0.1, fill: { color: CHAPTERS[i] } });
    s.addText(num, { x: x + 0.25, y: segY + 0.3, w: segW - 0.5, h: 0.7, fontFace: MONO, fontSize: 34, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(name, { x: x + 0.25, y: segY + 1.05, w: segW - 0.5, h: 0.6, fontFace: HEAD, fontSize: 18, bold: true, color: "FFFFFF", margin: 0 });
    s.addShape(pres.ShapeType.line, { x: x + 0.25, y: segY + 1.75, w: segW - 0.5, h: 0, line: { color: "FFFFFF", width: 0.75, transparency: 55 } });
    s.addText(pages, { x: x + 0.25, y: segY + 1.9, w: segW - 0.5, h: 0.35, fontFace: MONO, fontSize: 13, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(sub, { x: x + 0.25, y: segY + 2.3, w: segW - 0.5, h: 0.9, fontFace: BODY, fontSize: 12, color: "FFFFFF", margin: 0, lineSpacingMultiple: 1.25, valign: "top" });
    if (i < 3) {
      const cx = x + segW + 0.1;
      s.addShape(pres.ShapeType.triangle, { x: cx - 0.09, y: segY + segH / 2 - 0.09, w: 0.18, h: 0.18, rotate: 90, fill: { color: MUTE } });
    }
  });
  s.addNotes("目录页只报路标，不展开。建议动画：Morph 过渡到第 3 页，第 3 页出现时把「01」这一段的强调状态自然带过去（同一形状延续）。");
}

/* ================================================================= P3 背景与痛点：可视化为主视觉 */
{
  const s = lightSlide();
  badge(s, "01", TEAL);
  pageTitle(s, "有效数据被淹没：APC 精度卡在数据质量上");

  const chips = [
    "APC 精度取决于数据质量",
    "强噪声 · 强耦合 · 复杂时滞",
    "稳态样本增行数，不增信息",
  ];
  const chipW = (W - 2 * M - 2 * 0.25) / 3;
  chips.forEach((t, i) => {
    const x = M + i * (chipW + 0.25);
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.35, w: chipW, h: 0.55, rectRadius: 0.27, fill: { color: "E3EEF0" }, line: { color: "C7DCE0", width: 0 } });
    s.addText(t, { x, y: 1.35, w: chipW, h: 0.55, align: "center", valign: "middle", fontFace: HEAD, fontSize: 12, bold: true, color: "205A66", margin: 0 });
  });

  // dominant signal band — grey steady segments punctuated by teal dynamic bursts
  const bandX = M, bandY = 2.35, bandH = 1.05, bandW = W - 2 * M;
  const fractions = [0.19, 0.07, 0.14, 0.05, 0.2, 0.08, 0.15, 0.12];
  const isTeal = [false, true, false, true, false, true, false, false];
  let cx = bandX;
  fractions.forEach((f, i) => {
    const w = f * bandW;
    s.addShape(pres.ShapeType.rect, { x: cx, y: bandY, w, h: bandH, fill: { color: isTeal[i] ? TEAL : "DCE0E3" } });
    cx += w;
  });

  s.addText("灰色 = 稳态区间（低信息量）　青色 = 动态区间（高信息量）", {
    x: M, y: bandY + bandH + 0.15, w: W - 2 * M, h: 0.35, fontFace: BODY, fontSize: 11.5, color: MUTE, margin: 0,
  });
  s.addText("真正能确定模型参数的，是这几段", {
    x: M, y: bandY + bandH + 0.6, w: W - 2 * M, h: 0.5, fontFace: HEAD, fontSize: 18, bold: true, color: TEAL, margin: 0,
  });

  card(s, { x: M, y: 5.7, w: W - 2 * M, h: 0.95, fill: CARD, line: TEAL });
  s.addText([
    { text: "和利时自动化", options: { bold: true } },
    { text: "  ·  每年 8000+ 智能化改造项目  ·  ARC「全球自动化 50 强」中国唯一入选企业", options: {} },
  ], { x: M + 0.35, y: 5.7, w: W - 2 * M - 0.7, h: 0.95, fontFace: BODY, fontSize: 14, color: TXT, valign: "middle", margin: 0 });

  footer(s, 3, 0);
  s.addNotes(
    "这不是我们编的痛点——赛题原文点出的，命题企业背景摆在这里佐证分量。\n" +
      "建议动画：信号带先整体以灰色出现，0.5s 后三段青色高亮依次点亮（从左到右），最后浮出「真正能确定模型参数的是这几段」。"
  );
}

/* ================================================================= P4 需求拆解：配对卡片 */
{
  const s = lightSlide();
  badge(s, "02", TEAL);
  pageTitle(s, "赛题任务清单，逐条对应我们的模块");

  const rows = [
    ["① 数据文件管理（上传/查看/删除/概览 + 仿真测试集生成）", "数据集管理 + 一键合成基准数据"],
    ["② 智能规整与清洗（重采样/时间戳对齐/异常剔除）", "预处理流水线（阶段 3–4）"],
    ["③ 高信噪比数据智能筛选（截取 + 质量评分）", "质量约束 D-最优动态区间优选（阶段 5）"],
    ["④ 时滞与共线性自动解耦", "预白化时滞估计 + 共线性诊断降维（阶段 6）"],
    ["⑤ 一键式闭环寻优引擎（ARX + 拟合度为目标函数）", "闭环参数寻优（阶段 7–8）"],
    ["⑥ 专家级图文报告生成", "数值溯源报告（阶段 10）"],
    ["⑦ 高质量数据导出", "优选数据集一键导出"],
  ];
  const rowH = 0.68, gap = 0.1, startY = 1.42;
  const leftW = 5.7, rightW = 5.65, arrowX = M + leftW + 0.1;
  rows.forEach(([a, b], i) => {
    const y = startY + i * (rowH + gap);
    card(s, { x: M, y, w: leftW, h: rowH, fill: "EDF3F4", line: "D6E4E6", r: 0.06 });
    s.addText(a, { x: M + 0.2, y, w: leftW - 0.4, h: rowH, valign: "middle", fontFace: BODY, fontSize: 11.5, color: TXT, margin: 0, lineSpacingMultiple: 1.1 });
    s.addText("→", { x: arrowX, y, w: 0.5, h: rowH, align: "center", valign: "middle", fontFace: HEAD, fontSize: 16, bold: true, color: TEAL, margin: 0 });
    card(s, { x: arrowX + 0.5, y, w: rightW, h: rowH, fill: CARD, line: TEAL, lineW: 1, r: 0.06 });
    s.addText(b, { x: arrowX + 0.7, y, w: rightW - 0.4, h: rowH, valign: "middle", fontFace: HEAD, fontSize: 12, bold: true, color: "205A66", margin: 0, lineSpacingMultiple: 1.1 });
  });
  footer(s, 4, 0);
  s.addNotes("这页目的很直接：让评委一眼确认我们把 7 条任务清单全覆盖了。建议动画：7 行从上到下依次 Wipe（从左至右擦入）。");
}

/* ================================================================= P5 标准答案不成立 */
{
  const s = lightSlide();
  badge(s, "01", AMBER);
  pageTitle(s, "我们把「标准答案」实现了一遍——然后发现它不成立");

  card(s, { x: M, y: 1.35, w: 5.7, h: 1.0 });
  s.addText([
    { text: "人工圈选\n", options: { bold: true, fontSize: 14, color: TXT, breakLine: true } },
    { text: "慢、不可复现、结果因人而异", options: { fontSize: 12, color: MUTE } },
  ], { x: M + 0.25, y: 1.35, w: 5.2, h: 1.0, fontFace: BODY, valign: "middle", margin: 0, lineSpacingMultiple: 1.2 });

  card(s, { x: 7.0, y: 1.35, w: 5.6, h: 1.0 });
  s.addText([
    { text: "加权质量评分\n", options: { bold: true, fontSize: 14, color: TXT, breakLine: true } },
    { text: "滑窗算能量/信噪比/响应关联度，加权求和取前 K 段——赛题清单本身写的就是这套特征", options: { fontSize: 12, color: MUTE } },
  ], { x: 7.25, y: 1.35, w: 5.1, h: 1.0, fontFace: BODY, valign: "middle", margin: 0, lineSpacingMultiple: 1.2 });

  s.addText("同一批数据，两个几乎相同的失败结果", {
    x: M, y: 2.55, w: W - 2 * M, h: 0.35, align: "center", fontFace: BODY, fontSize: 12.5, italic: true, color: MUTE, margin: 0,
  });
  s.addText([
    { text: "14.81%", options: { fontFace: MONO, fontSize: 46, bold: true, color: RUST } },
    { text: "   对   ", options: { fontFace: BODY, fontSize: 16, color: MUTE } },
    { text: "14.82%", options: { fontFace: MONO, fontSize: 46, bold: true, color: MUTE } },
  ], { x: M, y: 2.95, w: W - 2 * M, h: 1.0, align: "center", margin: 0 });
  s.addText(
    "按规范原样实现加权评分，10 组种子对照实验：在激励不均匀的数据上，加权评分与「只看输入变化能量」没有区别，两者都秩亏",
    { x: M, y: 3.95, w: W - 2 * M, h: 0.5, align: "center", fontFace: BODY, fontSize: 13, color: MUTE, margin: 0 }
  );

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 4.8, w: W - 2 * M, h: 1.35, rectRadius: 0.08, fill: { color: TINT_AMBER }, line: { color: AMBER, width: 1 } });
  s.addText(
    "问题不在特征选得不够全，而在于「逐窗口独立打分」这个形式本身——评分公式里没有任何一项能表达「这个窗口和已选窗口在讲同一件事」",
    { x: M + 0.35, y: 4.8, w: W - 2 * M - 0.7, h: 1.35, fontFace: HEAD, fontSize: 15, bold: true, color: "8A5A15", valign: "middle", margin: 0, lineSpacingMultiple: 1.25 }
  );
  footer(s, 5, 1);
  s.addNotes(
    "这页和第 13 页是这份材料区别于其他队伍的地方，讲的时候不要略过。\n" +
      "建议动画：两条路线卡片先出现 → 「同一批数据…」小字出现 → 14.81% 和 14.82% 用 Fade+缩放依次出现（制造揭晓停顿）→ 归因红框最后浮出。"
  );
}

/* ================================================================= P6 核心方法 */
{
  const s = lightSlide();
  badge(s, "02", AMBER);
  pageTitle(s, "不问「这段数据质量多好」，问「能带来多少新信息」");

  s.addText("max log det(λI + Σ ΦᵀΦ)", {
    x: M, y: 1.35, w: W - 2 * M, h: 0.5, align: "center", fontFace: MONO, fontSize: 22, bold: true, color: TEAL, margin: 0,
  });

  const pts = [
    "把候选片段对 Fisher 信息矩阵的贡献作为选择依据",
    "与已选片段重复的窗口，增量增益趋近于零",
    "不是「分数最高的段」，是「边际信息量最大的段」",
  ];
  const colW = (W - 2 * M - 0.6) / 3;
  pts.forEach((t, i) => {
    const x = M + i * (colW + 0.3);
    card(s, { x, y: 2.0, w: colW, h: 0.85 });
    s.addText(t, { x: x + 0.2, y: 2.0, w: colW - 0.4, h: 0.85, fontFace: BODY, fontSize: 11.5, color: TXT, valign: "middle", margin: 0, lineSpacingMultiple: 1.2 });
  });

  s.addText("已选窗口 A / B / D 之外，新窗口 C 的边际增益 ≈ 0", {
    x: M, y: 3.15, w: W - 2 * M, h: 0.4, fontFace: HEAD, fontSize: 14, bold: true, color: TXT, margin: 0,
  });

  // candidate windows as waveform thumbnails — a concrete signal shape reads faster than an
  // abstract bar; patterns are illustrative (no fabricated precision numbers attached, only
  // the qualitative 高/≈0 tag we can actually stand behind)
  const windows = [
    { name: "窗口 A", tag: "已选", accept: true, pat: [0.5, 0.2, 0.8, 0.3, 0.9, 0.15, 0.7, 0.35, 0.6, 0.25, 0.85, 0.4, 0.5], gain: "边际增益：高" },
    { name: "窗口 B", tag: "已选", accept: true, pat: [0.5, 0.7, 0.25, 0.85, 0.3, 0.6, 0.2, 0.75, 0.4, 0.55, 0.2, 0.8, 0.5], gain: "边际增益：高" },
    { name: "窗口 C", tag: "新候选", accept: false, pat: [0.5, 0.55, 0.45, 0.52, 0.48, 0.53, 0.47, 0.5, 0.51, 0.49, 0.5, 0.48, 0.5], gain: "边际增益：≈0（冗余）" },
    { name: "窗口 D", tag: "已选", accept: true, pat: [0.5, 0.3, 0.65, 0.15, 0.75, 0.35, 0.9, 0.2, 0.6, 0.4, 0.8, 0.3, 0.5], gain: "边际增益：高" },
  ];
  const wcW = (W - 2 * M - 3 * 0.25) / 4, wcY = 3.65, wcH = 2.65;
  windows.forEach((win, i) => {
    const x = M + i * (wcW + 0.25);
    const tagColor = win.accept ? TEAL : "9AA5AB";
    card(s, { x, y: wcY, w: wcW, h: wcH, line: win.accept ? "C9E4E8" : "E2E8ED" });
    s.addShape(pres.ShapeType.roundRect, { x: x + 0.18, y: wcY + 0.18, w: wcW - 0.36, h: 0.4, rectRadius: 0.2, fill: { color: tagColor } });
    s.addText(`${win.name}（${win.tag}）`, { x: x + 0.18, y: wcY + 0.18, w: wcW - 0.36, h: 0.4, align: "center", valign: "middle", fontFace: HEAD, fontSize: 11, bold: true, color: "FFFFFF", margin: 0 });

    // sparkline
    const sx = x + 0.25, sy = wcY + 0.75, sw = wcW - 0.5, sh = 1.0;
    const pat = win.pat;
    const lineColor = win.accept ? TEAL : "AEB6BB";
    for (let p = 0; p < pat.length - 1; p++) {
      const x1 = sx + (sw / (pat.length - 1)) * p, y1 = sy + sh * pat[p];
      const x2 = sx + (sw / (pat.length - 1)) * (p + 1), y2 = sy + sh * pat[p + 1];
      s.addShape(pres.ShapeType.line, {
        x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
        flipV: y2 < y1, line: { color: lineColor, width: 1.5 },
      });
    }

    const gainColor = win.accept ? TEAL : "9AA5AB";
    s.addText(`${win.accept ? "✓" : "✕"} ${win.gain}`, {
      x: x + 0.18, y: wcY + wcH - 0.45, w: wcW - 0.36, h: 0.3, align: "center", fontFace: MONO, fontSize: 10.5, bold: true, color: gainColor, margin: 0,
    });
  });
  footer(s, 6, 1);
  s.addNotes(
    "公式讲直觉就够，主视觉是四个候选窗口的波形卡片——不是编造具体增益数值，只给可信的定性判断（高/≈0）。\n" +
      "建议动画：窗口 A → B → D 波形依次淡入点亮，C 最后以灰色波形淡入并标注「冗余」。"
  );
}

/* ================================================================= P7 系统架构：四段分组（章节页，深色） */
{
  const s = sectionSlide();
  badge(s, "03", AMBER);
  pageTitle(s, "一句自然语言，驱动全流程", 22, STRONG_DARK);

  const groups = [
    ["数据规整", ["上传", "规整清洗", "区间检测 / 门控"]],
    ["建模准备", ["D-最优优选", "时滞补偿", "共线降维", "ARX 辨识"]],
    ["闭环寻优", ["双口径评价", "闭环寻优", "热启动"]],
    ["智能交付", ["Agent 编排", "自评测基准", "溯源报告", "数据导出"]],
  ];
  const gW = (W - 2 * M - 3 * 0.35) / 4, gY = 1.5, gH = 2.6;
  groups.forEach(([name, items], i) => {
    const x = M + i * (gW + 0.35);
    darkCard(s, { x, y: gY, w: gW, h: gH });
    s.addShape(pres.ShapeType.roundRect, { x: x + 0.2, y: gY + 0.2, w: gW - 0.4, h: 0.45, rectRadius: 0.22, fill: { color: TEAL } });
    s.addText(name, { x: x + 0.2, y: gY + 0.2, w: gW - 0.4, h: 0.45, align: "center", valign: "middle", fontFace: HEAD, fontSize: 13, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(
      items.map((t) => ({ text: "•  " + t, options: { breakLine: true } })),
      { x: x + 0.25, y: gY + 0.85, w: gW - 0.5, h: gH - 1.05, valign: "top", fontFace: BODY, fontSize: 11.5, color: INV_MUTE, margin: 0, lineSpacingMultiple: 1.4 }
    );
    if (i < 3) {
      s.addText("→", { x: x + gW, y: gY, w: 0.35, h: gH, align: "center", valign: "middle", fontFace: HEAD, fontSize: 18, bold: true, color: TEAL, margin: 0 });
    }
  });
  s.addText("↻ 闭环回到评价环节，反复调参直至寻优出最佳预处理策略", {
    x: M, y: gY + gH + 0.1, w: W - 2 * M, h: 0.3, fontFace: BODY, fontSize: 10.5, italic: true, color: INV_MUTE, margin: 0,
  });

  s.addText("技术栈", { x: M, y: 4.55, w: 3, h: 0.35, fontFace: HEAD, fontSize: 13, bold: true, color: STRONG_DARK, margin: 0 });
  const stacks = [
    ["FastAPI + Vue/TS", "前后端框架"],
    ["LangGraph", "LLM 编排"],
    ["PostgreSQL + Redis + RQ", "存储与任务队列"],
    ["Docker Compose", "单机离线部署"],
  ];
  const sw = (W - 2 * M - 0.9) / 4;
  stacks.forEach(([big, small], i) => {
    const x = M + i * (sw + 0.3);
    darkCard(s, { x, y: 4.95, w: sw, h: 0.95 });
    s.addText(big, { x: x + 0.15, y: 5.02, w: sw - 0.3, h: 0.4, fontFace: MONO, fontSize: 11.5, bold: true, color: TEAL, margin: 0 });
    s.addText(small, { x: x + 0.15, y: 5.42, w: sw - 0.3, h: 0.4, fontFace: BODY, fontSize: 10.5, color: INV_MUTE, margin: 0 });
  });
  footer(s, 7, 1, true);
  s.addNotes("14 个环节归并成 4 段，减少密度；这页是「方法总览」的深色章节页，打断连续浅色页面的节奏。建议动画：Morph 从第 6 页的柱状图过渡到这页的 4 段分组卡（同色延续）；4 段从左到右依次推进出现。");
}

/* ================================================================= P8 技术创新 I */
{
  const s = lightSlide();
  badge(s, "04", AMBER);
  pageTitle(s, "两处我们没有照赛题字面做，且给出了理由");

  const colW = (W - 2 * M - 0.4) / 2;
  card(s, { x: M, y: 1.5, w: colW, h: 5.0 });
  s.addText("门控先于信息准则", { x: M + 0.3, y: 1.75, w: colW - 0.6, h: 0.45, fontFace: HEAD, fontSize: 17, bold: true, color: TXT, margin: 0 });
  s.addText([
    { text: "含尖峰或大段缺失的窗口「信息量」往往极高——直接用信息准则选段，污染会被优先选入", options: { bullet: true, breakLine: true } },
    { text: "质量门控前置：不合格窗口在参与信息量比较之前就被剔除", options: { bullet: true, breakLine: true } },
    { text: "每一条拒绝理由都被记录", options: { bullet: true } },
  ], { x: M + 0.3, y: 2.35, w: colW - 0.6, h: 3.9, valign: "top", fontFace: BODY, fontSize: 13.5, color: TXT, margin: 0, paraSpaceAfter: 14, lineSpacingMultiple: 1.3 });

  const rx = M + colW + 0.4;
  card(s, { x: rx, y: 1.5, w: colW, h: 5.0 });
  s.addText("自由仿真 FIT，不是一步预测 FIT", { x: rx + 0.3, y: 1.75, w: colW - 0.6, h: 0.45, fontFace: HEAD, fontSize: 17, bold: true, color: TXT, margin: 0 });
  s.addText([
    { text: "工业过程输出强自相关，模型只要「抄上一时刻」就能拿到很高的一步预测分数", options: { bullet: true, breakLine: true } },
    { text: "实测：参数误差 15%、秩亏的模型，一步预测 FIT 仍有 ", options: { bullet: true } },
    { text: "96.5", options: { fontFace: MONO, bold: true, color: AMBER } },
    { text: "，只比最优模型低 0.5 分\n", options: { breakLine: true } },
    { text: "同组模型自由仿真 FIT 跨度 ", options: { bullet: true } },
    { text: "15.3", options: { fontFace: MONO, bold: true, color: AMBER } },
    { text: " 分", options: {} },
  ], { x: rx + 0.3, y: 2.35, w: colW - 0.6, h: 2.0, valign: "top", fontFace: BODY, fontSize: 13.5, color: TXT, margin: 0, paraSpaceAfter: 10, lineSpacingMultiple: 1.3 });

  s.addText([
    { text: "区分度差 ", options: { fontFace: HEAD, fontSize: 22, bold: true, color: TXT } },
    { text: "28.5", options: { fontFace: MONO, fontSize: 32, bold: true, color: AMBER } },
    { text: " 倍", options: { fontFace: HEAD, fontSize: 22, bold: true, color: TXT } },
  ], { x: rx + 0.3, y: 4.4, w: colW - 0.6, h: 0.55, margin: 0 });

  const maxW = colW - 0.6, by1 = 5.1, by2 = 5.55;
  s.addShape(pres.ShapeType.rect, { x: rx + 0.3, y: by1, w: maxW * (0.5 / 15.3), h: 0.28, fill: { color: "C7CDD2" } });
  s.addText("一步预测 0.5 分", { x: rx + 0.3, y: by1 - 0.28, w: maxW, h: 0.25, fontFace: BODY, fontSize: 9.5, color: MUTE, margin: 0 });
  s.addShape(pres.ShapeType.rect, { x: rx + 0.3, y: by2, w: maxW, h: 0.28, fill: { color: AMBER } });
  s.addText("自由仿真 15.3 分", { x: rx + 0.3, y: by2 + 0.32, w: maxW, h: 0.25, fontFace: BODY, fontSize: 9.5, color: MUTE, margin: 0 });
  footer(s, 8, 1);
  s.addNotes(
    "一步预测 FIT 保留作诊断量，它和自由仿真的差值就是过拟合信号。\n" +
      "建议动画：左卡 Wipe 进入 → 右卡 Wipe 进入 → 「28.5 倍」最后用 Fade+放大强调出现。"
  );
}

/* ================================================================= P9 技术创新 II：四层护栏 */
{
  const s = lightSlide();
  badge(s, "05", AMBER);
  pageTitle(s, "大模型负责提议，不负责授权");

  const layers = [
    ["执行计划双轨同源校验", "大模型生成的执行计划必须通过与规则计划完全相同的白名单、执行图与合规校验"],
    [null, "`requires_confirmation` 一律取自白名单，不是模型输出——模型不能自己决定这一步要不要用户确认"],
    ["报告数字，大模型一个都不许写", "只能输出占位符，由渲染器绑定到真实运行记录；连续三次不合规回退模板化结论"],
    ["最坏情况有下限", "模型不可用、输出畸形甚至刻意越权，最坏结果都只是「回退 + 说明」"],
  ];
  const barH = 0.85, gapY = 0.13, startY = 1.5;
  layers.forEach((l, i) => {
    const y = startY + i * (barH + gapY);
    card(s, { x: M, y, w: W - 2 * M, h: barH, r: 0.06 });
    s.addShape(pres.ShapeType.rect, { x: M, y, w: 0.08, h: barH, fill: { color: AMBER } });
    s.addText(`护栏 ${i + 1}`, {
      x: M + 0.3, y, w: 0.9, h: barH, valign: "middle", fontFace: MONO, fontSize: 11, bold: true, color: AMBER, margin: 0,
    });
    if (l[0] === null) {
      s.addText([
        { text: "requires_confirmation", options: { fontFace: MONO, fontSize: 13, bold: true, color: TEAL, breakLine: true } },
        { text: " 一律取自白名单", options: { fontFace: HEAD, fontSize: 13, bold: true, color: TXT } },
      ], { x: M + 1.25, y, w: 3.3, h: barH, valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });
    } else {
      s.addText(l[0], { x: M + 1.25, y, w: 3.3, h: barH, valign: "middle", fontFace: HEAD, fontSize: 13, bold: true, color: TXT, margin: 0, lineSpacingMultiple: 1.15 });
    }
    s.addText(l[1], { x: M + 4.75, y, w: W - 2 * M - 4.75 - 0.3, h: barH, valign: "middle", fontFace: BODY, fontSize: 11.5, color: MUTE, margin: 0, lineSpacingMultiple: 1.25 });
  });

  s.addText("模型不可用时，系统依然完整可用", {
    x: M, y: startY + 4 * (barH + gapY) + 0.15, w: W - 2 * M, h: 0.5, align: "center", fontFace: HEAD, fontSize: 19, bold: true, color: TEAL, margin: 0,
  });
  footer(s, 9, 1);
  s.addNotes(
    "可信性不是承诺，是机制。\n" +
      "建议动画：四层护栏从上到下依次堆叠出现（Fade + 轻微上移），最后总结语淡入。"
  );
}

/* ================================================================= P10 产品功能：主图+缩略图 */
{
  const s = lightSlide();
  badge(s, "06", TEAL_LT);
  pageTitle(s, "不是原型图，是跑起来的产品");

  const heroW = 6.9, heroH = heroW * (900 / 1440), heroX = M, heroY = 1.5;
  s.addShape(pres.ShapeType.rect, { x: heroX - 0.02, y: heroY - 0.02, w: heroW + 0.04, h: heroH + 0.04, fill: { color: "FFFFFF" }, line: { color: "D8DEE3", width: 1 } });
  s.addImage({ path: path.join(SHOTS, "workspace-1440x900.png"), x: heroX, y: heroY, w: heroW, h: heroH });
  s.addText("工作台 / 流程编排 —— Agent 一句话驱动全流程的入口", {
    x: heroX, y: heroY + heroH + 0.1, w: heroW, h: 0.3, fontFace: BODY, fontSize: 12, color: MUTE, margin: 0,
  });

  const rest = [
    ["home-1440x900.png", "首页总览"],
    ["datasets-1440x900.png", "数据集管理"],
    ["arx-1440x900.png", "ARX 辨识结果"],
    ["optimization-1440x900.png", "闭环寻优收敛曲线"],
    ["deliverables-1440x900.png", "报告与交付物"],
  ];
  const tx0 = heroX + heroW + 0.3, tw = W - M - tx0;
  const cols = 2, tImgW = (tw - 0.2) / cols, tImgH = tImgW * (900 / 1440), rowGap = 0.35;
  rest.forEach(([file, label], i) => {
    const col = i % cols, row = Math.floor(i / cols);
    const x = tx0 + col * (tImgW + 0.2);
    const y = heroY + row * (tImgH + rowGap);
    s.addShape(pres.ShapeType.rect, { x: x - 0.02, y: y - 0.02, w: tImgW + 0.04, h: tImgH + 0.04, fill: { color: "FFFFFF" }, line: { color: "D8DEE3", width: 1 } });
    s.addImage({ path: path.join(SHOTS, file), x, y, w: tImgW, h: tImgH });
    s.addText(label, { x, y: y + tImgH + 0.03, w: tImgW, h: 0.25, align: "center", fontFace: BODY, fontSize: 9.5, color: MUTE, margin: 0 });
  });
  footer(s, 10, 2);
  s.addNotes(
    "这六张截图取自 artifacts/layout-refactor——正式提交前请核对是否为最新 UI。\n" +
      "建议动画：主图先 Fade 出现，五张缩略图依次出现（从左到右、从上到下）。"
  );
}

/* ================================================================= P11 一句话驱动全流程 */
{
  const s = lightSlide();
  badge(s, "07", TEAL_LT);
  pageTitle(s, "用户说一句话，Agent 拆解成完整工作流");

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 1.5, w: W - 2 * M, h: 0.85, rectRadius: 0.15, fill: { color: NAVY } });
  s.addText("“提取 1 号塔高信噪比的动态数据，处理共线性后，通过闭环寻优找出最佳模型数据”", {
    x: M + 0.35, y: 1.5, w: W - 2 * M - 0.7, h: 0.85, valign: "middle", fontFace: HEAD, fontSize: 15, italic: true, color: "FFFFFF", margin: 0,
  });

  const steps = [
    ["意图解析", "识别出「数据筛选 + 共线性处理 + 闭环寻优」三个子任务"],
    ["生成执行计划", "含每步参数与执行顺序的结构化计划"],
    ["依次调度", "动态区间优选 → 共线性诊断降维 → ARX 辨识 → 闭环寻优"],
    ["回溯调参", "捕获辨识指标，自动回溯调整前置处理参数"],
    ["产出交付", "最优参数组合 + 图文报告 + 可下载数据集"],
  ];
  const nW = (W - 2 * M - 4 * 0.25) / 5;
  steps.forEach(([t, d], i) => {
    const x = M + i * (nW + 0.25);
    const cy = 2.85;
    s.addShape(pres.ShapeType.ellipse, { x: x + nW / 2 - 0.22, y: cy, w: 0.44, h: 0.44, fill: { color: TEAL_LT } });
    s.addText(String(i + 1), { x: x + nW / 2 - 0.22, y: cy, w: 0.44, h: 0.44, align: "center", valign: "middle", fontFace: MONO, fontSize: 15, bold: true, color: "FFFFFF", margin: 0 });
    if (i < steps.length - 1) {
      s.addShape(pres.ShapeType.line, { x: x + nW / 2 + 0.24, y: cy + 0.22, w: nW + 0.25 - 0.48, h: 0, line: { color: TEAL_LT, width: 1 } });
    }
    card(s, { x, y: 3.55, w: nW, h: 2.7 });
    s.addText(t, { x: x + 0.15, y: 3.75, w: nW - 0.3, h: 0.4, fontFace: HEAD, fontSize: 12.5, bold: true, color: TXT, margin: 0 });
    s.addText(d, { x: x + 0.15, y: 4.2, w: nW - 0.3, h: 1.9, valign: "top", fontFace: BODY, fontSize: 10, color: MUTE, margin: 0, lineSpacingMultiple: 1.25 });
  });
  footer(s, 11, 2);
  s.addNotes(
    "这句话直接照抄赛题原文的示例场景。\n" +
      "建议动画：用户原话先出现 → 5 个步骤按顺序点亮（编号圆点 + 连线依次绘出）。"
  );
}

/* ================================================================= P12 实测结果：证据卡片 */
{
  const s = lightSlide();
  badge(s, "08", TEAL_LT);
  pageTitle(s, "结论不是单点巧合");

  const evid = [
    ["14.3%", "数据量达到全量数据辨识精度（4.54% vs 4.61%）", "EXP-2.1 S6"],
    ["15%", "能量启发式与完整加权分同等预算下同时失效", "EXP-2.1 S6"],
    ["18/20", "200 个工作点上 D-最优参数误差最优（满秩 16/20）", "EXP-3.0"],
    ["1/28.5", "一步预测 FIT 区分度仅为自由仿真 FIT 的", "EXP-2.1 S6"],
    ["24 倍", "闭环分级搜索使昂贵环节摊薄", "阶段 8 实测"],
  ];
  const cW = (W - 2 * M - 4 * 0.25) / 5;
  evid.forEach(([big, desc, src], i) => {
    const x = M + i * (cW + 0.25);
    card(s, { x, y: 1.5, w: cW, h: 3.15, fill: TINT_TEAL, line: "C9E4E8" });
    s.addText(big, { x: x + 0.15, y: 1.7, w: cW - 0.3, h: 0.65, fontFace: MONO, fontSize: 24, bold: true, color: TEAL_LT, margin: 0 });
    s.addText(desc, { x: x + 0.15, y: 2.45, w: cW - 0.3, h: 1.05, valign: "top", fontFace: BODY, fontSize: 11, color: TXT, margin: 0, lineSpacingMultiple: 1.3 });
    s.addShape(pres.ShapeType.line, { x: x + 0.15, y: 4.05, w: cW - 0.3, h: 0, line: { color: "C9E4E8", width: 0.75 } });
    s.addText(src, { x: x + 0.15, y: 4.15, w: cW - 0.3, h: 0.35, fontFace: MONO, fontSize: 9.5, bold: true, color: MUTE, margin: 0 });
  });
  // supporting visual: rank-deficient vs full-rank design matrix, illustrative only —
  // explicitly labeled as such, no fabricated precision attached to a synthetic pattern
  const gridSize = 1.6, cell = gridSize / 6, gridY = 4.8, centerX = W / 2, vsW = 0.5, gap = 0.35;
  const leftGX = centerX - vsW / 2 - gap - gridSize, rightGX = centerX + vsW / 2 + gap;
  const deficient = [
    [100, 85, 78, 15, 10, 12], [85, 100, 82, 12, 8, 14], [78, 82, 100, 10, 12, 9],
    [15, 12, 10, 100, 80, 76], [10, 8, 12, 80, 100, 83], [12, 14, 9, 76, 83, 100],
  ];
  const fullRank = [
    [100, 18, 12, 20, 15, 10], [18, 100, 22, 14, 18, 12], [12, 22, 100, 16, 10, 20],
    [20, 14, 16, 100, 19, 15], [15, 18, 10, 19, 100, 17], [10, 12, 20, 15, 17, 100],
  ];
  function corrGrid(gx, gy, matrix) {
    matrix.forEach((row, r) => {
      row.forEach((v, c) => {
        s.addShape(pres.ShapeType.rect, {
          x: gx + c * cell, y: gy + r * cell, w: cell, h: cell,
          fill: { color: TEAL_LT, transparency: 100 - v * 0.85 },
        });
      });
    });
    s.addShape(pres.ShapeType.rect, { x: gx, y: gy, w: gridSize, h: gridSize, line: { color: "D8DEE3", width: 0.5 } });
  }
  s.addText("加权评分选出的窗口集合 · 秩亏", { x: leftGX - 0.3, y: gridY - 0.32, w: gridSize + 0.6, h: 0.28, align: "center", fontFace: HEAD, fontSize: 10.5, bold: true, color: RUST, margin: 0 });
  corrGrid(leftGX, gridY, deficient);
  s.addText("D-最优选出的窗口集合 · 满秩", { x: rightGX - 0.3, y: gridY - 0.32, w: gridSize + 0.6, h: 0.28, align: "center", fontFace: HEAD, fontSize: 10.5, bold: true, color: GREEN, margin: 0 });
  corrGrid(rightGX, gridY, fullRank);
  s.addShape(pres.ShapeType.ellipse, { x: centerX - vsW / 2, y: gridY + gridSize / 2 - vsW / 2, w: vsW, h: vsW, fill: { color: CARD }, line: { color: "D8DEE3", width: 1 } });
  s.addText("VS", { x: centerX - vsW / 2, y: gridY + gridSize / 2 - vsW / 2, w: vsW, h: vsW, align: "center", valign: "middle", fontFace: MONO, fontSize: 9, bold: true, color: MUTE, margin: 0 });
  s.addText("窗口间相关性示意（非实测矩阵）：颜色越深 = 两个窗口信息越重叠。加权评分选出的窗口相互高度重叠，条件数差；D-最优选出的窗口彼此独立，满秩", {
    x: M, y: gridY + gridSize + 0.15, w: W - 2 * M, h: 0.4, align: "center", fontFace: BODY, fontSize: 9.5, italic: true, color: MUTE, margin: 0,
  });

  footer(s, 12, 2);
  s.addNotes(
    "每条结论都能查到具体实验编号；底部矩阵图是概念示意，明确标注非实测数据，避免被误读成真实矩阵。\n" +
      "建议动画：五张卡片的大数字先依次 Fade 出现，说明文字随后统一淡入 → 底部两个矩阵图同时 Fade 出现，最后浮出对比说明文字。"
  );
}

/* ================================================================= P13 不利结果：边界条件卡片 */
{
  const s = lightSlide();
  badge(s, "09", RUST);
  pageTitle(s, "我们同时提交对自己不利的结果");

  const items = [
    [[{ text: "同构激励下 D-最优排在末位（", options: {} }, { text: "4.80%", options: { fontFace: MONO, bold: true, color: RUST } }, { text: "，落后加权分 ", options: {} }, { text: "3.75%", options: { fontFace: MONO, bold: true, color: RUST } }, { text: "、全量 ", options: {} }, { text: "3.76%", options: { fontFace: MONO, bold: true, color: RUST } }, { text: "）", options: {} }],
      "价值在于「不会崩」，不是「永远最优」。差距约 1 个百分点；异构激励下的差距是 11 个百分点加秩亏"],
    [[{ text: "预算太小时（预算/窗长 ≤ ", options: {} }, { text: "2.3", options: { fontFace: MONO, bold: true, color: RUST } }, { text: "）D-最优同样秩亏", options: {} }],
      "不是准则失灵，是预算不足。已作为提示写进产品，不让工程师在不知情时拿到秩亏模型"],
    [[{ text: "内容寻址缓存命中率仅 ", options: {} }, { text: "1.7%", options: { fontFace: MONO, bold: true, color: RUST } }],
      "真正的节省来自分级搜索。据实上报，不把收益错误归因"],
    [[{ text: "预白化时滞估计 ", options: {} }, { text: "4 胜 1 负 1 平", options: { fontFace: MONO, bold: true, color: RUST } }],
      "占优但非全胜，报告里就这么写"],
  ];
  const rowH = 1.1, gap = 0.15, startY = 1.5;
  items.forEach(([claim, resp], i) => {
    const y = startY + i * (rowH + gap);
    card(s, { x: M, y, w: W - 2 * M, h: rowH, r: 0.06, fill: TINT_RUST, line: "F3D6D2" });
    s.addShape(pres.ShapeType.rect, { x: M, y, w: 0.08, h: rowH, fill: { color: RUST } });
    s.addText(claim, { x: M + 0.35, y, w: 5.7, h: rowH, valign: "middle", fontFace: HEAD, fontSize: 13, color: TXT, margin: 0, lineSpacingMultiple: 1.2 });
    s.addText(resp, { x: M + 6.25, y, w: W - 2 * M - 6.25 - 0.3, h: rowH, valign: "middle", fontFace: BODY, fontSize: 11.5, color: MUTE, margin: 0, lineSpacingMultiple: 1.25 });
  });
  footer(s, 13, 2);
  s.addNotes(
    "这页和第 5 页是这份材料区别于其他队伍的地方，不要略过、不要用花哨转场抢戏。\n" +
      "建议动画：四条边界条件从上到下依次单独 Fade，不要用 Wipe/涡流这类花哨效果。"
  );
}

/* ================================================================= P14 工程完成度：质量门禁面板（章节页，深色） */
{
  const s = sectionSlide();
  badge(s, "10", RUST);
  pageTitle(s, "不是能跑通一次，是有测试兜底", 22, STRONG_DARK);

  const mono = (t) => ({ text: t, options: { fontFace: MONO, bold: true, color: "9FE1CB" } });
  const rows = [
    ["后端自动化测试", [mono("237 passed"), { text: "  端到端用例、大模型集成、真实 Redis + RQ Worker 往返", options: { color: INV_MUTE } }]],
    ["前端 E2E", [mono("Playwright 9 passed"), { text: "  真实浏览器驱动真实后端，无 mock", options: { color: INV_MUTE } }]],
    ["静态检查", [mono("Ruff / Ruff format / Mypy"), { text: "  全通过（69 个源文件）", options: { color: INV_MUTE } }]],
    ["前端构建", [mono("vue-tsc --noEmit"), { text: " 退出码 0，", options: { color: INV_MUTE } }, mono("Vitest 3 passed")]],
    ["部署", [mono("Docker Compose"), { text: "  单机离线栈（PostgreSQL + Redis + API + Worker）", options: { color: INV_MUTE } }]],
    ["大模型", [{ text: "任意 OpenAI 兼容端点；", options: { color: INV_MUTE } }, { text: "未配置时系统完整可用", options: { bold: true, color: AMBER } }]],
  ];
  const panelH = 4.15, panelY = 1.45;
  s.addShape(pres.ShapeType.roundRect, { x: M, y: panelY, w: W - 2 * M, h: panelH, rectRadius: 0.1, fill: { color: NAVY } });
  const rowH = (panelH - 0.4) / rows.length;
  rows.forEach(([label, statusRuns], i) => {
    const y = panelY + 0.2 + i * rowH;
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.35, y: y + rowH / 2 - 0.13, w: 0.26, h: 0.26, fill: { color: GREEN } });
    s.addText("✓", { x: M + 0.35, y: y + rowH / 2 - 0.13, w: 0.26, h: 0.26, align: "center", valign: "middle", fontFace: BODY, fontSize: 11, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(label, { x: M + 0.8, y, w: 2.3, h: rowH, valign: "middle", fontFace: HEAD, fontSize: 12.5, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(statusRuns, { x: M + 3.2, y, w: W - 2 * M - 3.5, h: rowH, valign: "middle", fontFace: BODY, fontSize: 11, margin: 0 });
    if (i < rows.length - 1) {
      s.addShape(pres.ShapeType.line, { x: M + 0.35, y: y + rowH, w: W - 2 * M - 0.7, h: 0, line: { color: "2A4258", width: 0.5 } });
    }
  });

  s.addText("尚未完成：公开工业数据集外部验证（受开发环境出网策略限制，非算法问题）、Docker Compose 实机启动复核", {
    x: M, y: panelY + panelH + 0.2, w: W - 2 * M, h: 0.3, fontFace: BODY, fontSize: 10.5, color: INV_MUTE, margin: 0,
  });
  footer(s, 14, 3, true);
  s.addNotes("如实列出尚未完成的两项，不粉饰；这页是「工程与交付」的深色章节页。建议动画：六行状态从上到下逐项打勾出现（绿色圆点 Fade 入）。");
}

/* ================================================================= P15 实施方案：四大阶段 */
{
  const s = lightSlide();
  badge(s, "11", RUST);
  pageTitle(s, "四大阶段，按计划完成");

  s.addShape(pres.ShapeType.roundRect, { x: W - M - 3.6, y: 0.42, w: 3.6, h: 0.55, rectRadius: 0.08, fill: { color: "E3F3EC" }, line: { color: GREEN, width: 1 } });
  s.addText("阶段 0–11 全部开发完成", { x: W - M - 3.6, y: 0.42, w: 3.6, h: 0.55, align: "center", valign: "middle", fontFace: HEAD, fontSize: 12, bold: true, color: "1F6B4C", margin: 0 });

  const groups = [
    ["基础奠定", "阶段 0–2", "10–14 天", ["需求 / 口径冻结", "工程骨架搭建", "仿真数据与 ARX 基线"]],
    ["核心算法", "阶段 3–6", "22–29 天", ["数据集与质量诊断", "数据清洗与时间规整", "动态区间优选", "时滞与共线性处理"]],
    ["辨识与寻优", "阶段 7–9", "19–26 天", ["完整系统辨识", "闭环参数寻优", "Agent 智能编排"]],
    ["交付与验收", "阶段 10–11", "11–16 天", ["报告与数据交付", "测试与竞赛交付"]],
  ];
  const gW = (W - 2 * M - 3 * 0.3) / 4, gY = 1.55, gH = 4.6;
  groups.forEach(([name, range, days, items], i) => {
    const x = M + i * (gW + 0.3);
    card(s, { x, y: gY, w: gW, h: gH });
    s.addShape(pres.ShapeType.rect, { x, y: gY, w: gW, h: 0.08, fill: { color: RUST } });
    s.addText(name, { x: x + 0.2, y: gY + 0.25, w: gW - 0.4, h: 0.4, fontFace: HEAD, fontSize: 15, bold: true, color: TXT, margin: 0 });
    s.addText(range, { x: x + 0.2, y: gY + 0.68, w: gW - 0.4, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: RUST, margin: 0 });
    s.addText(days, { x: x + 0.2, y: gY + 0.98, w: gW - 0.4, h: 0.3, fontFace: MONO, fontSize: 11, color: MUTE, margin: 0 });
    s.addShape(pres.ShapeType.line, { x: x + 0.2, y: gY + 1.4, w: gW - 0.4, h: 0, line: { color: "E2E8ED", width: 0.75 } });
    s.addText(
      items.map((t) => ({ text: "•  " + t, options: { breakLine: true } })),
      { x: x + 0.2, y: gY + 1.55, w: gW - 0.4, h: gH - 1.7, valign: "top", fontFace: BODY, fontSize: 11.5, color: TXT, margin: 0, lineSpacingMultiple: 1.5 }
    );
    if (i < 3) {
      s.addText("→", { x: x + gW, y: gY, w: 0.3, h: gH, align: "center", valign: "middle", fontFace: HEAD, fontSize: 16, bold: true, color: RUST, margin: 0 });
    }
  });

  s.addText("唯一未完成项：公开数据集外部验证（环境网络限制，非计划延误）", {
    x: M, y: 6.35, w: W - 2 * M, h: 0.3, fontFace: BODY, fontSize: 10.5, color: MUTE, margin: 0,
  });
  footer(s, 15, 3);
  s.addNotes(
    "这是评分权重最大的一页——实施方案 30 分，务必讲扎实。原 12 个小阶段归并为 4 大阶段，字号更大更可读。\n" +
      "建议动画：时间轴从左到右 Wipe，四段依次推进出现。"
  );
}

/* ================================================================= P16 团队介绍 */
{
  const s = lightSlide();
  badge(s, "12", RUST);
  pageTitle(s, "按赛制要求的三个角色分工");

  s.addText(
    "《参赛指南》要求团队必须包含项目负责人、技术负责人、客户关系经理三个角色，并在方案里体现各自职责——对应网评评分表「项目展示与团队协作」这一项",
    { x: M, y: 1.35, w: W - 2 * M, h: 0.45, fontFace: BODY, fontSize: 12, color: MUTE, margin: 0 }
  );

  const roles = [
    ["项目负责人", "PM", "领导力、组织力、管理能力；对应 S2B 组织管理与业务分析", "【待填，如：整体进度把控、阶段验收、赛事材料统筹】"],
    ["技术负责人", "TECH", "技术水平和主导力；对应 S2C 技术路线及实现方案", "【待填，如：算法设计（D-最优优选、闭环寻优）、后端架构】"],
    ["客户关系经理", "CR", "沟通、协调、交际能力；对应 S2D 成本模型及可行性分析", "【待填，如：需求对接、产品交互设计、可行性与成本分析】"],
  ];
  const colW = (W - 2 * M - 2 * 0.35) / 3;
  roles.forEach(([name, tag, duty, work], i) => {
    const x = M + i * (colW + 0.35);
    card(s, { x, y: 2.0, w: colW, h: 4.3 });
    s.addShape(pres.ShapeType.ellipse, { x: x + colW / 2 - 0.4, y: 2.35, w: 0.8, h: 0.8, fill: { color: RUST } });
    s.addText(tag, { x: x + colW / 2 - 0.4, y: 2.35, w: 0.8, h: 0.8, align: "center", valign: "middle", fontFace: MONO, fontSize: 13, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(name, { x: x + 0.2, y: 3.35, w: colW - 0.4, h: 0.4, align: "center", fontFace: HEAD, fontSize: 15, bold: true, color: TXT, margin: 0 });
    s.addText(duty, { x: x + 0.3, y: 3.85, w: colW - 0.6, h: 0.8, align: "center", fontFace: BODY, fontSize: 10.5, color: MUTE, margin: 0, lineSpacingMultiple: 1.2 });
    s.addShape(pres.ShapeType.line, { x: x + 0.3, y: 4.75, w: colW - 0.6, h: 0, line: { color: "E2E8ED", width: 0.75 } });
    s.addText(work, { x: x + 0.3, y: 4.9, w: colW - 0.6, h: 1.3, valign: "top", fontFace: BODY, fontSize: 10, color: MUTE, margin: 0, lineSpacingMultiple: 1.25 });
  });
  footer(s, 16, 3);
  s.addNotes(
    "姓名建议直接写角色名或昵称，指导教师姓名不能出现在任何一页。字母圆标已经代替头像，避免真人照片带来的匿名化风险。\n" +
      "建议动画：三张卡片从左到右依次 Fade 出现。"
  );
}

/* ================================================================= P17 总结：一句主张 + 三个证据 */
{
  const s = darkSlide();

  s.addText("不是选质量最高的数据，是选信息量最大的数据", {
    x: M, y: 1.05, w: W - 2 * M, h: 0.7, align: "center", fontFace: HEAD, fontSize: 30, bold: true, color: STRONG_DARK, margin: 0,
  });

  // KPI strip — same accent-line treatment as P1, for a consistent bookend
  const stats = [
    ["14.3%", "数据量 → 全量精度"],
    ["200", "工作点 → 稳健性验证"],
    ["237", "项 → 测试通过"],
  ];
  const cardW = 3.1, cardH = 0.85, cardGap = 0.4;
  const totalW = 3 * cardW + 2 * cardGap;
  const startX = (W - totalW) / 2;
  stats.forEach(([big, small], i) => {
    const x = startX + i * (cardW + cardGap);
    s.addShape(pres.ShapeType.rect, { x, y: 2.15, w: 0.03, h: cardH, fill: { color: TEAL } });
    s.addText(big, { x: x + 0.2, y: 2.15, w: cardW - 0.2, h: 0.5, fontFace: MONO, fontSize: 24, bold: true, color: AMBER, margin: 0 });
    s.addText(small, { x: x + 0.2, y: 2.68, w: cardW - 0.2, h: 0.3, fontFace: BODY, fontSize: 11, color: INV_MUTE, margin: 0 });
  });

  s.addText("连自己不利的结果，也一起交给评委", {
    x: M, y: 3.75, w: W - 2 * M, h: 0.5, align: "center", fontFace: HEAD, fontSize: 18, bold: true, color: TEAL, margin: 0,
  });
  s.addText("后续：公开工业数据集外部验证 · 更多本地大模型适配 · 跨行业场景验证", {
    x: M, y: 4.35, w: W - 2 * M, h: 0.35, align: "center", fontFace: BODY, fontSize: 11, color: "829FAF", margin: 0,
  });

  s.addText("团队昵称【待填】  ·  联系邮箱【待填，不用学校域名】  ·  演示视频二维码【待填】", {
    x: M, y: 6.6, w: W - 2 * M, h: 0.35, fontFace: BODY, fontSize: 12, color: "829FAF", margin: 0,
  });
  s.addNotes(
    "收尾：一句主张 + 三个证据（呼应封面数字），首尾呼应封面的深色调性。\n" +
      "建议动画：主张先出现 → 三张证据卡依次 Fade → 「连自己不利的结果」浮出 → 最后二维码/联系方式淡入。"
  );
}

pres.writeFile({ fileName: path.join(__dirname, "..", "IndusOpt-A14-项目简介.pptx") }).then((fileName) => {
  console.log("wrote", fileName);
});
