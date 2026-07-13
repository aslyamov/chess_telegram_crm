import aiohttp
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .models import Student, LICHESS_VARIANTS, LICHESS_LABELS, MonthlyTournamentResult
from .utils import format_duration, format_points
from .config import settings
from .database import make_lichess_request, get_lichess_ratings_batch, update_students_batch, db
from .stepchess_utils import get_stepchess_activity, get_stepchess_tasks_stats, filter_stepchess_activity
from aiogram.utils.formatting import Text, Bold, Italic, Code, as_list

LICHESS_API_BASE = "https://lichess.org/api"

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь"]

async def fetch_ndjson(url: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Helper to fetch and parse NDJSON data."""
    text_data = await make_lichess_request(url, headers, response_format="text", cooldown=1.0)
    results = []
    if text_data:
        for line in text_data.splitlines():
            if line.strip():
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results

async def get_team_tournaments(team_id: str) -> List[Dict[str, Any]]:
    """Fetch only Swiss tournaments for a team."""
    headers = {"Accept": "application/x-ndjson"}
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"

    swiss_url = f"{LICHESS_API_BASE}/team/{team_id}/swiss"
    swisses = await fetch_ndjson(swiss_url, headers)
    
    # Mark types
    for s in swisses: s["_type"] = "swiss"

    logging.info(f"Lichess: Found {len(swisses)} swisses for team {team_id}")
    return swisses

async def get_tournament_results(tour_type: str, tour_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch results for a specific Swiss tournament, with Firestore caching."""
    try:
        doc_ref = db.collection("tournaments").document(tour_id)
        doc = await doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            if data.get("status") == "finished":
                logging.info(f"Tournament {tour_id} loaded from Firestore cache.")
                return data.get("results", [])
    except Exception as e:
        logging.error(f"Error reading tournament {tour_id} from Firestore cache: {e}")

    headers = {"Accept": "application/x-ndjson"}
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"

    url = f"{LICHESS_API_BASE}/swiss/{tour_id}/results"
    results = await fetch_ndjson(url, headers)

    if results:
        try:
            cache_status = status or "finished"
            await db.collection("tournaments").document(tour_id).set({
                "results": results,
                "status": cache_status,
                "updated_at": datetime.utcnow().isoformat()
            })
            logging.info(f"Tournament {tour_id} results saved to Firestore cache (status: {cache_status}).")
        except Exception as e:
            logging.error(f"Error saving tournament {tour_id} to Firestore cache: {e}")

    return results

def parse_lichess_date(date_val: Any) -> Optional[datetime]:
    """Parse Lichess date which can be timestamp (int/str) or ISO string."""
    if not date_val:
        return None
    try:
        ts_float = float(date_val)
        if ts_float > 1e11: # ms
            ts_float /= 1000.0
        return datetime.fromtimestamp(ts_float)
    except (ValueError, TypeError):
        try:
            if isinstance(date_val, str):
                return datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        except Exception:
            pass
    return None

def is_in_current_month(date_obj: Optional[datetime]) -> bool:
    """Check if the given datetime is within the current month."""
    if not date_obj:
        return False
    now = datetime.now()
    return date_obj.year == now.year and date_obj.month == now.month

async def get_user_activity(username: str) -> List[Dict[str, Any]]:
    """Fetch recent activity for a single user."""
    url = f"{LICHESS_API_BASE}/user/{username}/activity"
    headers = {"Accept": "application/json"}
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"
    
    data = await make_lichess_request(url, headers, response_format="json", cooldown=4.0)
    return data if data is not None else []

async def generate_monthly_report(team_id: str, students: List[Student]) -> str:
    """Generate a monthly report of student performances in team tournaments."""
    all_tournaments = None
    try:
        doc = await db.collection("metadata").document("team_tournaments").get()
        if doc.exists:
            data = doc.to_dict()
            all_tournaments = data.get("tournaments", [])
            logging.info("Loaded team tournaments list from Firestore cache.")
    except Exception as e:
        logging.error(f"Error reading team tournaments from Firestore cache: {e}")
        
    if not all_tournaments:
        all_tournaments = await get_team_tournaments(team_id)
        
    if not all_tournaments: return f"Турниров не найдено."

    months_ru = {
        "January": "Январь", "February": "Февраль", "March": "Март", "April": "Апрель",
        "May": "Май", "June": "Июнь", "July": "Июль", "August": "Август",
        "September": "Сентябрь", "October": "Октябрь", "November": "Ноябрь", "December": "Декабрь"
    }
    now = datetime.now()
    month_display = months_ru.get(now.strftime("%B"), now.strftime("%B"))

    current_tournaments = []
    for t in all_tournaments:
        tour_date = None
        for field in ["startsAt", "createdAt", "nextStartAt"]:
            if t.get(field):
                tour_date = parse_lichess_date(t.get(field))
                if tour_date: break
        
        if tour_date and is_in_current_month(tour_date):
            if t.get("status") == "finished":
                current_tournaments.append((t, tour_date))

    if not current_tournaments: return f"В месяце {month_display} турниров клуба пока не найдено."

    student_map = {s.lichess.lower(): s for s in students if s.lichess}
    found_results = []

    async def fetch_and_process_results(tour):
        try:
            results = await get_tournament_results(tour.get("_type", "arena"), tour["id"], status=tour.get("status"))
            tour_results = []
            for res in results:
                username = res.get("username", "").lower()
                if username in student_map:
                    tour_results.append({
                        "tour_name": (tour.get("fullName") or tour.get("name", "")).replace("Онлайн-лига.", "").strip(),
                        "rank": int(res.get("rank") or 999),
                        "student_name": student_map[username].fio,
                        "score": res.get("score") or res.get("points")
                    })
            return tour_results
        except Exception as e:
            logging.error(f"Error fetching tournament results for {tour.get('id')}: {e}")
            return []

    for tour, _ in current_tournaments:
        res_list = await fetch_and_process_results(tour)
        found_results.extend(res_list)

    if not found_results: return f"В турнирах за {month_display} ученики пока не участвовали."
    found_results.sort(key=lambda x: x["rank"])

    report_items = [
        Text("📅 ", Bold(f"Подборка результатов за {month_display}")),
        ""
    ]
    for res in found_results:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(res["rank"], "🔹")
        report_items.append(
            Text(medal, " ", Bold(str(res['rank'])), f". {res['student_name']} ({res['score']} очк.) — ", Italic(res['tour_name']))
        )

    return as_list(*report_items).as_html()

async def _get_single_student_activity(student: Student, threshold_ms: float, days: int) -> Optional[Dict[str, Any]]:
    # This helper is deprecated as we now do batch filtering in generate_activity_report directly.
    return None

async def generate_activity_report(students: List[Student], days: int = 1) -> str:
    """Generate a detailed summary of student activity."""
    if not students: return "Список учеников пуст."
    
    students_with_activity = [s for s in students if s.lichess or s.stepchess]
    if not students_with_activity: return "Ни у одного ученика не указаны ники."

    now = datetime.now()
    start_dt = (now - timedelta(days=days-1)).replace(hour=0, minute=0, second=0, microsecond=0)
    threshold_ms = start_dt.timestamp() * 1000

    # 1. Пакетный сбор текущих рейтингов Lichess
    lichess_usernames = [s.lichess for s in students_with_activity if s.lichess]
    batch_ratings = {}
    if lichess_usernames:
        try:
            batch_ratings = await get_lichess_ratings_batch(lichess_usernames)
        except Exception as e:
            logging.error(f"Error fetching Lichess batch ratings: {e}")

    # Эвристику "только изменившиеся рейтинги" используем только для отчета "за сегодня" (days == 1)
    use_heuristic = (days == 1)

    async def get_student_report_data(student: Student):
        stats = {}
        has_lichess_activity = False
        lichess_update_data = {}
        
        if student.lichess:
            username_low = student.lichess.lower()
            current = batch_ratings.get(username_low)
            if current:
                # Собираем новые рейтинги для обновления в БД
                for pt in ["rapid", "blitz", "bullet", "ultraBullet", "classical", "correspondence", "puzzle"]:
                    curr_val = current.get(f"{pt}_rating")
                    if curr_val is not None:
                        lichess_update_data[f"{pt}_rating"] = curr_val
                        lichess_update_data[f"is_{pt}_provisional"] = current.get(f"is_{pt}_provisional", False)
                for pt in ["storm", "racer", "streak"]:
                    curr_val = current.get(f"{pt}_score")
                    if curr_val is not None:
                        lichess_update_data[f"{pt}_score"] = curr_val
                
                # Проверяем, изменились ли рейтинги по сравнению с сохраненными в БД
                if use_heuristic:
                    rating_changed = False
                    for pt in ["rapid", "blitz", "bullet", "ultraBullet", "classical", "correspondence", "puzzle"]:
                        curr_val = current.get(f"{pt}_rating")
                        stored_val = getattr(student, f"{pt}_rating", None)
                        if curr_val is not None and curr_val != stored_val:
                            rating_changed = True
                            break
                    if not rating_changed:
                        for pt in ["storm", "racer", "streak"]:
                            curr_val = current.get(f"{pt}_score")
                            stored_val = getattr(student, f"{pt}_score", None)
                            if curr_val is not None and curr_val != stored_val:
                                rating_changed = True
                                break
                    if rating_changed:
                        has_lichess_activity = True
                else:
                    # Если отчет за несколько дней (days > 1), опрашиваем всех детально
                    has_lichess_activity = True
            else:
                # Если нет данных в батче, опрашиваем на всякий случай
                has_lichess_activity = True

        # 1. Запрос детальной активности Lichess
        # Благодаря _lichess_sem = Semaphore(1) в database.py эти запросы пойдут строго последовательно,
        # но мы выполняем их только для тех учеников, у кого реально изменились рейтинги!
        if has_lichess_activity and student.lichess:
            try:
                activities = await get_user_activity(student.lichess)
                for act in activities:
                    if act.get("interval", {}).get("end", 0) < threshold_ms: continue
                    # Игры
                    for p_type, data in act.get("games", {}).items():
                        if p_type not in stats: stats[p_type] = {"count": 0, "delta": 0, "rating": 0}
                        stats[p_type]["count"] += (data.get("win", 0) + data.get("loss", 0) + data.get("draw", 0))
                        rp = data.get("rp", {})
                        if "after" in rp and "before" in rp:
                            stats[p_type]["delta"] += (rp["after"] - rp["before"])
                            if stats[p_type]["rating"] == 0: stats[p_type]["rating"] = rp["after"]
                    # Задачи
                    p_act = act.get("puzzles", {})
                    if p_act:
                        if "puzzles" not in stats: stats["puzzles"] = {"count": 0, "delta": 0, "rating": 0}
                        stats["puzzles"]["count"] += (p_act.get("count") or p_act.get("score", {}).get("win", 0))
                        p_rp = p_act.get("score", {}).get("rp", {})
                        if "after" in p_rp and "before" in p_rp:
                            stats["puzzles"]["delta"] += (p_rp["after"] - p_rp["before"])
                            if stats["puzzles"]["rating"] == 0: stats["puzzles"]["rating"] = p_rp["after"]
            except Exception as e:
                logging.error(f"Error fetching Lichess activity details for {student.lichess}: {e}")

        # 2. Запрос Stepchess (выполняется параллельно для всех студентов, лимитов нет)
        if student.stepchess:
            try:
                step_act, step_stats = await asyncio.gather(
                    get_stepchess_activity(student.stepchess),
                    get_stepchess_tasks_stats(student.stepchess)
                )
                breakdown = filter_stepchess_activity(step_act, step_stats, days)
                if breakdown:
                    stats["stepchess"] = {"count": sum(c["puzzles"] + c["controls"] + c["exams"] for c in breakdown.values()), "breakdown": breakdown}
            except Exception as e:
                logging.error(f"Error fetching Stepchess activity for {student.stepchess}: {e}")

        res_report = None
        if stats:
            res_report = {"name": student.fio, "is_provisional": student.is_rapid_provisional, "stats": stats}
            
        # Подготавливаем данные для обновления в БД (с пересчетом возраста и групп)
        update_info = None
        if lichess_update_data:
            for k, v in lichess_update_data.items():
                setattr(student, k, v)
            student.update_calculated_fields()
            lichess_update_data["age"] = student.age
            lichess_update_data["group_morning"] = student.group_morning
            lichess_update_data["group_evening"] = student.group_evening
            update_info = (student.id, lichess_update_data)

        return res_report, update_info

    tasks = [get_student_report_data(s) for s in students_with_activity]
    results = await asyncio.gather(*tasks)
    
    active_students = []
    updates_to_save = []
    for res_report, update_info in results:
        if res_report is not None:
            active_students.append(res_report)
        if update_info:
            updates_to_save.append(update_info)

    # Сохраняем новые рейтинги в Firestore пакетно
    if updates_to_save:
        try:
            await update_students_batch(updates_to_save)
            logging.info(f"Successfully saved {len(updates_to_save)} ratings updates to Firestore.")
        except Exception as e:
            logging.error(f"Error saving batch ratings updates to Firestore: {e}")

    if not active_students: return "Активности не обнаружено."
    
    active_students.sort(key=lambda s: sum(d["count"] for d in s["stats"].values()), reverse=True)
    perf_map = {k: v.replace(" L", "") for k, v in LICHESS_LABELS.items()}
    perf_map["puzzles"] = "Задачи (Li)"
    perf_map["stepchess"] = "Stepchess"

    report_items = []
    if days == 1:
        date_display = now.strftime("%d.%m.%Y")
        report_items.extend([Text("📊 ", Bold(f"Активность за сегодня ({date_display}):")), ""])
    else:
        start_date_display = start_dt.strftime("%d.%m.%Y")
        end_date_display = now.strftime("%d.%m.%Y")
        report_items.extend([Text("📊 ", Bold(f"Активность за {days} дн. ({start_date_display} — {end_date_display}):")), ""])
    for s in active_students:
        report_items.append(Text("👤 ", Bold(s['name']), ":"))
        for p_type, data in sorted(s["stats"].items()):
            if p_type == "stepchess": continue
            if data["count"] > 0:
                p_name = perf_map.get(p_type, p_type.capitalize())
                sign = "+" if data.get("delta", 0) > 0 else ""
                unit = "задач" if p_type == "puzzles" else "игр"
                rating_str = f"{data.get('rating', 0)}{'?' if s['is_provisional'] else ''}"
                report_items.append(
                    Text(f"🐴 {p_name}: {rating_str} ({sign}{data['delta']}) — {data['count']} {unit}")
                )

        if "stepchess" in s["stats"]:
            for course, c in s["stats"]["stepchess"]["breakdown"].items():
                report_items.append(Text("🧩 ", Bold(course), ":"))
                if c['puzzles'] > 0:
                    p_attempts = max(c.get('puzzles_success', 0), c.get('puzzles_attempts', 0))
                    p_avg = round(p_attempts / c['puzzles'], 1) if c['puzzles'] > 0 else 0
                    
                    total_time_str = format_duration(c['time'])
                    avg_time_val = c['time'] / c.get('tasks_count', 0) if c.get('tasks_count', 0) > 0 else 0
                    avg_time_str = format_duration(avg_time_val)
                    time_info = f" | ⏱ {total_time_str} (ср. {avg_time_str})" if c['time'] > 0 else ""
                    
                    report_items.append(Text(f"   └ {c['puzzles']} зад. (✅ {c.get('puzzles_success', 0)}/{c['puzzles']}) | 🔄 {p_attempts} поп. (ср. {p_avg}){time_info}"))
                if c['controls'] > 0:
                    c_attempts = c.get('controls_attempts', 0)
                    c_avg = round(c_attempts / c['controls'], 1) if c['controls'] > 0 else 0
                    solved_str = ""
                    if c.get('controls_max_solved'):
                        solved_str = " | Решено: " + ", ".join(f"{x}/10" for x in c['controls_max_solved'])
                    report_items.append(Text(f"   └ {c['controls']} контр. (✅ {c.get('controls_success', 0)}/{c['controls']}) | 🔄 {c_attempts} поп. (ср. {c_avg}){solved_str}"))
                if c['exams'] > 0:
                    e_attempts = c.get('exams_attempts', 0)
                    e_avg = round(e_attempts / c['exams'], 1) if c['exams'] > 0 else 0
                    report_items.append(Text(f"   └ {c['exams']} экз. (✅ {c.get('exams_success', 0)}/{c['exams']}) | 🔄 {e_attempts} поп. (ср. {e_avg})"))
        report_items.append("")
    return as_list(*report_items).as_html()

def _generate_rating_leaderboard_base(students: List[Student], field: str, is_prov_field: str, title: str) -> str:
    """Generic generator for Lichess rating leaderboards."""
    rated = [s for s in students if getattr(s, field) is not None]
    if not rated: return f"В базе пока нет данных для рейтинга {title}."

    calib = sorted([s for s in rated if not getattr(s, is_prov_field)], key=lambda x: (-getattr(x, field), x.fio))
    uncalib = sorted([s for s in rated if getattr(s, is_prov_field)], key=lambda x: (-getattr(x, field), x.fio))

    report_items = [Text("📊 ", Bold(f"Рейтинг ({title}):")), ""]
    if calib:
        report_items.append(Bold("✅ Откалиброванные:"))
        for i, s in enumerate(calib, 1):
            val = f"{getattr(s, field):>4} "
            report_items.append(
                Text(Code(f"{i:>2}."), " 👤 ", Code(val), f" {s.fio}")
            )
    if uncalib:
        if calib: report_items.append("")
        report_items.append(Bold("❓ Неоткалиброванные:"))
        for i, s in enumerate(uncalib, 1):
            val = f"{getattr(s, field):>4}?"
            report_items.append(
                Text(Code(f"{i:>2}."), " 👤 ", Code(val), f" {s.fio}")
            )
    return as_list(*report_items).as_html()

def generate_rapid_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "rapid_rating", "is_rapid_provisional", "Рапид")
def generate_puzzle_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "puzzle_rating", "is_puzzle_provisional", "Задачи")
def generate_blitz_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "blitz_rating", "is_blitz_provisional", "Блиц")
def generate_bullet_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "bullet_rating", "is_bullet_provisional", "Пуля")
def generate_ultraBullet_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "ultraBullet_rating", "is_ultraBullet_provisional", "Ultrabullet")
def generate_classical_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "classical_rating", "is_classical_provisional", "Классика")
def generate_correspondence_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "correspondence_rating", "is_correspondence_provisional", "Переписка")
def generate_crazyhouse_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "crazyhouse_rating", "is_crazyhouse_provisional", "Crazyhouse")
def generate_chess960_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "chess960_rating", "is_chess960_provisional", "Chess960")
def generate_kingOfTheHill_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "kingOfTheHill_rating", "is_kingOfTheHill_provisional", "King of the Hill")
def generate_threeCheck_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "threeCheck_rating", "is_threeCheck_provisional", "Three-check")
def generate_antichess_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "antichess_rating", "is_antichess_provisional", "Antichess")
def generate_atomic_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "atomic_rating", "is_atomic_provisional", "Atomic")
def generate_horde_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "horde_rating", "is_horde_provisional", "Horde")
def generate_racingKings_leaderboard(s: List[Student]): return _generate_rating_leaderboard_base(s, "racingKings_rating", "is_racingKings_provisional", "Racing Kings")

def generate_tactical_leaderboard(students: List[Student], field: str, title: str, emoji: str) -> str:
    rated = sorted([s for s in students if getattr(s, field) is not None], key=lambda x: (-getattr(x, field), x.fio))
    if not rated: return f"В базе пока нет данных для рейтинга {title}."
    report_items = [Text(f"{emoji} ", Bold(f"Топ по {title}:")), ""]
    for i, s in enumerate(rated, 1):
        val = f"{getattr(s, field):>4} "
        report_items.append(
            Text(Code(f"{i:>2}."), " 👤 ", Code(val), f" {s.fio}")
        )
    return as_list(*report_items).as_html()

def generate_rating_leaderboard(students: List[Student]) -> str: return generate_rapid_leaderboard(students)

def generate_fide_fsr_leaderboard(students: List[Student], field: str, title: str) -> str:
    rated = [s for s in students if getattr(s, field) is not None]
    if not rated: return f"В базе пока нет данных для рейтинга {title}."
    sorted_students = sorted(rated, key=lambda x: (-getattr(x, field), x.fio))
    report_items = [Text("📊 ", Bold(f"Рейтинг ({title}):")), ""]
    for i, s in enumerate(sorted_students, 1):
        val = f"{getattr(s, field):>4}"
        report_items.append(
            Text(Code(f"{i:>2}."), " 👤 ", Code(val), f" {s.fio}")
        )
    return as_list(*report_items).as_html()


def generate_rank_leaderboard(students: List[Student], rank: Optional[str]) -> str:
    if rank:
        filtered = [s for s in students if s.rank == rank]
        title = f"Разряд: {rank}"
    else:
        filtered = [s for s in students if not s.rank]
        title = "Без разряда"
        
    if not filtered:
        return f"В базе пока нет учеников с разрядом: {rank or 'Без разряда'}."
        
    def get_max_rating(s: Student):
        ratings = [
            s.fsr_rapid_rating or 0,
            s.fsr_classical_rating or 0,
            s.rapid_rating or 0,
            s.fide_rapid_rating or 0,
            s.fide_classical_rating or 0
        ]
        return max(ratings)
        
    sorted_students = sorted(filtered, key=lambda x: (-get_max_rating(x), x.fio))
    
    report_items = [Text("🏅 ", Bold(f"Список учеников по разряду ({title}):")), ""]
    for i, s in enumerate(sorted_students, 1):
        ratings_parts = []
        if s.fsr_rapid_rating:
            ratings_parts.append(f"ФШР Рп: {s.fsr_rapid_rating}")
        elif s.fsr_classical_rating:
            ratings_parts.append(f"ФШР Кл: {s.fsr_classical_rating}")
            
        if s.rapid_rating:
            is_prov = getattr(s, "is_rapid_provisional", False)
            ratings_parts.append(f"L Rapid: {s.rapid_rating}{'?' if is_prov else ''}")
            
        if s.fide_rapid_rating:
            ratings_parts.append(f"FIDE Рп: {s.fide_rapid_rating}")
            
        ratings_str = " | ".join(ratings_parts) if ratings_parts else "Нет рейтингов"
        report_items.append(
            Text(Code(f"{i:>2}."), " 👤 ", Bold(s.fio), f"\n   └ {ratings_str}")
        )
    return as_list(*report_items).as_html()


def parse_tournament_info(tour_name: str, tour_date: Optional[datetime] = None) -> Optional[dict]:
    """
    Parses tournament name to identify the month, league, group, and multiplier.
    Expected format: "Онлайн-лига. <Месяц>. <Название Группы>"
    Matches months from January to November.
    """
    # Normalize Latin characters to Russian to prevent matching errors
    norm_name = tour_name.replace("A", "А").replace("B", "В").replace("C", "С").replace("E", "Е")
    norm_lower = norm_name.lower()
    
    # Exclude December (final tournament month)
    months_lower = [m.lower() for m in MONTHS_RU]
    found_month = None
    found_month_ru = None
    for m in months_lower:
        if m in norm_lower:
            found_month = m
            found_month_ru = m.capitalize()
            break
            
    if not found_month:
        return None
        
    # Split name to get the group part (usually "Онлайн-лига. Месяц. Группа...")
    clean_name = norm_name.replace("Онлайн-лига.", "").strip()
    parts = [p.strip() for p in clean_name.split(".") if p.strip()]
    if len(parts) < 2:
        return None
        
    group_part = parts[1].lower()
    
    # Determine league first
    if "вечер" in group_part:
        league = "evening"
    else:
        league = "morning"
        
    # Strip noise words to avoid matching the letter "а" inside "группа" or "утро"
    clean_group = group_part.replace("группа", "").replace("утро", "").replace("вечер", "").strip()
    
    # Determine group and multiplier
    if "дошкол" in clean_group:
        group = "Дошкольники"
        multiplier = 1.4
    elif "а" in clean_group:
        if league == "evening":
            group = "Группа А"
            multiplier = 1.0
        else:
            if "а1" in clean_group: group = "А1"
            elif "а2" in clean_group: group = "А2"
            elif "а3" in clean_group: group = "А3"
            elif "а4" in clean_group: group = "А4"
            else: group = "А"
            multiplier = 1.0
    elif "в" in clean_group:
        if league == "evening":
            group = "Группа В"
            multiplier = 1.5
        else:
            if "в1" in clean_group: group = "В1"
            elif "в2" in clean_group: group = "В2"
            elif "в3" in clean_group: group = "В3"
            elif "в4" in clean_group: group = "В4"
            else: group = "В"
            multiplier = 1.25
    elif "с" in clean_group:
        if league == "evening":
            group = "Группа С"
            multiplier = 2.0
        else:
            if "с1" in clean_group: group = "С1"
            elif "с2" in clean_group: group = "С2"
            else: group = "С"
            multiplier = 1.5
    elif "d" in clean_group or "д" in clean_group:
        if "d1" in clean_group or "д1" in clean_group:
            group = "D1"
            multiplier = 2.0
        elif "d2" in clean_group or "д2" in clean_group:
            group = "D2"
            multiplier = 2.5
        else:
            group = "D"
            multiplier = 2.5
    elif "е" in clean_group:
        group = "Е"
        multiplier = 3.0
    else:
        return None
        
    # Overwrite multiplier for January and February 2026 tournaments if applicable
    if tour_date and tour_date.year == 2026 and found_month_ru in ["Январь", "Февраль"]:
        if league == "evening":
            if group == "Группа А":
                multiplier = 1.0
            elif group == "Группа В":
                multiplier = 1.5
            elif group == "Группа С":
                multiplier = 2.0
        else:  # morning
            if group in ["А", "А1", "А2", "А3", "А4"]:
                multiplier = 1.0
            elif group in ["В1", "В2"]:
                multiplier = 1.0
            elif group in ["В3", "В4", "В"]:
                multiplier = 1.5
            elif group in ["С", "С1", "С2"]:
                multiplier = 2.0
            elif group in ["D", "D1", "D2"]:
                multiplier = 2.5
            elif group == "Е":
                multiplier = 3.0
            
    return {
        "month": found_month_ru,
        "league": league,
        "group": group,
        "multiplier": multiplier
    }


async def sync_annual_tournament_results(team_id: str, students: List[Student], full_rebuild: bool = False) -> List[tuple]:
    """
    Syncs annual tournament results for students from Lichess.
    If full_rebuild is True, fetches all tournaments (up to 100).
    If False, fetches only tournaments in the current and previous months.
    Returns a list of updates (student_id, update_dict) to write to database.
    """
    all_tournaments = await get_team_tournaments(team_id)
    if not all_tournaments:
        return []
        
    try:
        await db.collection("metadata").document("team_tournaments").set({
            "tournaments": all_tournaments,
            "updated_at": datetime.utcnow().isoformat()
        })
        logging.info("Saved team tournaments list to Firestore.")
    except Exception as e:
        logging.error(f"Error saving team tournaments list to Firestore: {e}")
        
    now = datetime.now()
    months_ru_mapping = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    
    # Identify which months we want to update
    if full_rebuild:
        months_to_update = set(MONTHS_RU)
    else:
        curr_m = months_ru_mapping.get(now.month)
        prev_date = now - timedelta(days=32)
        prev_m = months_ru_mapping.get(prev_date.month)
        months_to_update = {curr_m, prev_m}
        months_to_update.discard("Декабрь")
        
    # Filter tournaments matching the months we want to update
    relevant_tournaments = []
    for t in all_tournaments:
        starts_at = t.get("startsAt")
        tour_date = parse_lichess_date(starts_at) if starts_at else None
        if not tour_date or tour_date.year != now.year:
            continue
            
        parsed_info = parse_tournament_info(t.get("fullName") or t.get("name", ""), tour_date)
        if parsed_info and parsed_info["month"] in months_to_update:
            # Only finished tournaments
            if t.get("status") == "finished":
                relevant_tournaments.append((t, parsed_info, tour_date))
                
    if not relevant_tournaments:
        return []
        
    # Map student Lichess usernames
    student_map = {s.lichess.lower(): s for s in students if s.lichess}
    
    # Store aggregated scores: student_id -> month -> best_result
    updates_cache = {} # student_id -> {month: MonthlyTournamentResult}
    
    # Fetch results for each relevant tournament
    for t, info, tour_date in relevant_tournaments:
        tour_id = t["id"]
        month = info["month"]
        multiplier = info["multiplier"]
        group = info["group"]
        
        try:
            results = await get_tournament_results(t.get("_type", "swiss"), tour_id, status=t.get("status"))
            for res in results:
                username = res.get("username", "").lower()
                if username in student_map:
                    student = student_map[username]
                    score = float(res.get("score") or res.get("points") or 0.0)
                    points_multiplied = score * multiplier
                    
                    if student.id not in updates_cache:
                        updates_cache[student.id] = {}
                        
                    # If there's already a result for this month, keep the one with higher points_multiplied
                    existing = updates_cache[student.id].get(month)
                    if not existing or points_multiplied > existing.points_multiplied:
                        updates_cache[student.id][month] = MonthlyTournamentResult(
                            score=score,
                            group=group,
                            multiplier=multiplier,
                            points_multiplied=points_multiplied,
                            date=tour_date.strftime("%Y-%m-%d"),
                            tournament_id=tour_id,
                            tournament_name=t.get("fullName") or t.get("name", "")
                        )
            # Safe sleep of 1.0 seconds between tournaments to avoid 429
            await asyncio.sleep(1.0)
        except Exception as e:
            logging.error(f"Error fetching results for tournament {tour_id}: {e}")
            
    # Prepare updates for database
    batch_updates = []
    for student in students:
        updated_results = {}
        has_changes = False
        
        # Copy existing annual_results (if any)
        if student.annual_results:
            for m, r in student.annual_results.items():
                if isinstance(r, dict):
                    updated_results[m] = MonthlyTournamentResult(**r)
                else:
                    updated_results[m] = r
        else:
            has_changes = True
            
        # Ensure all 11 months are initialized
        for m in MONTHS_RU:
            if m not in updated_results:
                updated_results[m] = MonthlyTournamentResult(
                    score=0.0,
                    group="Нет данных",
                    multiplier=1.0,
                    points_multiplied=0.0,
                    date="",
                    tournament_id=""
                )
                has_changes = True
                
        # Apply fetched updates for the relevant months
        student_updates = updates_cache.get(student.id, {})
        for m in months_to_update:
            if m in student_updates:
                new_res = student_updates[m]
                old_res = updated_results.get(m)
                if (not old_res or 
                    old_res.tournament_id != new_res.tournament_id or 
                    old_res.score != new_res.score or
                    old_res.group != new_res.group or
                    old_res.multiplier != new_res.multiplier or
                    old_res.points_multiplied != new_res.points_multiplied):
                    updated_results[m] = new_res
                    has_changes = True
            else:
                if full_rebuild:
                    old_res = updated_results.get(m)
                    if old_res and (old_res.score != 0.0 or old_res.group != "Нет данных"):
                        updated_results[m] = MonthlyTournamentResult(
                            score=0.0,
                            group="Нет данных",
                            multiplier=1.0,
                            points_multiplied=0.0,
                            date="",
                            tournament_id=""
                        )
                        has_changes = True
                        
        if has_changes:
            serialized_results = {m: r.model_dump() for m, r in updated_results.items()}
            batch_updates.append((student.id, {"annual_results": serialized_results}))
            student.annual_results = updated_results
            
    return batch_updates


def calculate_student_annual_metrics(student: Student, league: str) -> dict:
    """
    Calculates annual tournament metrics for a student.
    league can be "morning" or "evening".
    """
    results = student.annual_results or {}
    
    points_sum = 0.0
    played_months = []
    highest_group_from_results = None
    highest_multiplier = -1.0
    
    for m in MONTHS_RU:
        res = results.get(m)
        if res:
            if isinstance(res, dict):
                res = MonthlyTournamentResult(**res)
            
            g = res.group
            if g != "Нет данных" and res.score > 0:
                is_evening = "Вечер" in g or g in ["Группа А", "Группа В", "Группа С"]
                tour_league = "evening" if is_evening else "morning"
                
                if tour_league == league:
                    points_sum += res.points_multiplied
                    played_months.append(m)
                    if res.multiplier >= highest_multiplier:
                        highest_multiplier = res.multiplier
                        highest_group_from_results = g
                        
    if highest_group_from_results:
        highest_group = highest_group_from_results
    else:
        if league == "morning":
            highest_group = student.group_morning or "Нет данных"
        else:
            highest_group = student.group_evening or "Нет данных"
            
    if league == "morning":
        g_norm = (highest_group or "").replace("A", "А").replace("B", "В").replace("C", "С").replace("E", "Е")
        is_high_group = any(x in g_norm for x in ["D", "Е"])
        target = 35.0 if is_high_group else 25.0
        tournament_name = "Основной годовой турнир" if is_high_group else "Турнир новичков"
    else:
        target = 25.0
        tournament_name = "Сильный годовой турнир"
        
    remaining = max(0.0, target - points_sum)
    
    now = datetime.now()
    months_ru_mapping = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    
    current_month_name = months_ru_mapping.get(now.month, "")
    try:
        current_month_idx = MONTHS_RU.index(current_month_name)
    except ValueError:
        current_month_idx = 11
        
    remaining_tours = max(1, 11 - current_month_idx)
    
    avg_needed_overall = target / 11.0
    avg_needed_remaining = remaining / remaining_tours
    
    return {
        "points_sum": points_sum,
        "highest_group": highest_group,
        "target": target,
        "remaining": remaining,
        "avg_needed_overall": avg_needed_overall,
        "avg_needed_remaining": avg_needed_remaining,
        "tournament_name": tournament_name,
        "played_count": len(played_months)
    }


async def generate_student_annual_report(student: Student) -> str:
    """
    Generates a detailed HTML report of annual tournament results for a single student.
    """
    all_tournaments = None
    try:
        doc = await db.collection("metadata").document("team_tournaments").get()
        if doc.exists:
            data = doc.to_dict()
            all_tournaments = data.get("tournaments", [])
            logging.info("Loaded team tournaments list from Firestore cache for annual report.")
    except Exception as e:
        logging.error(f"Error reading team tournaments from Firestore cache for annual report: {e}")
        
    if not all_tournaments:
        try:
            all_tournaments = await get_team_tournaments(settings.lichess_team_id)
        except Exception as e:
            logging.error(f"Error fetching team tournaments for mapping: {e}")
            all_tournaments = []
            
    tour_names = {t["id"]: (t.get("fullName") or t.get("name", "")) for t in all_tournaments} if all_tournaments else {}
        
    results = student.annual_results or {}
    
    report_items = [
        f"🏆 <b>Годовой турнир: {student.fio}</b>",
        f"📅 <i>Период: Январь — Ноябрь</i>",
        ""
    ]
    
    for month in MONTHS_RU:
        res = results.get(month)
        if res:
            if isinstance(res, dict):
                res = MonthlyTournamentResult(**res)
            
            if res.tournament_id:
                t_name = res.tournament_name or tour_names.get(res.tournament_id) or f"Турнир {res.tournament_id}"
                t_name = t_name.replace("Онлайн-лига.", "").strip()
                t_url = f"https://lichess.org/swiss/{res.tournament_id}"
                t_link = f'<a href="{t_url}">{t_name}</a>'
                
                report_items.append(
                    f"• <b>{month}:</b> {t_link}\n"
                    f"  Очки: <b>{format_points(res.score)}</b> | Множитель: <b>{res.multiplier}</b> | Итого: <b>{format_points(res.points_multiplied)}</b>"
                )
            else:
                report_items.append(f"• <b>{month}:</b> Нет участия (Итого: <b>0.0</b>)")
        else:
            report_items.append(f"• <b>{month}:</b> Нет данных")
            
    report_items.append("")
    report_items.append("──────────────────")
    
    # Morning league metrics
    m_metrics = calculate_student_annual_metrics(student, "morning")
    m_pts = m_metrics["points_sum"]
    m_target = m_metrics["target"]
    m_rem = m_metrics["remaining"]
    m_tour = m_metrics["tournament_name"]
    
    status_m = "Выполнено! 🎉" if m_rem == 0 else f"осталось {format_points(m_rem)} очк. (ср. {format_points(m_metrics['avg_needed_remaining'])}/турнир)"
    report_items.append(f"🌅 <b>Утро:</b> {format_points(m_pts)} из {m_target:.0f} в {m_tour}\n  ({status_m})")
        
    # Evening league metrics
    e_metrics = calculate_student_annual_metrics(student, "evening")
    e_pts = e_metrics["points_sum"]
    e_target = e_metrics["target"]
    e_rem = e_metrics["remaining"]
    
    status_e = "Выполнено! 🎉" if e_rem == 0 else f"осталось {format_points(e_rem)} очк. (ср. {format_points(e_metrics['avg_needed_remaining'])}/турнир)"
    report_items.append(f"⚡️ <b>Вечер:</b> {format_points(e_pts)} из {e_target:.0f}\n  ({status_e})")
        
    return "\n".join(report_items)

