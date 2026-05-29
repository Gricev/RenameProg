
import os
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz


ARGS_FILE = "rename_args.txt"
PDF_EXT = ".pdf"

# Шрифт для вставляемого текста. Arial есть на любой Windows и поддерживает кириллицу.
PDF_FONT_NAME = "replfont"
PDF_FONT_FILE = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")


def parse_args_file(path: str) -> list[tuple[str, str]]:
    pairs = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(" to ", maxsplit=1)
            if len(parts) != 2:
                print(f"  Строка {lineno} пропущена (неверный формат): {line!r}")
                continue
            old, new = parts[0].strip(), parts[1].strip()
            if not old:
                print(f"  Строка {lineno} пропущена: пустая строка замены.")
                continue
            pairs.append((old, new))
    return pairs


def rename_in_name(name: str, pairs: list[tuple[str, str]]) -> str:
    out = name
    for old, new in pairs:
        if old in out:
            out = out.replace(old, new)
    return out


def find_pdf_pairs_in_content(pdf_path: str, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    doc = fitz.open(pdf_path)
    matching = []
    try:
        for old, new in pairs:
            for page in doc:
                if page.search_for(old):
                    matching.append((old, new))
                    break
    finally:
        doc.close()
    return matching


def _detect_fontsize(text_dict: dict, rect) -> float | None:
    best = None
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sr = fitz.Rect(span["bbox"])
                if sr.intersects(rect):
                    size = span.get("size")
                    if size and (best is None or abs(sr.y1 - sr.y0 - (rect.y1 - rect.y0)) < 0.5):
                        best = size
    return best


def apply_pdf_replacements(pdf_path: str, pairs: list[tuple[str, str]]) -> int:
    doc = fitz.open(pdf_path)
    total = 0
    tmp = pdf_path + ".tmp"
    try:
        for page in doc:
            text_dict = page.get_text("dict")
            occurrences = []
            for old, new in pairs:
                for rect in page.search_for(old):
                    fontsize = _detect_fontsize(text_dict, rect) or 10.0
                    occurrences.append((new, rect, fontsize))

            if not occurrences:
                continue

            # Шаг 1: стираем все старые вхождения (без вставки текста).
            for _, rect, _ in occurrences:
                page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions(images=0, graphics=0)

            # Шаг 2: вставляем новый текст в тех же позициях своим шрифтом.
            for new, rect, fontsize in occurrences:
                baseline = fitz.Point(rect.x0, rect.y1 - fontsize * 0.15)
                page.insert_text(
                    baseline,
                    new,
                    fontname=PDF_FONT_NAME,
                    fontfile=PDF_FONT_FILE,
                    fontsize=fontsize,
                )
            total += len(occurrences)
        doc.save(tmp, garbage=4, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, pdf_path)
    return total


def build_plan(directory: str, pairs: list[tuple[str, str]]) -> list[tuple[str, str, list[tuple[str, str]], bool]]:
    script_name = os.path.basename(__file__) if not getattr(sys, "frozen", False) else os.path.basename(sys.executable)
    plan = []
    for name in sorted(os.listdir(directory)):
        if name == ARGS_FILE or name == script_name:
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        is_pdf = name.lower().endswith(PDF_EXT)
        new_name = rename_in_name(name, pairs)
        pdf_pairs: list[tuple[str, str]] = []
        if is_pdf:
            try:
                pdf_pairs = find_pdf_pairs_in_content(path, pairs)
            except Exception as e:
                print(f"  Не удалось прочитать PDF {name}: {e}")
        if new_name != name or pdf_pairs:
            plan.append((name, new_name, pdf_pairs, is_pdf))
    return plan


def print_plan(plan: list[tuple[str, str, list[tuple[str, str]], bool]]) -> None:
    for old_name, new_name, pdf_pairs, _ in plan:
        rename_part = f"  -> {new_name}" if new_name != old_name else ""
        print(f"  {old_name}{rename_part}")
        if pdf_pairs:
            replacements = ", ".join(f"{o} -> {n}" for o, n in pdf_pairs)
            print(f"      штамп: {replacements}")


def execute_plan(directory: str, plan: list[tuple[str, str, list[tuple[str, str]], bool]]) -> None:
    for old_name, new_name, pdf_pairs, is_pdf in plan:
        src = os.path.join(directory, old_name)
        if pdf_pairs and is_pdf:
            try:
                n = apply_pdf_replacements(src, pdf_pairs)
                print(f"  PDF {old_name}: заменено вхождений в штампе: {n}")
            except Exception as e:
                print(f"  ОШИБКА правки PDF {old_name}: {e}")
                continue
        if new_name != old_name:
            dst = os.path.join(directory, new_name)
            if os.path.exists(dst):
                print(f"  Пропущено переименование (уже существует): {new_name}")
                continue
            os.rename(src, dst)
            print(f"  OK  {old_name}  ->  {new_name}")


def main() -> None:
    if getattr(sys, "frozen", False):
        directory = os.path.dirname(sys.executable)
    else:
        directory = os.path.dirname(os.path.abspath(__file__))
    args_path = os.path.join(directory, ARGS_FILE)

    if not os.path.exists(args_path):
        print(f"Файл с аргументами не найден: {ARGS_FILE}")
        print(f"Создайте его в той же папке, формат строки:  В671 to В345")
        sys.exit(1)

    pairs = parse_args_file(args_path)
    if not pairs:
        print("Нет корректных строк для обработки.")
        sys.exit(1)

    plan = build_plan(directory, pairs)
    print()
    if not plan:
        print("Совпадений ни в именах файлов, ни в штампах PDF не найдено.")
        return

    print("План изменений:")
    print_plan(plan)
    print()

    answer = input("Применить? [д/н]: ").strip().lower()
    if answer in ("д", "y", "да", "yes", ""):
        execute_plan(directory, plan)
        print("\nГотово.")
    else:
        print("Отменено.")


if __name__ == "__main__":
    main()