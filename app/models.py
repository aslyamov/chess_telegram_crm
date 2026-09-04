from pydantic import BaseModel, field_validator
from typing import Optional, Dict, List
from .utils import calculate_detailed_age, get_age_years, calculate_morning_group, calculate_evening_group

# Константы для Lichess
LICHESS_VARIANTS = [
    "rapid", "blitz", "bullet", "ultraBullet", "classical", "correspondence",
    "crazyhouse", "chess960", "kingOfTheHill", "threeCheck", "antichess", 
    "atomic", "horde", "racingKings", "puzzle"
]

LICHESS_LABELS: Dict[str, str] = {
    "rapid": "📊 Рапид L",
    "blitz": "⚡️ Блиц L",
    "bullet": "☄️ Пуля L",
    "ultraBullet": "🚀 Ultra L",
    "classical": "🐢 Классика L",
    "correspondence": "📬 Переписка L",
    "crazyhouse": "🤡 Crazy L",
    "chess960": "🎲 960 L",
    "kingOfTheHill": "👑 KOTH L",
    "threeCheck": "➕ 3Check L",
    "antichess": "📉 Anti L",
    "atomic": "☢️ Atomic L",
    "horde": "🏹 Horde L",
    "racingKings": "🏁 Racing L",
    "puzzle": "🧩 Задачи L"
}

class MonthlyTournamentResult(BaseModel):
    score: float
    group: str
    multiplier: float
    points_multiplied: float
    date: str
    tournament_id: str
    tournament_name: Optional[str] = None


class Student(BaseModel):
    id: Optional[str] = None
    fio: str
    annual_results: Dict[str, MonthlyTournamentResult] = {}
    birth_date: Optional[str] = None
    age: Optional[str] = None
    fsr_id: Optional[str] = None
    fide_id: Optional[str] = None
    city: Optional[str] = None
    lichess: Optional[str] = None
    stepchess: Optional[str] = None
    # Рейтинги Lichess
    rapid_rating: Optional[int] = None
    blitz_rating: Optional[int] = None
    bullet_rating: Optional[int] = None
    ultraBullet_rating: Optional[int] = None
    classical_rating: Optional[int] = None
    correspondence_rating: Optional[int] = None
    
    crazyhouse_rating: Optional[int] = None
    chess960_rating: Optional[int] = None
    kingOfTheHill_rating: Optional[int] = None
    threeCheck_rating: Optional[int] = None
    antichess_rating: Optional[int] = None
    atomic_rating: Optional[int] = None
    horde_rating: Optional[int] = None
    racingKings_rating: Optional[int] = None

    fsr_rating: Optional[int] = None  # Deprecated — use fsr_rapid_rating
    fide_rating: Optional[int] = None  # Deprecated — use fide_rapid_rating

    fsr_classical_rating: Optional[int] = None
    fsr_rapid_rating: Optional[int] = None
    fsr_blitz_rating: Optional[int] = None

    fide_classical_rating: Optional[int] = None
    fide_rapid_rating: Optional[int] = None
    fide_blitz_rating: Optional[int] = None
    # Флаги калибровки (провижн)
    is_rapid_provisional: bool = False
    is_blitz_provisional: bool = False
    is_bullet_provisional: bool = False
    is_ultraBullet_provisional: bool = False
    is_classical_provisional: bool = False
    is_correspondence_provisional: bool = False
    
    is_crazyhouse_provisional: bool = False
    is_chess960_provisional: bool = False
    is_kingOfTheHill_provisional: bool = False
    is_threeCheck_provisional: bool = False
    is_antichess_provisional: bool = False
    is_atomic_provisional: bool = False
    is_horde_provisional: bool = False
    is_racingKings_provisional: bool = False
    
    # Тактические показатели Lichess
    puzzle_rating: Optional[int] = None
    is_puzzle_provisional: bool = False
    storm_score: Optional[int] = None
    racer_score: Optional[int] = None
    streak_score: Optional[int] = None

    group_morning: Optional[str] = None
    group_evening: Optional[str] = None
    rank: Optional[str] = "нет разряда"

    @field_validator("annual_results", mode="before")
    @classmethod
    def coerce_annual_results(cls, v: dict) -> dict:
        """Auto-convert dict values from Firestore into MonthlyTournamentResult objects."""
        if not v:
            return v
        result = {}
        for month, entry in v.items():
            if isinstance(entry, dict):
                result[month] = MonthlyTournamentResult(**entry)
            else:
                result[month] = entry
        return result

    def update_calculated_fields(self):
        """Recalculate age and groups based on current birth_date and rapid_rating."""
        if self.fsr_rapid_rating is None and self.fsr_rating is not None:
            self.fsr_rapid_rating = self.fsr_rating
        if self.fide_rapid_rating is None and self.fide_rating is not None:
            self.fide_rapid_rating = self.fide_rating

        self.age = calculate_detailed_age(self.birth_date)
        age_years = get_age_years(self.birth_date)
        # Группы рассчитываются по рейтингу: неоткалиброванный рейтинг (со знаком ?) считается как 600
        rating_for_groups = 600 if self.is_rapid_provisional else self.rapid_rating
        self.group_morning = calculate_morning_group(age_years, rating_for_groups)
        self.group_evening = calculate_evening_group(rating_for_groups)


