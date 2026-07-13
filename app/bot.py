import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F, Router, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import Message, CallbackQuery, LinkPreviewOptions, TelegramObject
from typing import Any, Awaitable, Callable, Dict, List, Optional
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.formatting import Text, Bold, Italic, TextLink, Code, as_list

from datetime import datetime
from .config import settings
from .database import (
    add_student, get_students, delete_student, search_students_by_name, 
    get_student_by_id, update_student, get_lichess_rating, get_fsr_ratings, 
    get_fide_ratings, update_students_batch, close_session, get_lichess_ratings_batch,
    db
)
from .models import Student, LICHESS_VARIANTS, LICHESS_LABELS
from .states import StudentForm, SearchStudent, EditStudent
from .utils import format_points
from .lichess_utils import (
    generate_monthly_report, 
    generate_activity_report, 
    generate_rapid_leaderboard,
    generate_blitz_leaderboard,
    generate_bullet_leaderboard,
    generate_ultraBullet_leaderboard,
    generate_classical_leaderboard,
    generate_correspondence_leaderboard,
    generate_crazyhouse_leaderboard,
    generate_chess960_leaderboard,
    generate_kingOfTheHill_leaderboard,
    generate_threeCheck_leaderboard,
    generate_antichess_leaderboard,
    generate_atomic_leaderboard,
    generate_horde_leaderboard,
    generate_racingKings_leaderboard,
    generate_puzzle_leaderboard,
    generate_tactical_leaderboard,
    generate_fide_fsr_leaderboard,
    generate_student_annual_report,
    generate_rank_leaderboard
)

router = Router()

# Middleware для проверки админа
class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
            
        user = event.from_user
        if not user or user.id != settings.admin_telegram_id:
            await event.answer("Доступ запрещен.")
            return
        return await handler(event, data)

RANKS = [
    "КМС",
    "1-й спортивный разряд",
    "2-й спортивный разряд",
    "3-й спортивный разряд",
    "1-й юношеский разряд",
    "2-й юношеский разряд",
    "3-й юношеский разряд"
]

# Поля для редактирования (названия для кнопок)
EDIT_FIELDS = {
    "ФИО": "fio",
    "ДР": "birth_date",
    "Разряд": "rank",
    "ФШР ID": "fsr_id",
    "ФИДЕ ID": "fide_id",
    "Город": "city",
    "Lichess": "lichess",
    "Stepchess": "stepchess"
}

def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👥 Список учеников")
    builder.button(text="➕ Добавить ученика")
    builder.button(text="🔍 Поиск")
    builder.button(text="🔄 Обновить всех")
    builder.button(text="📊 Турниры месяца")
    builder.button(text="🏆 Годовой турнир")
    builder.button(text="📈 Активность")
    builder.button(text="🏆 Рейтинги")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_rating_platform_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🐴 Lichess", callback_data="lbmenu_lichess")
    builder.button(text="🌍 ФИДЕ", callback_data="lbmenu_fide")
    builder.button(text="🇷🇺 ФШР", callback_data="lbmenu_fsr")
    builder.button(text="🏅 По разрядам", callback_data="lbmenu_ranks")
    builder.adjust(1)
    return builder.as_markup()

# --- LEADERBOARD ---
@router.message(F.text == "🏆 Рейтинги")
async def show_leaderboard_menu(message: Message):
    await message.answer("Выберите платформу для просмотра рейтингов:", reply_markup=get_rating_platform_keyboard())

@router.callback_query(F.data.startswith("lbmenu_"))
async def process_lbmenu_choice(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    menu_type = callback.data.split("_")[1]
    
    builder = InlineKeyboardBuilder()
    if menu_type == "lichess":
        builder.button(text="📊 Рапид", callback_data="lb_lic_rapid")
        builder.button(text="⚡️ Блиц", callback_data="lb_lic_blitz")
        builder.button(text="☄️ Пуля", callback_data="lb_lic_bullet")
        builder.button(text="🚀 Ultra", callback_data="lb_lic_ultraBullet")
        builder.button(text="🐢 Классика", callback_data="lb_lic_classical")
        builder.button(text="📬 Переписка", callback_data="lb_lic_correspondence")
        builder.button(text="🤡 Crazy", callback_data="lb_lic_crazyhouse")
        builder.button(text="🎲 960", callback_data="lb_lic_chess960")
        builder.button(text="👑 KOTH", callback_data="lb_lic_kingOfTheHill")
        builder.button(text="🏁 Racing", callback_data="lb_lic_racingKings")
        builder.button(text="🏹 Horde", callback_data="lb_lic_horde")
        builder.button(text="☢️ Atomic", callback_data="lb_lic_atomic")
        builder.button(text="📉 Anti", callback_data="lb_lic_antichess")
        builder.button(text="➕ 3Check", callback_data="lb_lic_threeCheck")
        builder.button(text="🧩 Задачи", callback_data="lb_lic_puzzle")
        builder.button(text="⚡️ Storm", callback_data="lb_lic_storm")
        builder.button(text="🏎 Racer", callback_data="lb_lic_racer")
        builder.button(text="🔥 Streak", callback_data="lb_lic_streak")
        builder.button(text="⬅️ Назад", callback_data="lbmenu_back")
        builder.adjust(3, 3, 4, 4, 4, 1)
        await callback.message.edit_text("Выберите тип рейтинга Lichess:", reply_markup=builder.as_markup())
        
    elif menu_type == "fide":
        builder.button(text="🐢 Классика", callback_data="lb_fide_classical")
        builder.button(text="📊 Рапид", callback_data="lb_fide_rapid")
        builder.button(text="⚡️ Блиц", callback_data="lb_fide_blitz")
        builder.button(text="⬅️ Назад", callback_data="lbmenu_back")
        builder.adjust(3, 1)
        await callback.message.edit_text("Выберите дисциплину ФИДЕ:", reply_markup=builder.as_markup())
        
    elif menu_type == "fsr":
        builder.button(text="🐢 Классика", callback_data="lb_fsr_classical")
        builder.button(text="📊 Рапид", callback_data="lb_fsr_rapid")
        builder.button(text="⚡️ Блиц", callback_data="lb_fsr_blitz")
        builder.button(text="⬅️ Назад", callback_data="lbmenu_back")
        builder.adjust(3, 1)
        await callback.message.edit_text("Выберите дисциплину ФШР:", reply_markup=builder.as_markup())
        
    elif menu_type == "ranks":
        for r in RANKS:
            builder.button(text=r, callback_data=f"lbrank_{r}")
        builder.button(text="Без разряда", callback_data="lbrank_none")
        builder.button(text="⬅️ Назад", callback_data="lbmenu_back")
        builder.adjust(1)
        await callback.message.edit_text("Выберите разряд:", reply_markup=builder.as_markup())

    elif menu_type == "back":
        await callback.message.edit_text("Выберите платформу для просмотра рейтингов:", reply_markup=get_rating_platform_keyboard())
        
    await callback.answer()

@router.callback_query(F.data.startswith("lbrank_"))
async def process_rank_leaderboard_choice(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    rank_val = callback.data.split("_", 1)[1]
    if rank_val == "none":
        rank_val = None
        
    students = await get_students()
    report = generate_rank_leaderboard(students, rank_val)
    
    await callback.message.answer(report, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("lb_"))
async def process_leaderboard_choice(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    parts = callback.data.split("_")
    if len(parts) == 3:
        platform = parts[1]
        lb_type = parts[2]
    elif len(parts) == 2:
        platform = "lic"
        lb_type = parts[1]
    else:
        await callback.answer("Неверный формат данных")
        return
        
    students = await get_students()
    
    if platform == "lic":
        lb_functions = {
            "rapid": generate_rapid_leaderboard, "blitz": generate_blitz_leaderboard,
            "bullet": generate_bullet_leaderboard, "ultraBullet": generate_ultraBullet_leaderboard,
            "classical": generate_classical_leaderboard, "correspondence": generate_correspondence_leaderboard,
            "crazyhouse": generate_crazyhouse_leaderboard, "chess960": generate_chess960_leaderboard,
            "kingOfTheHill": generate_kingOfTheHill_leaderboard, "threeCheck": generate_threeCheck_leaderboard,
            "antichess": generate_antichess_leaderboard, "atomic": generate_atomic_leaderboard,
            "horde": generate_horde_leaderboard, "racingKings": generate_racingKings_leaderboard,
            "puzzle": generate_puzzle_leaderboard
        }
        
        if lb_type in lb_functions:
            report = lb_functions[lb_type](students)
        elif lb_type == "storm":
            report = generate_tactical_leaderboard(students, "storm_score", "Puzzle Storm", "⚡️")
        elif lb_type == "racer":
            report = generate_tactical_leaderboard(students, "racer_score", "Puzzle Racer", "🏎")
        elif lb_type == "streak":
            report = generate_tactical_leaderboard(students, "streak_score", "Puzzle Streak", "🔥")
        else:
            await callback.answer("Тип не поддерживается")
            return
            
    elif platform == "fide":
        titles = {"classical": "ФИДЕ Классические", "rapid": "ФИДЕ Рапид", "blitz": "ФИДЕ Блиц"}
        field = f"fide_{lb_type}_rating"
        report = generate_fide_fsr_leaderboard(students, field, titles.get(lb_type, "ФИДЕ"))
        
    elif platform == "fsr":
        titles = {"classical": "ФШР Классические", "rapid": "ФШР Быстрые", "blitz": "ФШР Блиц"}
        field = f"fsr_{lb_type}_rating"
        report = generate_fide_fsr_leaderboard(students, field, titles.get(lb_type, "ФШР"))
        
    else:
        await callback.answer("Платформа не поддерживается")
        return

    await callback.message.answer(report, parse_mode="HTML")
    await callback.answer()

# --- SYNC ALL (OPTIMIZED) ---
async def update_single_student_data(student: Student, semaphore: asyncio.Semaphore, lichess_data: Optional[dict] = None) -> Optional[tuple]:
    """Helper to update data for one student with rate limiting."""
    try:
        async with semaphore:
            lichess_res = lichess_data
            if not lichess_res and student.lichess:
                lichess_task = get_lichess_rating(student.lichess)
            else:
                lichess_task = asyncio.sleep(0, result=None)
                
            fsr_task = get_fsr_ratings(student.fsr_id) if student.fsr_id else asyncio.sleep(0, result=None)
            fide_task = get_fide_ratings(student.fide_id) if student.fide_id else asyncio.sleep(0, result=None)
            
            lichess_fetched, fsr_res, fide_res = await asyncio.gather(lichess_task, fsr_task, fide_task)
            if lichess_fetched:
                lichess_res = lichess_fetched
            
            updates = {}
            # 1. Lichess
            if lichess_res:
                for pt in LICHESS_VARIANTS:
                    updates[f"{pt}_rating"] = lichess_res.get(f"{pt}_rating")
                    updates[f"is_{pt}_provisional"] = lichess_res.get(f"is_{pt}_provisional", False)
                updates["storm_score"] = lichess_res.get("storm_score")
                updates["racer_score"] = lichess_res.get("racer_score")
                updates["streak_score"] = lichess_res.get("streak_score")
            
            # 2. FSR
            if fsr_res:
                updates["fsr_classical_rating"] = fsr_res.get("classical")
                updates["fsr_rapid_rating"] = fsr_res.get("rapid")
                updates["fsr_blitz_rating"] = fsr_res.get("blitz")
                
            # 3. FIDE
            if fide_res:
                updates["fide_classical_rating"] = fide_res.get("classical")
                updates["fide_rapid_rating"] = fide_res.get("rapid")
                updates["fide_blitz_rating"] = fide_res.get("blitz")

            if not updates and not student.birth_date:
                return None
                
            # Update model for calculation
            for k, v in updates.items(): setattr(student, k, v)
            student.update_calculated_fields()
            
            # Merge calculated fields into updates
            updates.update({
                "age": student.age,
                "group_morning": student.group_morning,
                "group_evening": student.group_evening
            })
            return (student.id, updates)
    except Exception as e:
        logging.error(f"Error updating single student data for {student.fio} (ID: {student.id}): {e}")
        return None

async def perform_students_sync(students: List[Student], status_msg: Message):
    # 1. Пакетный сбор данных Lichess в один запрос
    lichess_usernames = [s.lichess for s in students if s.lichess]
    batch_lichess_ratings = {}
    if lichess_usernames:
        try:
            batch_lichess_ratings = await get_lichess_ratings_batch(lichess_usernames)
        except Exception as e:
            logging.error(f"Error fetching batch Lichess ratings: {e}")
            
    # Семафор для ограничения одновременных запросов к FIDE/FSR (чтобы не забанили)
    semaphore = asyncio.Semaphore(10)
    tasks = []
    for s in students:
        s_lichess_data = batch_lichess_ratings.get(s.lichess.lower()) if s.lichess else None
        tasks.append(update_single_student_data(s, semaphore, lichess_data=s_lichess_data))
        
    results = await asyncio.gather(*tasks)
    
    # Фильтруем успешные обновления и применяем пакетно
    batch_updates = []
    failed_students = []
    failed_ids = []
    for s, r in zip(students, results):
        if r is not None:
            batch_updates.append(r)
        else:
            failed_students.append(s.fio)
            failed_ids.append(s.id)
            
    if batch_updates:
        await update_students_batch(batch_updates)

    # 2. Обновление результатов годового турнира (за текущий и прошлый месяцы)
    try:
        from .lichess_utils import sync_annual_tournament_results
        successful_students = [s for s, r in zip(students, results) if r is not None]
        if successful_students:
            annual_updates = await sync_annual_tournament_results(settings.lichess_team_id, successful_students, full_rebuild=False)
            if annual_updates:
                await update_students_batch(annual_updates)
    except Exception as e:
        logging.error(f"Error syncing annual tournament in perform_students_sync: {e}")

    # Сохраняем сбойные ID в Firestore
    try:
        if failed_ids:
            await db.collection("metadata").document("failed_sync_ids").set({
                "ids": failed_ids,
                "updated_at": datetime.utcnow().isoformat()
            })
        else:
            try:
                await db.collection("metadata").document("failed_sync_ids").delete()
            except Exception:
                pass
    except Exception as e:
        logging.error(f"Error saving failed_sync_ids to Firestore: {e}")

    status_text = (
        f"✅ Обновление завершено!\n\n"
        f"📊 Успешно обновлено: {len(students) - len(failed_students)} из {len(students)}\n"
    )
    
    builder = InlineKeyboardBuilder()
    if failed_students:
        status_text += f"\n⚠️ Не удалось обновить ({len(failed_students)}):"
        for name in failed_students:
            status_text += f"\n• {name}"
        builder.button(text="🔄 Повторить", callback_data="retry_failed_sync")
        
    try:
        await status_msg.edit_text(status_text, reply_markup=builder.as_markup())
    except Exception:
        await status_msg.answer(status_text, reply_markup=builder.as_markup())

@router.message(F.text == "🔄 Обновить всех")
async def sync_all_students(message: Message):
    students = await get_students()
    if not students:
        await message.answer("Список учеников пуст.")
        return
    
    status_msg = await message.answer(f"⏳ Начинаю параллельное обновление {len(students)} учеников...")
    await perform_students_sync(students, status_msg)

@router.callback_query(F.data == "retry_failed_sync")
async def retry_failed_sync_handler(callback: CallbackQuery):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await callback.answer("🔄 Запуск повторного обновления...")
    
    # Загружаем ID сбойных учеников
    failed_ids = []
    try:
        doc = await db.collection("metadata").document("failed_sync_ids").get()
        if doc.exists:
            failed_ids = doc.to_dict().get("ids", [])
    except Exception as e:
        logging.error(f"Error reading failed_sync_ids from Firestore: {e}")
        
    if not failed_ids:
        await callback.message.edit_text("✅ Все ученики уже успешно обновлены!")
        return
        
    students = []
    for s_id in failed_ids:
        s = await get_student_by_id(s_id)
        if s:
            students.append(s)
            
    if not students:
        await callback.message.edit_text("✅ Ученики для повторного обновления не найдены в БД.")
        return
        
    # Редактируем сообщение для отображения прогресса
    await callback.message.edit_text(f"⏳ Повторное обновление {len(students)} учеников...")
    await perform_students_sync(students, callback.message)

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать в CRM шахматной школы!", reply_markup=get_main_keyboard())

def format_student_info(s: Student):
    fsr_id_display = TextLink(str(s.fsr_id), url=f"https://ratings.ruchess.ru/people/{s.fsr_id}") if s.fsr_id else "—"
    fide_id_display = TextLink(str(s.fide_id), url=f"https://ratings.fide.com/profile/{s.fide_id}") if s.fide_id else "—"
    lichess_display = TextLink(str(s.lichess), url=f"https://lichess.org/@/{s.lichess}") if s.lichess else "—"
    stepchess_display = TextLink(str(s.stepchess), url=f"https://stepchess.ru/users/{s.stepchess}") if s.stepchess else "—"
    
    info_items = [
        Text("👤 ", Bold(s.fio)),
        Text(f"🎂 ДР: {s.birth_date or '—'} | Возраст: {s.age or '—'}"),
        Text(f"🏅 Разряд: {s.rank or '—'}"),
        Text("🆔 ФШР: ", fsr_id_display, " | ФИДЕ: ", fide_id_display),
        Text(f"🏙 Город: {s.city or '—'}"),
        Text("🐴 Lichess: ", lichess_display, " | 🧩 Stepchess: ", stepchess_display),
        "",
        Bold("🏆 Рейтинги Lichess:")
    ]

    # Группируем рейтинги для компактности
    ratings_line = []
    for pt, label in LICHESS_LABELS.items():
        rating = getattr(s, f"{pt}_rating")
        if rating:
            is_prov = getattr(s, f"is_{pt}_provisional")
            ratings_line.append(Text(f"{label}: ", Code(f"{rating}{'?' if is_prov else ''}")))
    
    if ratings_line:
        info_items.extend(ratings_line)
    else:
        info_items.append(Italic("Нет данных"))

    info_items.append("")
    info_items.append(Text("⚡️ Storm: ", str(s.storm_score or '—'), " | 🏎 Racer: ", str(s.racer_score or '—'), " | 🔥 Streak: ", str(s.streak_score or '—')))
    
    fsr_ratings = []
    if s.fsr_classical_rating: fsr_ratings.append(Text("Кл: ", Code(str(s.fsr_classical_rating))))
    if s.fsr_rapid_rating: fsr_ratings.append(Text("Рп: ", Code(str(s.fsr_rapid_rating))))
    if s.fsr_blitz_rating: fsr_ratings.append(Text("Бл: ", Code(str(s.fsr_blitz_rating))))
    if fsr_ratings:
        fsr_display = fsr_ratings[0]
        for r in fsr_ratings[1:]:
            fsr_display = Text(fsr_display, ", ", r)
    else:
        fsr_display = "—"

    fide_ratings = []
    if s.fide_classical_rating: fide_ratings.append(Text("Кл: ", Code(str(s.fide_classical_rating))))
    if s.fide_rapid_rating: fide_ratings.append(Text("Рп: ", Code(str(s.fide_rapid_rating))))
    if s.fide_blitz_rating: fide_ratings.append(Text("Бл: ", Code(str(s.fide_blitz_rating))))
    if fide_ratings:
        fide_display = fide_ratings[0]
        for r in fide_ratings[1:]:
            fide_display = Text(fide_display, ", ", r)
    else:
        fide_display = "—"
    
    info_items.extend([
        Text("🇷🇺 ФШР (", fsr_id_display, "): ", fsr_display),
        Text("🌍 ФИДЕ (", fide_id_display, "): ", fide_display),
        Text(f"🏫 Группы: Утро {s.group_morning or '—'} | Вечер {s.group_evening or '—'}")
    ])
    
    if s.lichess:
        from .lichess_utils import calculate_student_annual_metrics
        info_items.append("")
        info_items.append(Bold("🏆 Годовой турнир (Янв - Ноя):"))
        
        # Morning league
        m_metrics = calculate_student_annual_metrics(s, "morning")
        m_pts = m_metrics["points_sum"]
        m_target = m_metrics["target"]
        m_rem = m_metrics["remaining"]
        m_tour = m_metrics["tournament_name"]
        
        # Show morning info if student has morning group or played in morning
        if m_pts > 0 or (s.group_morning and s.group_morning not in ["Нет данных", "—"]):
            status_m = "Выполнено! 🎉" if m_rem == 0 else f"осталось {format_points(m_rem)} очк. (ср. {format_points(m_metrics['avg_needed_remaining'])}/турнир)"
            info_items.append(Text(f" 🌅 Утро: {format_points(m_pts)} из {m_target:.0f} в {m_tour} ({status_m})"))
            
        # Evening league
        e_metrics = calculate_student_annual_metrics(s, "evening")
        e_pts = e_metrics["points_sum"]
        e_target = e_metrics["target"]
        e_rem = e_metrics["remaining"]
        
        # Show evening info if student has evening group or played in evening
        if e_pts > 0 or (s.group_evening and s.group_evening not in ["Нет данных", "—"]):
            status_e = "Выполнено! 🎉" if e_rem == 0 else f"осталось {format_points(e_rem)} очк. (ср. {format_points(e_metrics['avg_needed_remaining'])}/турнир)"
            info_items.append(Text(f" ⚡️ Вечер: {format_points(e_pts)} из {e_target:.0f} ({status_e})"))
            
    return as_list(*info_items).as_html()

def get_student_inline_kb(student_id: str, has_activity: bool = False, page: int = 0, has_lichess: bool = False):
    builder = InlineKeyboardBuilder()
    
    if has_activity:
        builder.button(text="📈  Активность", callback_data=f"askstact_{student_id}_{page}")
        if has_lichess:
            builder.button(text="🏆 Годовой турнир", callback_data=f"stannual_{student_id}_{page}")
            builder.button(text="🔄 Обновить Lichess", callback_data=f"sync_{student_id}_{page}")
            
    builder.button(text="📝 Изменить", callback_data=f"edit_{student_id}_{page}")
    builder.button(text="🗑 Удалить", callback_data=f"del_{student_id}_{page}")
    builder.button(text="⬅️ К списку", callback_data=f"list_{page}")
    
    builder.adjust(2)
    return builder.as_markup()


def get_pagination_keyboard(students: List[Student], page: int = 0, page_size: int = 10):
    builder = InlineKeyboardBuilder()
    start_idx, end_idx = page * page_size, (page + 1) * page_size
    for s in students[start_idx:end_idx]:
        builder.button(text=f"👤 {s.fio}", callback_data=f"view_{s.id}_{page}")
    builder.adjust(1)
    
    nav = []
    nav.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"list_{page-1}" if page > 0 else "noop"))
    nav.append(types.InlineKeyboardButton(text=f"{page+1}/{(len(students)-1)//page_size + 1}", callback_data="noop"))
    nav.append(types.InlineKeyboardButton(text="➡️", callback_data=f"list_{page+1}" if end_idx < len(students) else "noop"))
    builder.row(*nav)
    return builder.as_markup()

# --- HANDLERS (LIST, VIEW, DELETE) ---
@router.message(F.text == "👥 Список учеников")
async def list_students(message: Message):
    students = sorted(await get_students(), key=lambda x: x.fio)
    if not students:
        await message.answer("Список учеников пуст.")
        return
    await message.answer(f"👥 Всего учеников: {len(students)}\nВыберите ученика:", 
                         reply_markup=get_pagination_keyboard(students, 0))

@router.callback_query(F.data.startswith("list_"))
async def process_list_page(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    page = int(callback.data.split("_")[1])
    students = sorted(await get_students(), key=lambda x: x.fio)
    try:
        await callback.message.edit_text(f"👥 Всего учеников: {len(students)}\nВыберите ученика:", 
                                         reply_markup=get_pagination_keyboard(students, page))
    except Exception: pass
    await callback.answer()

@router.callback_query(F.data.startswith("view_"))
async def view_student(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    student = await get_student_by_id(student_id)
    if not student:
        await callback.answer("Ученик не найден")
        return
    await callback.message.edit_text(format_student_info(student), 
                                     reply_markup=get_student_inline_kb(student.id or "", bool(student.lichess or student.stepchess), int(page), bool(student.lichess)),
                                     parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
    await callback.answer()

# --- INDIVIDUAL ACTIVITY ---
@router.callback_query(F.data.startswith("askstact_"))
async def ask_student_activity_period(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    builder.button(text="🕒 За сегодня", callback_data=f"stact_{student_id}_1_{page}")
    builder.button(text="📅 За неделю", callback_data=f"stact_{student_id}_7_{page}")
    builder.button(text="⬅️ Назад", callback_data=f"view_{student_id}_{page}")
    builder.adjust(2, 1)
    await callback.message.edit_text("Выберите период для отчета по ученику:", 
                                     reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("stact_"))
async def show_student_activity_report(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, days, page = callback.data.split("_")
    days = int(days)
    await callback.answer("⏳ Собираю данные...")
    
    student = await get_student_by_id(student_id)
    if not student:
        await callback.message.answer("Ученик не найден")
        return

    try:
        report = await generate_activity_report([student], days)
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ К профилю", callback_data=f"view_{student_id}_{page}")
        await callback.message.answer(report, parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception as e:
        logging.error(f"Error student activity report: {e}")
        await callback.message.answer("❌ Ошибка при получении данных.")

@router.callback_query(F.data.startswith("stannual_"))
async def show_student_annual_report_handler(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    await callback.answer("⏳ Загрузка результатов...")
    
    student = await get_student_by_id(student_id)
    if not student:
        await callback.message.answer("Ученик не найден")
        return
        
    try:
        report = await generate_student_annual_report(student)
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ К профилю", callback_data=f"view_{student_id}_{page}")
        await callback.message.edit_text(report, parse_mode="HTML", reply_markup=builder.as_markup(), link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:
        logging.error(f"Error student annual report: {e}")
        await callback.message.answer("❌ Ошибка при получении данных.")

@router.callback_query(F.data.startswith("del_"))
async def ask_delete_confirmation(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    student = await get_student_by_id(student_id)
    if not student: return
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_del_{student_id}_{page}")
    builder.button(text="❌ Нет, отмена", callback_data=f"view_{student_id}_{page}")
    content = Text("⚠️ Удалить ", Bold(student.fio), "?")
    await callback.message.edit_text(content.as_html(), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_del_"))
async def process_confirm_delete(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, _, student_id, page = callback.data.split("_")
    await delete_student(student_id)
    await callback.answer("Ученик удален")
    await list_students(callback.message)

# --- SYNC INDIVIDUAL ---
@router.callback_query(F.data.startswith("sync_"))
async def sync_individual(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    student = await get_student_by_id(student_id)
    if not student: return
    await callback.answer("Обновляю...")
    
    semaphore = asyncio.Semaphore(1)
    res = await update_single_student_data(student, semaphore)
    if res:
        await update_student(student_id, res[1])
        # Also sync annual tournament results (current/prev month)
        try:
            from .lichess_utils import sync_annual_tournament_results
            annual_updates = await sync_annual_tournament_results(settings.lichess_team_id, [student], full_rebuild=False)
            if annual_updates:
                await update_student(student_id, annual_updates[0][1])
                # Reload student model to format correct info
                student = await get_student_by_id(student_id)
        except Exception as e:
            logging.error(f"Error syncing individual annual tournament: {e}")
            
        try:
            await callback.message.edit_text(format_student_info(student), 
                                             reply_markup=get_student_inline_kb(student_id, True, int(page), bool(student.lichess)),
                                             parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramBadRequest as e:
            if "message is not modified" not in e.message:
                raise
    await callback.message.answer(Text("✅ Данные ", Bold(student.fio), " обновлены!").as_html(), parse_mode="HTML")

# --- EDIT STUDENT ---
@router.callback_query(F.data.startswith("edit_"))
async def start_edit_student(callback: CallbackQuery, state: FSMContext):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    _, student_id, page = callback.data.split("_")
    await state.update_data(edit_student_id=student_id, edit_page=page)
    builder = InlineKeyboardBuilder()
    for label, field in EDIT_FIELDS.items():
        builder.button(text=label, callback_data=f"field_{field}")
    builder.adjust(3)
    await callback.message.answer("Что изменить?", reply_markup=builder.as_markup())
    await state.set_state(EditStudent.field_to_edit)
    await callback.answer()

@router.callback_query(EditStudent.field_to_edit, F.data.startswith("field_"))
async def process_field_choice(callback: CallbackQuery, state: FSMContext):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    field_name = callback.data.split("_", 1)[1]
    display_name = next((k for k, v in EDIT_FIELDS.items() if v == field_name), field_name)
    await state.update_data(field_to_update=field_name)
    
    if field_name == "rank":
        builder = InlineKeyboardBuilder()
        for r in RANKS:
            builder.button(text=r, callback_data=f"setrank_{r}")
        builder.button(text="❌ Без разряда", callback_data="setrank_none")
        builder.adjust(1)
        await callback.message.answer("Выберите разряд:", reply_markup=builder.as_markup())
    else:
        await callback.message.answer(f"Введите новое значение для '{display_name}':")
        await state.set_state(EditStudent.new_value)
    await callback.answer()

@router.callback_query(EditStudent.field_to_edit, F.data.startswith("setrank_"))
async def process_setrank_choice(callback: CallbackQuery, state: FSMContext):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    rank_val = callback.data.split("_", 1)[1]
    if rank_val == "none":
        rank_val = None
        
    user_data = await state.get_data()
    student_id = user_data['edit_student_id']
    
    student = await get_student_by_id(student_id)
    if not student:
        await callback.answer("Ученик не найден")
        return
        
    await update_student(student_id, {"rank": rank_val})
    
    updated_student = await get_student_by_id(student_id)
    if updated_student:
        updated_student.update_calculated_fields()
        await update_student(student_id, {
            "age": updated_student.age,
            "group_morning": updated_student.group_morning,
            "group_evening": updated_student.group_evening
        })
        
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 К профилю", callback_data=f"view_{student_id}_0")
    await callback.message.answer("✅ Разряд сохранен!", reply_markup=get_main_keyboard())
    
    content = Text("Данные ", Bold(updated_student.fio), " обновлены.")
    await callback.message.answer(content.as_html(), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.message(EditStudent.new_value)
async def process_new_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    student_id, field_to_update = user_data['edit_student_id'], user_data['field_to_update']
    new_val = message.text.strip()
    
    student = await get_student_by_id(student_id)
    if not student: return

    update_data = {}
    rating_fields = [f"{pt}_rating" for pt in LICHESS_VARIANTS] + [
        'fsr_classical_rating', 'fsr_rapid_rating', 'fsr_blitz_rating',
        'fide_classical_rating', 'fide_rapid_rating', 'fide_blitz_rating',
        'fsr_rating', 'fide_rating'
    ]
    
    if field_to_update in rating_fields:
        is_prov = False
        if '?' in new_val:
            is_prov, new_val = True, new_val.replace('?', '')
        
        if new_val.isdigit():
            update_data[field_to_update] = int(new_val)
            if field_to_update.endswith("_rating") and not (field_to_update.startswith("fsr_") or field_to_update.startswith("fide_")):
                update_data[f"is_{field_to_update.replace('_rating', '')}_provisional"] = is_prov
        elif new_val.lower() in ['-', 'none', '—', 'пропуск']:
            update_data[field_to_update] = None
        else:
            await message.answer("Введите число или '-'")
            return
    else:
        val = None if new_val.lower() == 'пропуск' else new_val
        update_data[field_to_update] = val
        if field_to_update == 'lichess' and val:
            res = await get_lichess_rating(val)
            if res: update_data.update(res)
        elif field_to_update == 'fsr_id' and val:
            res = await get_fsr_ratings(val)
            if res:
                update_data['fsr_classical_rating'] = res.get('classical')
                update_data['fsr_rapid_rating'] = res.get('rapid')
                update_data['fsr_blitz_rating'] = res.get('blitz')
        elif field_to_update == 'fide_id' and val:
            res = await get_fide_ratings(val)
            if res:
                update_data['fide_classical_rating'] = res.get('classical')
                update_data['fide_rapid_rating'] = res.get('rapid')
                update_data['fide_blitz_rating'] = res.get('blitz')

    await update_student(student_id, update_data)
    # Recalculate
    updated_student = await get_student_by_id(student_id)
    if updated_student:
        updated_student.update_calculated_fields()
        await update_student(student_id, {"age": updated_student.age, "group_morning": updated_student.group_morning, "group_evening": updated_student.group_evening})
        
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 К профилю", callback_data=f"view_{student_id}_0")
    await message.answer("✅ Сохранено!", reply_markup=get_main_keyboard())
    content = Text("Данные ", Bold(updated_student.fio), " обновлены.")
    await message.answer(content.as_html(), reply_markup=builder.as_markup(), parse_mode="HTML")

# --- ADD STUDENT & OTHERS ---
@router.message(F.text == "➕ Добавить ученика")
async def start_add_student(message: Message, state: FSMContext):
    await state.set_state(StudentForm.fio)
    await message.answer("Введите ФИО:", reply_markup=types.ReplyKeyboardRemove())

@router.message(StudentForm.fio)
async def process_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await state.set_state(StudentForm.birth_date)
    builder = ReplyKeyboardBuilder()
    builder.button(text="Пропустить")
    await message.answer("Дата рождения (ДД.ММ.ГГГГ):", reply_markup=builder.as_markup(resize_keyboard=True))

@router.message(StudentForm.birth_date)
async def process_birth_date(message: Message, state: FSMContext):
    await state.update_data(birth_date=message.text if message.text.lower() != 'пропустить' else None)
    await state.set_state(StudentForm.lichess)
    await message.answer("Ник Lichess (или 'пропустить'):")

@router.message(StudentForm.lichess)
async def process_lichess(message: Message, state: FSMContext):
    await state.update_data(lichess=message.text if message.text.lower() != 'пропустить' else None)
    await state.set_state(StudentForm.stepchess)
    await message.answer("Ник/ID Stepchess (или 'пропустить'):")

@router.message(StudentForm.stepchess)
async def process_stepchess(message: Message, state: FSMContext):
    await state.update_data(stepchess=message.text if message.text.lower() != 'пропустить' else None)
    await state.set_state(StudentForm.fide_id)
    await message.answer("FIDE ID (или 'пропустить'):")

@router.message(StudentForm.fide_id)
async def process_fide_id(message: Message, state: FSMContext):
    await state.update_data(fide_id=message.text if message.text.lower() != 'пропустить' else None)
    await state.set_state(StudentForm.fsr_id)
    await message.answer("ФШР ID (или 'пропустить'):")

@router.message(StudentForm.fsr_id)
async def process_fsr_id(message: Message, state: FSMContext):
    fsr_data = message.text if message.text.lower() != 'пропустить' else None
    user_data = await state.get_data()
    student = Student(fio=user_data['fio'], birth_date=user_data.get('birth_date'), lichess=user_data.get('lichess'),
                      stepchess=user_data.get('stepchess'), fide_id=user_data.get('fide_id'), fsr_id=fsr_data)
    
    # Сразу собираем рейтинги для нового ученика
    semaphore = asyncio.Semaphore(1)
    await update_single_student_data(student, semaphore)
    
    student_id = await add_student(student)
    student.id = student_id
    
    # Сразу подтягиваем годовую историю турниров Lichess за этот год
    if student.lichess:
        try:
            from .lichess_utils import sync_annual_tournament_results
            annual_updates = await sync_annual_tournament_results(settings.lichess_team_id, [student], full_rebuild=True)
            if annual_updates:
                await update_student(student_id, annual_updates[0][1])
        except Exception as e:
            logging.error(f"Error syncing annual tournament for new student: {e}")
            
    await state.clear()
    await message.answer(f"Ученик {student.fio} добавлен!", reply_markup=get_main_keyboard())

@router.message(F.text == "🔍 Поиск")
async def start_search(message: Message, state: FSMContext):
    await state.set_state(SearchStudent.query)
    await message.answer("Введите часть ФИО:")

@router.message(SearchStudent.query)
async def process_search(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Введите часть ФИО для поиска.")
        return
    results = await search_students_by_name(message.text)
    await state.clear()
    if not results:
        await message.answer("Ничего не найдено.", reply_markup=get_main_keyboard())
        return
    for s in results:
        await message.answer(format_student_info(s), reply_markup=get_student_inline_kb(s.id or "", bool(s.lichess or s.stepchess), 0, bool(s.lichess)), parse_mode="HTML")
    await message.answer("Поиск завершен.", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "noop")
async def process_noop(callback: CallbackQuery): await callback.answer()

# --- ACTIVITY & MONTHLY HANDLERS REMAIN SIMILAR ---
@router.message(F.text == "📈 Активность")
async def ask_activity_period(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🕒 За сегодня", callback_data="act_1")
    builder.button(text="📅 За неделю", callback_data="act_7")
    await message.answer("За какой период?", reply_markup=builder.as_markup())

async def send_long_message(message: Message, text: str, parse_mode: str = "HTML"):
    """
    Отправляет длинное сообщение в Telegram, разбивая его на части <= 4000 символов.
    Разбивка идет по строкам (\n), чтобы не разрывать HTML-теги форматирования.
    """
    if len(text) <= 4000:
        await message.answer(text, parse_mode=parse_mode)
        return

    lines = text.split("\n")
    current_chunk = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > 4000:
            if current_chunk:
                await message.answer("\n".join(current_chunk), parse_mode=parse_mode)
                current_chunk = []
                current_length = 0
            
            if len(line) > 4000:
                for i in range(0, len(line), 4000):
                    await message.answer(line[i:i+4000], parse_mode=parse_mode)
                continue
                
        current_chunk.append(line)
        current_length += len(line) + 1

    if current_chunk:
        await message.answer("\n".join(current_chunk), parse_mode=parse_mode)

@router.callback_query(F.data.startswith("act_"))
async def show_activity_report_handler(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    days = int(callback.data.split("_")[1])
    await callback.answer("⏳ Собираю...")
    report = await generate_activity_report(await get_students(), days)
    await send_long_message(callback.message, report, parse_mode="HTML")

@router.message(F.text == "📊 Турниры месяца")
async def show_monthly_report_handler(message: Message):
    status_msg = await message.answer("⏳ Собираю данные Lichess...")
    report = await generate_monthly_report(settings.lichess_team_id, await get_students())
    if len(report) > 4000:
        await status_msg.delete()
        await send_long_message(message, report, parse_mode="HTML")
    else:
        await status_msg.edit_text(report, parse_mode="HTML")

def get_annual_tournament_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🌅 Основной (Утро)", callback_data="annual_main")
    builder.button(text="🐣 Новички (Утро)", callback_data="annual_novice")
    builder.button(text="⚡️ Сильный (Вечер)", callback_data="annual_evening")
    builder.button(text="🔄 Пересчитать историю", callback_data="annual_rebuild")
    builder.adjust(1)
    return builder.as_markup()

@router.message(F.text == "🏆 Годовой турнир")
async def show_annual_tournament_menu(message: Message):
    await message.answer(
        "🏆 <b>Годовой турнир (Январь — Ноябрь)</b>\n\n"
        "Выберите интересующий вас отбор или запустите полный пересчет результатов за весь год:",
        reply_markup=get_annual_tournament_keyboard(),
        parse_mode="HTML"
    )

async def run_full_rebuild(message: Message):
    status_msg = await message.answer("⏳ Начинаю фоновый пересчет годового турнира (с января по ноябрь) для всех учеников...")
    try:
        from .lichess_utils import sync_annual_tournament_results
        students = await get_students()
        if not students:
            await status_msg.edit_text("❌ Список учеников пуст.")
            return
            
        annual_updates = await sync_annual_tournament_results(settings.lichess_team_id, students, full_rebuild=True)
        if annual_updates:
            await update_students_batch(annual_updates)
            await status_msg.edit_text(
                f"✅ <b>Фоновый пересчет годового турнира успешно завершен!</b>\n\n"
                f"📊 Обработано учеников: {len(students)}\n"
                f"🔄 База данных Firestore обновлена.",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text("✅ Пересчет завершен. Новых данных не обнаружено.")
    except Exception as e:
        logging.error(f"Error in run_full_rebuild: {e}")
        await status_msg.edit_text("❌ Произошла ошибка во время пересчета истории.")

@router.callback_query(F.data.startswith("annual_"))
async def process_annual_choice(callback: CallbackQuery):
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer()
        return
    choice = callback.data.split("_")[1]
    
    if choice == "rebuild":
        await callback.answer("⏳ Запускаю полный пересчет истории...")
        asyncio.create_task(run_full_rebuild(callback.message))
        return
        
    await callback.answer("⏳ Собираю таблицу...")
    students = await get_students()
    
    from .lichess_utils import calculate_student_annual_metrics
    
    rated_students = [s for s in students if s.lichess]
    leaderboard_data = []
    
    title = ""
    target_score = 0.0
    
    if choice == "main":
        title = "Основной годовой турнир (Лига Утро)"
        target_score = 35.0
        for s in rated_students:
            m = calculate_student_annual_metrics(s, "morning")
            if m["points_sum"] > 0 and m["target"] == 35.0:
                leaderboard_data.append((s, m))
                
    elif choice == "novice":
        title = "Годовой турнир новичков (Лига Утро)"
        target_score = 25.0
        for s in rated_students:
            m = calculate_student_annual_metrics(s, "morning")
            if m["points_sum"] > 0 and m["target"] == 25.0:
                leaderboard_data.append((s, m))
                
    elif choice == "evening":
        title = "Сильный годовой турнир (Лига Вечер)"
        target_score = 25.0
        for s in rated_students:
            m = calculate_student_annual_metrics(s, "evening")
            if m["points_sum"] > 0:
                leaderboard_data.append((s, m))
                
    if not leaderboard_data:
        await callback.message.answer(f"📊 <b>{title}</b>\n\nСписок кандидатов пока пуст.", parse_mode="HTML")
        return
        
    leaderboard_data.sort(key=lambda x: -x[1]["points_sum"])
    
    report_lines = [
        f"📊 <b>{title}</b>",
        f"🎯 Целевой балл: <b>{target_score:.0f} очк.</b>",
        ""
    ]
    
    qualified_section = []
    in_progress_section = []
    
    for idx, (s, m) in enumerate(leaderboard_data, 1):
        points = m["points_sum"]
        rem = m["remaining"]
        highest_g = m["highest_group"]
        avg_rem = m["avg_needed_remaining"]
        
        if rem == 0:
            qualified_section.append(
                f"🥇 <b>{s.fio}</b> ({highest_g}) — <b>{format_points(points)}</b> очк. (Выполнено! 🎉)"
            )
        else:
            in_progress_section.append(
                f"🔹 <b>{s.fio}</b> ({highest_g}) — <b>{format_points(points)}</b> очк. (Осталось: <b>{format_points(rem)}</b>, ср. {format_points(avg_rem)}/турнир)"
            )
            
    if qualified_section:
        report_lines.append("<b>✅ Прошли квалификацию:</b>")
        report_lines.extend(qualified_section)
        report_lines.append("")
        
    if in_progress_section:
        report_lines.append("<b>⏳ В процессе отбора:</b>")
        report_lines.extend(in_progress_section)
        
    await send_long_message(callback.message, "\n".join(report_lines), parse_mode="HTML")

def get_dispatcher():
    dp = Dispatcher()
    dp.message.outer_middleware(AdminMiddleware())
    dp.include_router(router)
    return dp
