import csv
import io
import json
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RANKING_HEADERS = ["Rank", "Supplier", "Absolute score", "PPI", "Submitted on", "Experience", "Rank note"]
SCORE_HEADERS = [
    "Supplier",
    "Criterion id",
    "Criterion",
    "Weight",
    "Max points",
    "Points",
    "Status",
    "Benchmark",
    "Gap",
    "Relative %",
    "Confidence",
    "Quote found",
    "Quote page",
    "Quote",
    "Reason",
]
AUDIT_HEADERS = ["When", "Action", "Supplier", "Criterion id", "Old value", "New value", "Note"]


def run_json(run):
    return json.dumps(run, indent=2, ensure_ascii=False, default=str)


def ranking_rows(run):
    rows = []
    for supplier in run["suppliers"]:
        rows.append(
            [
                supplier["rank"],
                supplier["supplier"],
                supplier["absolute"],
                supplier["ppi"],
                supplier["submitted_on"],
                supplier["experience"],
                supplier.get("rank_note", ""),
            ]
        )
    return rows


def score_rows(run):
    rows = []
    for supplier in run["suppliers"]:
        for item in supplier["items"]:
            rows.append(
                [
                    supplier["supplier"],
                    item["id"],
                    item["title"],
                    item["weight"],
                    item["max_points"],
                    item["points"],
                    item["status"],
                    item.get("benchmark"),
                    item.get("gap"),
                    item.get("relative"),
                    item.get("confidence"),
                    "yes" if item.get("quote_ok") else "no",
                    item.get("quote_page"),
                    item.get("quote", ""),
                    item.get("reason", ""),
                ]
            )
    return rows


def audit_rows(run):
    rows = []
    for entry in run.get("audit", []):
        rows.append(
            [
                entry["at"],
                entry["action"],
                entry.get("supplier") or "",
                entry.get("criterion_id"),
                entry.get("old_value"),
                entry.get("new_value"),
                entry.get("note") or "",
            ]
        )
    return rows


def scores_csv(run):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Run id", "Rank", *SCORE_HEADERS])
    ranks = {supplier["supplier"]: supplier["rank"] for supplier in run["suppliers"]}
    for row in score_rows(run):
        writer.writerow([run["run_id"], ranks[row[0]], *row])
    return buffer.getvalue()


def add_sheet(book, title, headers, rows, first=False):
    sheet = book.active if first else book.create_sheet()
    sheet.title = title
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(["" if value is None else value for value in row])
    for column in sheet.columns:
        longest = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(longest + 2, 10), 60)
    sheet.freeze_panes = "A2"


def run_workbook(run):
    book = Workbook()
    add_sheet(book, "Ranking", RANKING_HEADERS, ranking_rows(run), first=True)
    add_sheet(book, "Scores", SCORE_HEADERS, score_rows(run))
    add_sheet(book, "Audit", AUDIT_HEADERS, audit_rows(run))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def cell(value, style):
    if value is None:
        value = ""
    return Paragraph(escape(str(value)), style)


def table(headers, rows, widths, style):
    head_style = style.clone("head", fontName="Helvetica-Bold")
    data = [[cell(value, head_style) for value in headers]]
    for row in rows:
        data.append([cell(value, style) for value in row])
    grid = Table(data, colWidths=widths, repeatRows=1)
    grid.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf2")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa4b2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return grid


def run_facts(run):
    facts = [
        f"Run id: {run['run_id']}",
        f"Name: {run['name']}",
        f"State: {run['state']}",
        f"Model: {run['model']}",
        f"Started: {run['started_at']}",
        f"Finished: {run.get('finished_at') or '-'}",
        f"Locked: {'yes, ' + str(run.get('locked_at')) if run['locked'] else 'no'}",
    ]
    return facts


def short_scores(run):
    rows = []
    for row in score_rows(run):
        rows.append(row[:3] + row[5:11] + [row[14]])
    return rows


def run_pdf(run):
    styles = getSampleStyleSheet()
    body = styles["BodyText"].clone("small", fontSize=8, leading=10)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"RFP evaluation {run['run_id']}",
    )
    story = [Paragraph(escape(f"RFP evaluation report: {run['name']}"), styles["Title"])]
    for fact in run_facts(run):
        story.append(Paragraph(escape(fact), styles["BodyText"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Ranking", styles["Heading2"]))
    ranking_widths = [14 * mm, 45 * mm, 25 * mm, 20 * mm, 25 * mm, 20 * mm, 120 * mm]
    story.append(table(RANKING_HEADERS, ranking_rows(run), ranking_widths, body))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Scores by criterion", styles["Heading2"]))
    headers = SCORE_HEADERS[:3] + SCORE_HEADERS[5:11] + ["Reason"]
    widths = [32 * mm, 12 * mm, 32 * mm, 14 * mm, 22 * mm, 18 * mm, 14 * mm, 16 * mm, 16 * mm, 97 * mm]
    story.append(table(headers, short_scores(run), widths, body))
    notes = run.get("notes") or []
    if notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Warnings", styles["Heading2"]))
        for note in notes:
            story.append(Paragraph(escape(str(note)), body))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Audit trail", styles["Heading2"]))
    audit = audit_rows(run)
    if audit:
        audit_widths = [35 * mm, 30 * mm, 40 * mm, 20 * mm, 20 * mm, 20 * mm, 108 * mm]
        story.append(table(AUDIT_HEADERS, audit, audit_widths, body))
    else:
        story.append(Paragraph("No manual changes were made.", body))
    document.build(story)
    return buffer.getvalue()
