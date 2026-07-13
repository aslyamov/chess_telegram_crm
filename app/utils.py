from datetime import date
from typing import Optional, Tuple

def calculate_detailed_age(birth_date_str: str) -> str:
    """
    Calculates age in format 'YY лет, MM мес., DD дн.'
    Expects birth_date_str in format 'DD.MM.YYYY' or similar.
    """
    if not birth_date_str or birth_date_str in ["—", "пропуск", ""]:
        return "—"
    
    try:
        # Assuming format DD.MM.YYYY. Adjust if your data format is different.
        day, month, year = map(int, birth_date_str.split('.'))
        born = date(year, month, day)
        today = date.today()
        
        years = today.year - born.year
        months = today.month - born.month
        days = today.day - born.day

        if days < 0:
            months -= 1
            # Get days in previous month
            prev_month = today.month - 1 if today.month > 1 else 12
            prev_year = today.year if today.month > 1 else today.year - 1
            import calendar
            days_in_prev_month = calendar.monthrange(prev_year, prev_month)[1]
            days += days_in_prev_month

        if months < 0:
            years -= 1
            months += 12

        return f"{years:02d} лет, {months:02d} мес., {days:02d} дн."
    except Exception:
        return "—"

def get_age_years(birth_date_str: str) -> Optional[int]:
    """Helper to get only full years for group logic."""
    if not birth_date_str or birth_date_str in ["—", "пропуск", ""]:
        return None
    try:
        day, month, year = map(int, birth_date_str.split('.'))
        born = date(year, month, day)
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return None

def calculate_morning_group(age_years: Optional[int], rating: Optional[int]) -> str:
    """Logic from Google Sheets formula for Morning Group."""
    if rating is None or age_years is None:
        return "Нет данных"
    
    if rating <= 800:
        if age_years <= 6: return "Дошкольники"
        if age_years <= 8: return "А1"
        if age_years <= 10: return "А2"
        return "А3"
    elif rating <= 1000:
        if age_years <= 8: return "В1"
        if age_years <= 10: return "В2"
        return "В3"
    elif rating <= 1200:
        if age_years <= 10: return "С1"
        return "С2"
    elif rating <= 1400:
        return "D1"
    elif rating <= 1650:
        return "D2"
    else:
        return "Е"

def calculate_evening_group(rating: Optional[int]) -> str:
    """Logic from Google Sheets formula for Evening Group."""
    if rating is None:
        return "Нет данных"
    
    if rating < 800:
        return "Группа А"
    elif rating < 1300:
        return "Группа В"
    else:
        return "Группа С"

def format_duration(seconds: float) -> str:
    """Format duration in seconds to a human-readable string like '12 мин 30 сек'."""
    total_seconds = int(round(seconds))
    if total_seconds <= 0:
        return "0 сек"
    
    minutes = total_seconds // 60
    secs = total_seconds % 60
    
    parts = []
    if minutes > 0:
        parts.append(f"{minutes} мин")
    if secs > 0 or not parts:
        parts.append(f"{secs} сек")
        
    return " ".join(parts)

def format_points(val: float) -> str:
    """Formats points/scores to 1 or 2 decimal places (e.g. 3.0, 2.5, 3.75)."""
    rounded = round(val, 2)
    if (rounded * 2).is_integer():
        return f"{rounded:.1f}"
    return f"{rounded:.2f}"

