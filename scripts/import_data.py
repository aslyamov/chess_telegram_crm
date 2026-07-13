import sys
import os
import csv
import logging

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
        'Возраст': 'age',
        'ФШР id': 'fsr_id',
        'ФИДЕ id': 'fide_id',
        'Город, район': 'city_district',
        'Lichess': 'lichess',
        'Stepchess': 'stepchess',
        'Рапид рейтинг': 'rapid_rating',
        'Группа. Утро': 'group_morning',
        'Группа. Вечер': 'group_evening'
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
                    if val:
                        # Обработка числовых полей
                        if eng_key == 'rapid_rating':
                            raw_val = val.strip()
                            if '?' in raw_val:
                                student_data['is_provisional'] = True
                                raw_val = raw_val.replace('?', '')
                            try:
                                student_data[eng_key] = int(raw_val)
                            except (ValueError, TypeError):
                                student_data[eng_key] = None
                        elif eng_key == 'age':
                            # Возраст мы все равно пересчитаем
                            try:
                                student_data[eng_key] = val
                            except:
                                student_data[eng_key] = None
                        else:
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
