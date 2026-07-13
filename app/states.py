from aiogram.fsm.state import State, StatesGroup

class StudentForm(StatesGroup):
    fio = State()
    birth_date = State()
    age = State()
    fsr_id = State()
    fide_id = State()
    city_district = State()
    lichess = State()
    stepchess = State()
    rapid_rating = State()
    group_morning = State()
    group_evening = State()

class SearchStudent(StatesGroup):
    query = State()

class EditStudent(StatesGroup):
    field_to_edit = State()
    new_value = State()
