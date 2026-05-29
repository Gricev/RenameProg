import os
import sys
import shutil

sys.path.insert(0, r"C:\Users\Inzhener\PycharmProjects\PythonProject")

import pymupdf
import rename_files

tmpdir = r"C:\Users\Inzhener\AppData\Local\Temp\rename_test"
font_file = r"C:\Windows\Fonts\arial.ttf"

# 1. Создаём тестовый PDF с кириллицей в штампе
pdf_path = os.path.join(tmpdir, "Чертеж_В671.pdf")
doc = pymupdf.open()
page = doc.new_page()
# имитация: основной штамп (правый нижний) и доп. графа (верхний левый)
page.insert_text((100, 100), "Чертеж В671 — рама", fontname="ar", fontfile=font_file, fontsize=12)
page.insert_text((100, 130), "Доп. графа: В671", fontname="ar", fontfile=font_file, fontsize=10)
doc.save(pdf_path)
doc.close()
print("Создан тестовый PDF:", pdf_path)

# 2. Поиск
pairs = [("В671", "В345")]
found = rename_files.find_pdf_pairs_in_content(pdf_path, pairs)
print("Найденные пары для замены:", found)
assert found == pairs, f"Ожидалось {pairs}, получено {found}"

# 3. Применение замены
n = rename_files.apply_pdf_replacements(pdf_path, pairs)
print("Выполнено замен:", n)
assert n == 2, f"Ожидалось 2 замены, получено {n}"

# 4. Проверяем, что текст изменился
doc = pymupdf.open(pdf_path)
text = doc[0].get_text()
doc.close()
print("Текст после правки:")
print(text)
assert "В345" in text, "Новый текст В345 не найден"
assert "В671" not in text, "Старый текст В671 не должен присутствовать"

print("\n=== SMOKE TEST PASSED ===")