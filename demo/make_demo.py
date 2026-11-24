"""Build a small, entirely fictional folder of documents to try Gleaner (and to take the README screenshots).

    python demo/make_demo.py [TARGET]     default: ./gleaner-demo
Then: gleaner TARGET
"""
import os
import sys
import zipfile
from xml.sax.saxutils import escape

INTRO = "This report presents the design of a small fixed-wing drone built by our group to survey crops at low altitude."
GOAL = "The aircraft must fly for forty minutes, carry a two hundred gram camera and be assembled by two people in the field."
WING = "We chose a high wing with a span of one metre sixty because it keeps the camera below the fuselage and stable in gusts."
WING2 = "We chose a high wing with a span of one metre eighty, as the longer span lowered the stall speed by two metres per second in the tunnel."
MOTOR = "The motor is a brushless outrunner of eight hundred kV driving a ten inch folding propeller."
BATTERY = "A four cell battery of five thousand milliampere hours gives the required endurance with a safety margin of fifteen percent."
TESTS = "The first flight tests took place on a calm morning and showed a slight tendency to roll to the left at low speed."
TESTS2 = "Flight tests on three mornings showed a slight tendency to roll to the left at low speed, which we traced to a warped aileron."
COST = "The total cost of the parts reached three hundred and twelve euros, below the budget given by the department."
CONC = "In conclusion the drone meets its requirements and the design can be reused by next year's students."
# written by a teammate in the copy they were emailed, never merged back
SIDE1 = "Safety note: the battery must be stored in a fireproof bag and never charged unattended, as required by the lab rules."
SIDE2 = "We thank the workshop staff, who lent us the foam cutter and helped us repair the landing gear twice."
OLD = "A first idea was a flying wing, which we abandoned because the camera would have unbalanced it."

LETTER_A = ["Dear hiring team,", "I am applying for the summer internship in your structures department, which I discovered at the school career fair.",
            "During my second year I designed and tested a small drone with three classmates, and I led the wind tunnel campaign.",
            "I would be glad to bring this hands-on experience to your team and to learn from your engineers.", "Kind regards,"]
LETTER_B = [LETTER_A[0], "I am applying for the summer internship in your structures department, which I discovered through your engineering blog.",
            LETTER_A[2], "I also enjoy programming, and wrote the data logging scripts used during our flight tests.", LETTER_A[3], LETTER_A[4]]


def docx(path, paras, modified):
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(p)}</w:t></w:r></w:p>" for p in paras)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                   f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified></cp:coreProperties>')


def main(target):
    j = lambda *p: os.path.join(target, *p)
    for d in ("Drone project/drafts", "Drone project/from Sam", "Downloads", "Internship"):
        os.makedirs(j(d), exist_ok=True)
    docx(j("Drone project/drafts/Report.docx"), ["Drone project report", INTRO, GOAL, OLD, WING, MOTOR, BATTERY], "2026-03-02T18:10:00Z")
    docx(j("Drone project/from Sam/Report - Sam's edits.docx"),
         ["Drone project report", INTRO, GOAL, OLD, WING, MOTOR, BATTERY, SIDE1, TESTS, SIDE2], "2026-03-09T21:40:00Z")
    docx(j("Drone project/drafts/Report_v2.docx"), ["Drone project report", INTRO, GOAL, WING, MOTOR, BATTERY, TESTS, COST], "2026-03-12T16:05:00Z")
    docx(j("Downloads/Report_v2 (1).docx"), ["Drone project report", INTRO, GOAL, WING, MOTOR, BATTERY, TESTS, COST], "2026-03-12T16:05:00Z")
    final = ["Drone project report", INTRO, GOAL, WING2, MOTOR, BATTERY, TESTS2, COST, CONC]
    docx(j("Drone project/Report_FINAL.docx"), final, "2026-03-20T23:52:00Z")
    with open(j("Drone project/Report_FINAL.md"), "w", encoding="utf-8") as f:  # an export of the final
        f.write("# " + final[0] + "\n\n" + "\n\n".join(final[1:]) + "\n")
    docx(j("Internship/Cover letter.docx"), LETTER_A, "2026-01-15T10:00:00Z")
    docx(j("Internship/Cover letter - Airframes.docx"), LETTER_B, "2026-02-03T09:30:00Z")
    print(f"Demo folder ready: {os.path.abspath(target)}\nTry: gleaner \"{os.path.abspath(target)}\"")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gleaner-demo")
