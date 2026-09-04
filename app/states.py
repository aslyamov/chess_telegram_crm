from aiogram.fsm.state import State, StatesGroup

class StudentForm(StatesGroup):
    fio = State()
    birth_date = State()
    lichess = State()
    stepchess = State()
    fide_id = State()
    fsr_id = State()

class SearchStudent(StatesGroup):
    query = State()

class EditStudent(StatesGroup):
    field_to_edit = State()
    new_value = State()
