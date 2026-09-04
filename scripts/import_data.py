import sys
import os
import csv
import logging
import asyncio

# Добавляем корневую папку в путь поиска модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import add_student
from app.models import Student

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def import_from_tsv(file_path: str):
    """
    Импорт данных из файла TSV (табуляция).
    Ожидается, что первая строка - заголовки, соответствующие полям Student.
    """
    if not os.path.exists(file_path):
        logger.error(f"Файл {file_path} не найден.")
        return

    # Карта соответствия русских заголовков полям модели
    headers_map = {
        'ФИО': 'fio',
        'Дата рождения': 'birth_date',
        'ФШР id': 'fsr_id',
        'ФИДЕ id': 'fide_id',
        'Город': 'city',
        'Lichess': 'lichess',
        'Stepchess': 'stepchess',
        'Разряд': 'rank',
    }

    students_added = 0
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Читаем первую строку (заголовки)
            reader = csv.DictReader(f, delimiter='\t')
            
            for row in reader:
                # Создаем словарь для модели, заменяя русские ключи на английские
                student_data = {}
                for rus_key, eng_key in headers_map.items():
                    val = row.get(rus_key)
                    if val and val.strip():
                        student_data[eng_key] = val.strip()

                
                if student_data.get('fio'):
                    student = Student(**student_data)
                    student.update_calculated_fields()  # Вычисляем возраст и группы
                    await add_student(student)
                    students_added += 1
                    logger.info(f"Добавлен: {student_data['fio']}")

        logger.info(f"Импорт завершен! Успешно добавлено учеников: {students_added}")

    except Exception as e:
        logger.error(f"Ошибка при импорте: {e}")

if __name__ == "__main__":
    # Убедись, что файл пример.txt сохранен в формате TSV (из Excel: Сохранить как -> Текст (разделитель табуляция))
    asyncio.run(import_from_tsv("пример.txt"))
