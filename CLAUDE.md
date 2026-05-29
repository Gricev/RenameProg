# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

`rename_files.py` is a batch utility for ESKD-style drawings:
1. Renames files in its working directory according to substitution rules in `rename_args.txt`.
2. For `.pdf` files (textual, not scans) it also rewrites occurrences of the same substrings inside the document — typically the designation code in the title block (правый нижний угол, штамп) and the rotated copy in the top-left auxiliary box (графа 26).

It previews the full plan and asks for confirmation before touching anything. Ships as both a Python script and a standalone Windows .exe built with PyInstaller.

## Running

```powershell
# Run as script
.venv\Scripts\python.exe rename_files.py

# Build the .exe
.venv\Scripts\pyinstaller.exe --onefile rename_files.py
```

Dependencies: `pymupdf` (installed in `.venv`).

## rename_args.txt format

```
# comment lines are ignored
В671 to В345
old_fragment to new_fragment
```

One rule per line: `<substring> to <substring>`. Each rule is applied independently to every file name AND, for `.pdf` files, to every page of the PDF content.

## Key design notes

- **Working directory when frozen**: `sys.frozen` → directory of `sys.executable`. So `rename_args.txt` must sit next to the `.exe`, not the source.
- **Skipped files**: `rename_args.txt` and the script/exe itself are excluded from processing.
- **PDF text replacement** uses a two-step approach in `apply_pdf_replacements`:
  1. `add_redact_annot(rect, fill=(1,1,1))` + `apply_redactions(images=0, graphics=0)` erases the old text without touching line art or images.
  2. `page.insert_text(baseline, new, fontname=PDF_FONT_NAME, fontfile=PDF_FONT_FILE, ...)` re-inserts the new text at the same position. The font is `C:\Windows\Fonts\arial.ttf` because PyMuPDF's built-in base14 fonts (`helv`, `tiro`, etc.) do not support Cyrillic. Original drawing fonts are NOT preserved — replaced fragments will visually render in Arial.
  3. Font size is detected from the nearest text span via `page.get_text("dict")` — falls back to 10pt if not found.
- **Baseline calculation**: `rect.y1 - fontsize * 0.15` is an empirical offset from `search_for` rect bottom to text baseline. Tune if replaced text drifts vertically on real CAD-exported PDFs.
- **Atomic save**: PDFs are written to `<path>.tmp` first, then `os.replace`d into place.
- `main.py` is empty and unrelated to this utility.
