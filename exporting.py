import re
from io import BytesIO

from fpdf import FPDF


def create_markdown_file(content: str) -> BytesIO:
    markdown_file = BytesIO()
    markdown_file.write(content.encode('utf-8'))
    markdown_file.seek(0)
    return markdown_file


def _strip_inline_md(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text


def create_pdf_file(content: str) -> BytesIO:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 20, 20)
    pdf.add_page()

    for line in content.splitlines():
        stripped = line.rstrip()

        if stripped.startswith('# '):
            pdf.set_font('Helvetica', 'B', 18)
            pdf.set_text_color(40, 40, 120)
            pdf.multi_cell(0, 10, _strip_inline_md(stripped[2:]))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
        elif stripped.startswith('## '):
            pdf.set_font('Helvetica', 'B', 14)
            pdf.set_text_color(40, 40, 120)
            pdf.multi_cell(0, 8, _strip_inline_md(stripped[3:]))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
        elif stripped.startswith('### '):
            pdf.set_font('Helvetica', 'B', 12)
            pdf.multi_cell(0, 7, _strip_inline_md(stripped[4:]))
            pdf.ln(1)
        elif stripped.startswith(('- ', '* ', '+ ')):
            pdf.set_font('Helvetica', '', 11)
            pdf.multi_cell(0, 6, f'  \u2022  {_strip_inline_md(stripped[2:])}')
        elif re.match(r'^\d+\.\s', stripped):
            pdf.set_font('Helvetica', '', 11)
            pdf.multi_cell(0, 6, f'  {_strip_inline_md(stripped)}')
        elif stripped == '':
            pdf.ln(4)
        else:
            pdf.set_font('Helvetica', '', 11)
            pdf.multi_cell(0, 6, _strip_inline_md(stripped))

    pdf_buffer = BytesIO()
    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer
