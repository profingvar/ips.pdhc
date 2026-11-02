"""plans/eps_state_plan.docx — the EPS + patient-state plan, typeset for paper.

Same approach as alert.pdhc/make_plan_docx.py and
icd11.pdhc/documents/make_plan_docx.py: pandoc for structure, python-docx for
the typography pandoc leaves unset (page size among them).

Tables get 10pt rather than alert's 9.5: the widest here is 4 columns, not 5,
so the extra half point buys readability without wrapping a row.
"""
import subprocess, docx
from docx.shared import Pt, Inches, Mm

SRC = 'plans/eps_state_plan.md'
OUT = 'plans/eps_state_plan.docx'
TITLE = 'EPS och patient-state i ips.pdhc — plan'

subprocess.run(['pandoc', SRC, '-o', OUT, '--from=gfm',
                '--toc', '--toc-depth=3',
                '--metadata', f'title={TITLE}',
                '-V', 'lang=sv'], check=True)

d = docx.Document(OUT)

for sec in d.sections:
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Inches(0.8)
    sec.top_margin = sec.bottom_margin = Inches(0.8)

for name in ('Body Text', 'First Paragraph', 'Compact', 'Normal'):
    st = d.styles[name]
    st.font.size = Pt(11)
    st.paragraph_format.line_spacing = 1.15
    st.paragraph_format.space_after = Pt(6)

for name, size, before in (('Heading 1', 18, 24), ('Heading 2', 15, 18),
                           ('Heading 3', 12.5, 14)):
    st = d.styles[name]
    st.font.size = Pt(size)
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(6)
    # Never orphan a heading at the foot of a page.
    st.paragraph_format.keep_with_next = True

cs = d.styles['Source Code']
cs.font.name, cs.font.size = 'Courier New', Pt(9)
v = d.styles['Verbatim Char']
v.font.name, v.font.size = 'Courier New', Pt(10)

for t in d.tables:
    for row in t.rows:
        for cell in row.cells:
            for par in cell.paragraphs:
                par.paragraph_format.space_after = Pt(2)
                par.paragraph_format.line_spacing = 1.0
                for r in par.runs:
                    r.font.size = Pt(10)

d.save(OUT)
print("wrote", OUT)
