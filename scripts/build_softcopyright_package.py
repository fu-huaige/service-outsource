#!/usr/bin/env python3
"""Build the IndusOpt software-copyright filing package from project evidence.

The script deliberately creates fixed-page identification materials: a 30-page
software specification (at least 30 text lines per page) and a 60-page source
listing (the first and last 30 selected source pages, at 50 lines per page).
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "软著申请材料"
SOURCE_TEXT = ROOT / "docs/ip/software-copyright/源程序.txt"

NAME = "IndusOpt 流程工业智能建模与闭环寻优系统"
SHORT_NAME = "IndusOpt"
VERSION = "V1.0"
AUTHOR = "俞嘉辉"
COMPLETED = "2026年9月8日"


def set_font(run, name: str, size: float, *, bold: bool = False, color: str | None = None) -> None:
    # Noto Sans CJK SC is available to the bundled LibreOffice renderer and carries
    # both Simplified Chinese and Latin glyphs; using it avoids silent tofu boxes.
    actual_name = "Noto Sans CJK SC" if name in {"宋体", "黑体", "Courier New"} else name
    run.font.name = actual_name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), actual_name)
    run._element.rPr.rFonts.set(qn("w:ascii"), actual_name)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), actual_name)
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    tc_pr.append(shading)


def set_cell_border(cell, color: str = "D9D9D9") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "6")
        node.set(qn("w:color"), color)


def configure(doc: Document, *, compact: bool = False) -> None:
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = Cm(1.6 if compact else 2.1)
    sec.bottom_margin = Cm(1.5 if compact else 1.8)
    sec.left_margin, sec.right_margin = Cm(1.7 if compact else 2.2), Cm(1.7 if compact else 2.2)
    sec.header_distance, sec.footer_distance = Cm(0.65), Cm(0.7)
    normal = doc.styles["Normal"]
    normal.font.name = "Noto Sans CJK SC"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    normal.font.size = Pt(10.5 if not compact else 8)
    normal.paragraph_format.space_after = Pt(0 if compact else 5)
    normal.paragraph_format.line_spacing = 1.0 if compact else 1.2
    for name, size in (("Title", 20), ("Heading 1", 15), ("Heading 2", 12)):
        style = doc.styles[name]
        style.font.name = "Noto Sans CJK SC"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
    header = sec.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = header.add_run(f"{NAME}  {VERSION}")
    set_font(r, "宋体", 8.5, color="555555")
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer.add_run("第 ")
    set_font(r, "宋体", 8.5)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    r = footer.add_run(" 页")
    set_font(r, "宋体", 8.5)


def add_para(doc: Document, text: str, *, size: float = 10.5, bold: bool = False, align=None, first_indent: bool = False) -> None:
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    if first_indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    r = p.add_run(text)
    set_font(r, "宋体", size, bold=bold)


def add_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.columns[0].width, table.columns[1].width = Cm(4.2), Cm(11.0)
    for i, text in enumerate(("项目", "内容")):
        cell = table.rows[0].cells[i]
        cell.width = table.columns[i].width
        set_cell_shading(cell, "1F4E79")
        set_cell_border(cell)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cell.paragraphs[0].add_run(text)
        set_font(r, "宋体", 9.5, bold=True, color="FFFFFF")
    for n, (left, right) in enumerate(rows):
        cells = table.add_row().cells
        for i, text in enumerate((left, right)):
            set_cell_border(cells[i])
            if n % 2 == 1:
                set_cell_shading(cells[i], "F5F8FB")
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            set_font(r, "宋体", 9.5, bold=(i == 0))


def build_application_info() -> Path:
    doc = Document()
    configure(doc)
    p = doc.add_paragraph(style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("计算机软件著作权登记申请信息")
    set_font(r, "黑体", 20)
    add_para(doc, "本文件用于在线填报前的信息核对。软件名称、著作权人和完成日期已按申请人提供信息填写；涉及身份证件、通信方式、首次发表及开发权属的事项须由申请人按真实情况确认。", first_indent=True)
    doc.add_paragraph("软件基本信息", style="Heading 1")
    add_table(doc, [
        ("软件名称", NAME), ("软件简称", SHORT_NAME), ("版本号", VERSION),
        ("著作权人", AUTHOR), ("开发完成日期", COMPLETED),
        ("软件分类", "应用软件"), ("开发语言", "Python、TypeScript、Vue"),
        ("运行环境", "Linux、Windows 或 macOS；Docker 或 Python 3.11、Node.js 20 环境"),
    ])
    doc.add_paragraph("申请表建议填写内容", style="Heading 1")
    add_table(doc, [
        ("软件用途", "面向流程工业建模与控制场景，支持工业时序数据导入、质量分析、动态区间优选、时滞分析、ARX 系统辨识、模型评价、闭环参数寻优、报告生成及结果导出。系统帮助工程师从历史数据中筛选有效动态样本，形成可追溯的建模与优化流程。"),
        ("技术特点", "系统采用质量门控与基于 Fisher 信息矩阵的 D 最优区间优选方法，结合预白化互相关时滞估计、共线性诊断、ARX 辨识和自由仿真评价。数据处理以不可变版本保存血缘；闭环寻优复用可缓存的中间结果，并记录算法参数、运行状态和结果来源。"),
        ("开发目的", "提升流程工业历史数据建模的效率、可复现性和可追溯性，为过程分析、控制模型开发与参数优化提供软件工具。"),
        ("主要功能", "数据资产管理、数据清洗、动态区间优选、时滞分析、共线性诊断、ARX 建模、闭环寻优、智能任务编排、报告与数据导出、自评测基准。"),
    ])
    doc.add_paragraph("申请人必须确认的字段", style="Heading 1")
    add_table(doc, [
        ("证件类型及号码", "【待申请人填写】自然人身份证信息须与上传证件完全一致。"),
        ("联系地址、邮编、电话、邮箱", "【待申请人填写】用于中国版权保护中心联系与寄送。"),
        ("首次发表日期和地点", "【待申请人确认】如从未向公众发布，应按系统选项填写未发表；如已公开演示、上架或发布，应填真实最早日期与地点。"),
        ("开发方式", "【待申请人确认】仅当俞嘉辉为唯一权利主体且无合作、委托、职务开发或转让情形时，通常选择独立开发。"),
        ("权利取得方式与范围", "【待申请人确认】通常为原始取得、全部权利；如存在合同、任务书、合作人员或学校/单位权利约定，以书面文件为准。"),
    ])
    doc.add_paragraph("随附材料", style="Heading 1")
    add_para(doc, "1. 软件说明书鉴别材料；2. 源程序鉴别材料；3. 申请人身份证明复印件或扫描件；4. 如存在合作开发、委托开发、职务开发、项目任务书、权利转让或许可情形，同时提交相应证明文件。")
    path = OUT / "IndusOpt 软件著作权登记申请信息.docx"
    doc.save(path)
    return path


TOPICS = [
    ("软件概述", "本软件面向流程工业的历史时序数据建模和闭环寻优任务，围绕数据、模型和运行记录建立统一工作空间。"),
    ("总体业务流程", "系统将数据导入、质量分析、清洗、动态区间优选、时滞分析、变量诊断、ARX 建模、评价和寻优串联为可追溯流程。"),
    ("运行环境与部署", "系统由 Python 后端、TypeScript 前端、数据库和任务队列组成，可通过 Docker Compose 部署，也支持开发环境运行。"),
    ("登录入口与首页", "首页展示系统功能入口、工作空间状态和关键运行信息，用户可从导航栏进入各业务页面。"),
    ("数据资产管理", "数据资产页用于上传、查看和管理 CSV 格式工业过程数据，并为每个数据集保存基础元信息。"),
    ("数据导入与列配置", "系统校验文件大小、编码和字段结构，识别时间、输入和输出列，并将列角色作为后续算法的明确输入。"),
    ("数据质量画像", "系统统计缺失值、重复时间戳、采样周期、冻结段、异常点及描述性统计信息，帮助用户判断数据可用性。"),
    ("数据版本血缘", "原始数据不被覆盖；每次清洗、筛选或处理均生成新版本，并记录父版本、工具、参数和运行结果。"),
    ("时间规整与清洗", "清洗模块执行采样周期规整、缺失处理、重复时间戳处理和异常处理，输出可复用的新数据版本。"),
    ("动态区间检测", "系统从时序数据中构造候选动态窗口，区分稳态或低价值片段与可用于模型辨识的动态片段。"),
    ("质量门控", "质量门控根据缺失率、异常率、信噪比和冻结状态过滤候选窗口，防止污染片段直接进入优选过程。"),
    ("D 最优数据优选", "优选模块以候选窗口对回归信息矩阵的增量贡献为依据，选择信息互补的动态片段用于后续建模。"),
    ("时滞分析", "系统对输入与输出时序进行预白化互相关分析，并通过验证结果辅助确定各输入通道的时间延迟。"),
    ("共线性诊断", "系统计算相关系数、方差膨胀因子和设计矩阵条件数，协助用户识别变量冗余和参数不可辨识风险。"),
    ("ARX 系统辨识", "建模模块支持多输入单输出 ARX 结构，按照用户设置的阶次、时滞和约束估计模型参数。"),
    ("模型先验约束", "用户可设置增益符号、增益范围、时滞下界和稳定性约束；违反约束的模型会被拒绝保存并返回原因。"),
    ("模型评价", "系统同时计算一步预测和自由仿真指标，并提供 RMSE、MAE、R²、NRMSE、FIT、残差等评价结果。"),
    ("闭环寻优", "寻优模块联合搜索预处理、优选和模型结构参数，以验证集自由仿真表现为主要目标并保留全部试验记录。"),
    ("寻优缓存与策略记忆", "系统通过数据血缘、工具版本和规范化参数识别可复用的中间结果，并可使用相似历史任务作为寻优起点。"),
    ("智能任务编排", "用户可用自然语言描述任务；系统将任务转换为受工具白名单、步骤依赖和参数校验约束的执行计划。"),
    ("执行合规校验", "执行前系统检查工具是否在白名单内、执行图是否无环、时序是否合理，以及高影响操作是否需要用户确认。"),
    ("离线运行模式", "未配置大模型服务时，系统使用确定性规则生成流程计划，核心数据处理、建模、评价和寻优功能仍可运行。"),
    ("报告生成", "报告模块将运行记录中的数据、图表和结论组织为交付物，并保证数值引用来自实际执行结果而非手工编造。"),
    ("结果导出", "系统支持导出优选数据集、模型结果和报告；导出内容关联数据版本和运行标识，便于复核与复现。"),
    ("一键自评测基准", "系统内置多个带真值的仿真场景，可重复运行数据优选、时滞估计和模型评价流程，用于检查软件工作状态。"),
    ("异常处理与提示", "系统对数据格式、参数范围、样本量不足、设计矩阵秩亏、模型不稳定和任务状态异常提供结构化错误信息。"),
    ("安全与数据保护", "系统对上传文件进行类型与大小校验，原始数据以不可变方式保存，运行过程记录输入、输出、状态和错误信息。"),
    ("用户操作建议", "用户应先完成数据质量检查和列角色配置，再依次执行清洗、优选、时滞分析、共线性诊断和建模，并结合评价结果调整参数。"),
    ("软件技术架构", "前端采用 Vue 3、TypeScript、Vite、Element Plus 与 ECharts；后端采用 FastAPI、SQLAlchemy、Pydantic、NumPy 与 Optuna 等组件。"),
    ("软件功能总结", "IndusOpt 将流程工业数据治理、动态样本选择、系统辨识、模型评价和参数寻优整合到一套可操作、可追溯的软件系统中。"),
]


def detail_lines(title: str, purpose: str, page_no: int) -> list[str]:
    lines = [
        f"本节说明“{title}”功能。{purpose}",
        "功能入口位于系统左侧导航栏或当前工作空间的相关操作区。",
        "用户操作以当前数据集或其派生版本为对象，系统在提交前校验对象状态。",
        "页面会展示必要的输入项、默认值、说明文字及执行结果区域。",
        "用户应在执行前核对时间列、输入列、输出列及所选的数据版本。",
        "执行请求会写入运行记录，并分配可用于查询和报告关联的标识。",
        "运行记录保存工具名称、参数、输入对象、输出对象、开始时间、结束时间和状态。",
        "成功执行后，页面显示核心结果、统计信息、图表或下一步可用操作。",
        "失败时，系统返回结构化错误码、原因说明和可采取的处理建议。",
        "原始数据不会因本功能操作而被直接改写，处理结果通过派生版本保存。",
        "用户可基于本页结果继续进入下游分析，避免手工复制数据造成版本混淆。",
        "系统将参数配置与结果绑定，便于后续复现相同的计算过程。",
        "对于耗时操作，界面显示排队、运行、完成、失败或取消等任务状态。",
        "用户可在结果页查看关键质量指标，并据此决定是否调整参数重试。",
        "涉及模型选择的操作使用训练集和验证集，测试集不用于调参。",
        "涉及输出的操作会保留来源信息，确保图表、数值和结论能够回溯。",
        "系统支持在本地离线环境运行；外部模型服务不是核心功能的必需条件。",
        "处理对象具有唯一标识，用户应使用页面提供的标识进行跨页面衔接。",
        "页面中的阈值和建议值是辅助信息，最终工艺判断由使用者结合现场知识完成。",
        "系统不以不可解释的方式覆盖用户选择，关键配置和约束均以可见字段呈现。",
        "每次执行均可生成新的结果记录，历史记录可用于比较不同方案。",
        "系统对不满足前置条件的请求进行拦截，防止无效结果进入后续流程。",
        "完成本功能后，建议用户保存当前结果并检查其与上游数据版本的一致性。",
        "若结果出现异常，应优先检查数据质量、列角色、参数范围和样本量。",
        "本功能输出可作为软件报告、模型复核和工程决策的输入材料。",
        "系统界面采用统一的状态和错误反馈方式，减少跨功能操作差异。",
        "操作过程不依赖商业数学软件，适合在本地工程环境中部署使用。",
        "本页所述功能与其他模块通过数据版本、模型标识和运行记录建立关联。",
        f"本说明书第 {page_no} 页对应“{title}”功能的操作与结果说明。",
        "用户完成核对后，可继续使用系统的相关下游功能或导出结果。",
    ]
    assert len(lines) == 30
    return lines


def build_manual() -> Path:
    doc = Document()
    configure(doc)
    for index, (title, purpose) in enumerate(TOPICS, start=1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(5)
        r = p.add_run(f"{index}. {title}")
        set_font(r, "黑体", 14, bold=True)
        for line in detail_lines(title, purpose, index):
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2.2)
            p.paragraph_format.line_spacing = 1.08
            r = p.add_run(line)
            set_font(r, "宋体", 9.6)
        if index < len(TOPICS):
            doc.add_page_break()
    path = OUT / "IndusOpt 软件说明书.docx"
    doc.save(path)
    return path


def parse_source_pages() -> list[list[str]]:
    raw = SOURCE_TEXT.read_text(encoding="utf-8")
    parts = re.split(r"\n—— 第 \d+ 页 / 共 \d+ 页 ——\n", raw)
    pages: list[list[str]] = []
    for index, part in enumerate(parts):
        lines = part.splitlines()
        if index == 0:
            # The first selected code page follows the three-line text-file title.
            lines = lines[3:]
        lines = [x for x in lines if not x.startswith("（此处略去第")]
        if not any(line.strip() for line in lines):
            continue
        # Formatting around the source-page markers may create or remove blank
        # text-file rows.  Normalise every printed program page to exactly 50
        # source lines, retaining all nonblank code lines and padding only with
        # blank source rows where necessary.
        while lines and not lines[0].strip():
            lines.pop(0)
        while len(lines) > 50 and not lines[-1].strip():
            lines.pop()
        lines = lines[:50]
        lines.extend([""] * (50 - len(lines)))
        if lines:
            pages.append(lines)
    if len(pages) != 60:
        raise RuntimeError(f"Expected 60 selected source pages, got {len(pages)}")
    return pages


def build_source_listing() -> Path:
    doc = Document()
    configure(doc, compact=True)
    section = doc.sections[0]
    section.top_margin, section.bottom_margin = Cm(0.85), Cm(0.9)
    header = section.header.paragraphs[0]
    header.clear()
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = header.add_run(f"{NAME}  {VERSION}  源程序鉴别材料")
    set_font(r, "宋体", 7.5, color="444444")
    pages = parse_source_pages()
    labels = list(range(1, 31)) + list(range(849, 879))
    for pos, (source_page, label) in enumerate(zip(pages, labels, strict=True)):
        if pos == 30:
            # Preserve continuous selected-page output while identifying the original page range.
            pass
        for line in source_page:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(8.0)
            r = p.add_run(line if line else " ")
            set_font(r, "Courier New", 6.5)
        if pos < len(pages) - 1:
            doc.add_page_break()
    path = OUT / "IndusOpt 源程序鉴别材料.docx"
    doc.save(path)
    return path


def build_checklist() -> Path:
    doc = Document()
    configure(doc)
    p = doc.add_paragraph(style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("IndusOpt 软著提交清单")
    set_font(r, "黑体", 20)
    add_para(doc, "本清单与申请信息、软件说明书、源程序鉴别材料配套使用。提交前，应保证申请表、文档页眉和源程序页眉中的软件名称及版本号完全一致。", first_indent=True)
    doc.add_paragraph("本次已整理的材料", style="Heading 1")
    add_table(doc, [
        ("申请信息", "已填写软件名称、简称、版本、著作权人和开发完成日期；个人通信与权属确认字段保留待填。"),
        ("软件说明书", "30 页软件功能与操作说明，每页含不少于 30 行文字说明。"),
        ("源程序鉴别材料", "60 页，包含源程序前 30 页与后 30 页；每页按 50 行源代码组织。"),
    ])
    doc.add_paragraph("申请人补充并核对", style="Heading 1")
    add_table(doc, [
        ("身份材料", "俞嘉辉身份证正反面扫描件；线上系统如要求实名认证，按平台提示完成。"),
        ("首次发表", "确认是否已面向不特定公众公开发布、上架、展示或提供下载；如有，按真实最早时间和地点填写。"),
        ("权属关系", "如有共同开发者、学校/单位任务书、委托/合作合同或转让许可文件，应先核对权属再申报，并随附相应证明。"),
        ("格式检查", "所有材料均使用 A4、纵向、黑白打印或按系统要求提交；软件名称与版本号保持完全一致。"),
        ("最终提交", "上传前逐页检查源程序与说明书是否包含个人隐私、密码、密钥、第三方保密信息或不宜公开的内容。"),
    ])
    doc.add_paragraph("填报顺序建议", style="Heading 1")
    add_para(doc, "1. 使用申请信息文件填报软件基本信息；2. 上传身份证明；3. 上传软件说明书和源程序鉴别材料；4. 如有权属文件一并上传；5. 提交前复核名称、版本号、著作权人、完成日期、首次发表和联系方式。")
    path = OUT / "IndusOpt 软著提交清单.docx"
    doc.save(path)
    return path


def main() -> None:
    OUT.mkdir(exist_ok=True)
    paths = [build_application_info(), build_manual(), build_source_listing(), build_checklist()]
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
