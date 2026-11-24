---
name: gleaner
description: Find every version of one of the user's documents (Word, PowerPoint, LibreOffice, PDF, Markdown, LaTeX, text) on this computer, tell which file is the latest, and list passages written in an older or side copy that never reached the latest. Use when the user asks "which is the latest version of my report", "I have several copies of this file", "did I lose a paragraph", "my teammate edited another copy", "compare these versions", or wants to clean up v2/final/final(1) files. Not for code repositories under git, and not for spreadsheets or images.
---

# Gleaner

Gleaner is a local, read-only command. It never modifies, moves or deletes files.

## Steps

1. Check it is installed: `gleaner --version`. If not, tell the user it needs
   `pip install "gleaner-docs[pdf] @ git+https://github.com/ThyZ0/gleaner"` and ask before installing.
2. One document the user names: `gleaner show "<file>" --json`, adding the folders where other copies may be
   (Documents, Desktop, Downloads, OneDrive, a USB drive the user mentions): `gleaner show "<file>" "<folder>" ... --json`.
   Without folders it only looks next to the file.
   Several documents or "what do I have in duplicate": `gleaner scan "<folder>" ... --json`.
3. Answer from the JSON, in the user's words:
   - the latest version: `versions[head].files[0].path` and its date (`doc_time`, `time_source` = "document" means the date saved inside the file, "file" means the file system date, less reliable);
   - how many versions and where they are;
   - `stranded`: passages written in another copy and missing from the latest. Quote each one, say which file holds it (`versions[source].files[0].path`) and where it belongs (`after`; `slide` for presentations). These are the most important thing to report.
   - `removed`: passages deleted on the latest version's own line, probably on purpose. Mention the count only, unless asked.
4. If the user thinks another file is the real latest, say so: the app can recompute with another version as latest (`gleaner` opens it; button "Treat as latest").
5. To put the left-behind passages back, offer `gleaner show "<file>" <folders> --merge`: it writes a NEW file
   "<latest> (gleaned).docx" (or .odt/.md/.txt/.tex) next to the latest version, passages highlighted in yellow, original
   untouched. Run it only when the user agrees, and give them the path it prints. Never edit their documents yourself.

For a visual comparison, `gleaner "<folder>"` opens the local app in the browser.
