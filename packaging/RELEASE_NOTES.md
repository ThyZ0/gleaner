First release.

**Windows, no Python needed:** download `Gleaner.exe` and double-click it. It reads your Documents, Desktop, Downloads and OneDrive folders, then opens in your browser. Nothing is sent anywhere and your files are never modified. It stops by itself five minutes after you close the tab.

Windows may warn that the file is from an unknown publisher (it is not code-signed): choose *More info → Run anyway*, or install with Python instead: `pip install "gleaner-docs[pdf] @ git+https://github.com/ThyZ0/gleaner"`.

What it does:
- groups the versions of each document (Word, PowerPoint, LibreOffice, PDF, Markdown, LaTeX, text), whatever their names and folders;
- says which one is the latest, and warns when the newest file is only an old or partial copy;
- finds passages written in a side copy that never reached the latest version, and writes a merged copy with them put back, highlighted (Word, LibreOffice, Markdown, text, LaTeX);
- compares any two versions word by word.
