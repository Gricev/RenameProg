
import math
import os
import sys

try:
    import pymupdf as fitz
except ImportError:
    import fitz


ARGS_FILE = "rename_args.txt"
PDF_EXT = ".pdf"

# Шрифт для вставляемого текста. GOST_A поддерживает кириллицу и соответствует ЕСКД.
PDF_FONT_NAME = "replfont"
PDF_FONT_FILE = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "GOST_A.TTF")
# Матрицы сдвига для наклона 75° по ГОСТ 2.304 (tan(15°) ≈ 0.268).
# _GOST_SHEAR — для 0° и ±90°; _GOST_SHEAR_INV — для 180° (зеркальный наклон).
_GOST_SHEAR     = fitz.Matrix(1, 0,  math.tan(math.radians(15)), 1, 0, 0)
_GOST_SHEAR_INV = fitz.Matrix(1, 0, -math.tan(math.radians(15)), 1, 0, 0)
# Отступ базовой линии от края rect в долях fontsize. Увеличьте, чтобы поднять текст.
_BASELINE_OFFSET = 0.25
# Сдвиг точки вставки в долях fontsize (+ вправо, - влево).
_TEXT_X_OFFSET = 0.0


def parse_args_file(path: str) -> tuple[list[tuple[str, str]], bool]:
    pairs = []
    apply_pdf = True
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line and " to " not in line:
                key, _, val = line.partition("=")
                if key.strip().lower() == "apply_pdf_replacement":
                    apply_pdf = val.strip().lower() not in ("false", "0", "no", "нет")
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
    return pairs, apply_pdf


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


def _detect_span_props(text_dict: dict, rect) -> tuple[float | None, tuple[float, float], fitz.Point | None]:
    """Возвращает (fontsize, dir, origin) ближайшего к rect спана.
    origin — точная базовая линия символа: используется для выравнивания вставки."""
    best_size = None
    best_dir = (1.0, 0.0)
    best_origin = None
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sr = fitz.Rect(span["bbox"])
                if sr.intersects(rect):
                    size = span.get("size")
                    if size and (best_size is None or abs(sr.y1 - sr.y0 - (rect.y1 - rect.y0)) < 0.5):
                        best_size = size
                        transform = span.get("transform")
                        if transform:
                            dx, dy = transform[0], transform[1]
                            norm = math.hypot(dx, dy)
                            best_dir = (dx / norm, dy / norm) if norm > 0 else (1.0, 0.0)
                        else:
                            best_dir = span.get("dir", (1.0, 0.0))
                        o = span.get("origin")
                        if o:
                            best_origin = fitz.Point(o)
    return best_size, best_dir, best_origin


def apply_pdf_replacements(pdf_path: str, pairs: list[tuple[str, str]]) -> int:
    doc = fitz.open(pdf_path)
    total = 0
    tmp = pdf_path + ".tmp"
    try:
        for page in doc:
            text_dict = page.get_text("rawdict")
            occurrences = []
            for old, new in pairs:
                all_quads = page.search_for(old, quads=True)
                for rect in page.search_for(old):
                    # Ищем первый квад, пересекающийся с rect, для определения направления.
                    # search_for(quads=True) возвращает по одному квadu на символ,
                    # поэтому нельзя просто zip — используем пересечение.
                    dir_vec = (1.0, 0.0)
                    for quad in all_quads:
                        if rect.intersects(quad.rect):
                            dx = quad.ur.x - quad.ul.x
                            dy = quad.ur.y - quad.ul.y
                            norm = math.hypot(dx, dy)
                            if norm > 0:
                                dir_vec = (dx / norm, dy / norm)
                            break
                    fontsize, _, origin = _detect_span_props(text_dict, rect)
                    fontsize = fontsize or 10.0
                    occurrences.append((new, rect, fontsize, dir_vec, origin))

            if not occurrences:
                continue

            # Шаг 1: стираем старые вхождения с отступом, чтобы не перекрывать линии ячейки.
            for _, rect, fontsize, _, _ in occurrences:
                pad = fontsize * 0.2
                erase_rect = fitz.Rect(rect.x0 + pad, rect.y0 + pad, rect.x1 - pad, rect.y1 - pad)
                page.add_redact_annot(erase_rect, fill=(1, 1, 1))
            page.apply_redactions(images=0, graphics=0)

            # Шаг 2: вставляем новый текст с наклоном 75° (ГОСТ) и учётом поворота.
            for new, rect, fontsize, dir_vec, origin in occurrences:
                dx, dy = dir_vec
                angle = math.degrees(math.atan2(dy, dx))
                # Базовая линия берётся из span["origin"] для точного выравнивания с оригиналом.
                if abs(angle) < 1:
                    y = origin[1] if origin else rect.y1 - fontsize * _BASELINE_OFFSET
                    baseline = fitz.Point(rect.x0, y)
                elif abs(angle + 90) < 1:
                    x = origin[0] if origin else rect.x1 - fontsize * _BASELINE_OFFSET
                    baseline = fitz.Point(x, rect.y1)
                elif abs(angle - 90) < 1:
                    x = origin[0] if origin else rect.x0 + fontsize * _BASELINE_OFFSET
                    baseline = fitz.Point(x, rect.y0)
                elif abs(abs(angle) - 180) < 1:
                    y = origin[1] if origin else rect.y0 + fontsize * _BASELINE_OFFSET
                    baseline = fitz.Point(rect.x1, y)
                else:
                    y = origin[1] if origin else rect.y1 - fontsize * _BASELINE_OFFSET
                    baseline = fitz.Point(rect.x0, y)
                mat = _GOST_SHEAR * fitz.Matrix(angle)
                page.insert_text(
                    baseline,
                    new,
                    fontname=PDF_FONT_NAME,
                    fontfile=PDF_FONT_FILE,
                    fontsize=fontsize,
                    morph=(baseline, mat),
                )
            total += len(occurrences)
        doc.save(tmp, garbage=4, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, pdf_path)
    return total


def build_plan(directory: str, pairs: list[tuple[str, str]], apply_pdf: bool = True) -> list[tuple[str, str, list[tuple[str, str]], bool]]:
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
        if is_pdf and apply_pdf:
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

    pairs, apply_pdf = parse_args_file(args_path)
    if not pairs:
        print("Нет корректных строк для обработки.")
        sys.exit(1)

    if not apply_pdf:
        print("Режим: только переименование файлов (замена в штампах PDF отключена).")

    plan = build_plan(directory, pairs, apply_pdf)
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