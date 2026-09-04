from google.cloud.firestore import AsyncClient
from google.oauth2 import service_account
import firebase_admin
from firebase_admin import credentials
import aiohttp
import logging
import asyncio
import os
import time
from bs4 import BeautifulSoup
from .config import settings
from .models import Student, LICHESS_VARIANTS
from typing import List, Optional, Any, Dict


def _parse_lichess_perfs(user_data: dict) -> dict:
    """Parse Lichess API user perfs dict into flat ratings/tactical dict."""
    perfs = user_data.get("perfs", {})
    result: dict = {}
    for pt in LICHESS_VARIANTS:
        p_data = perfs.get(pt, {})
        is_prov = p_data.get("prov", False) or p_data.get("games", 0) == 0
        result[f"{pt}_rating"] = p_data.get("rating")
        result[f"is_{pt}_provisional"] = is_prov
    for pt in ("storm", "racer", "streak"):
        result[f"{pt}_score"] = perfs.get(pt, {}).get("score")
    return result


_lichess_sem: Optional[asyncio.Semaphore] = None
_fsr_lock: Optional[asyncio.Lock] = None


def _get_lichess_sem() -> asyncio.Semaphore:
    global _lichess_sem
    if _lichess_sem is None:
        _lichess_sem = asyncio.Semaphore(3)  # 3 concurrent — safe with Lichess token
    return _lichess_sem


def _get_fsr_lock() -> asyncio.Lock:
    global _fsr_lock
    if _fsr_lock is None:
        _fsr_lock = asyncio.Lock()
    return _fsr_lock



# Initialize Firebase for general purposes if needed
if not firebase_admin._apps:
    try:
        if os.path.exists(settings.google_application_credentials):
            cred = credentials.Certificate(settings.google_application_credentials)
            firebase_admin.initialize_app(cred)
        else:
            logging.info("serviceAccountKey.json not found. Initializing Firebase Admin with Application Default Credentials.")
            firebase_admin.initialize_app()
    except Exception as e:
        logging.warning(f"Failed to initialize Firebase Admin: {e}. Trying default initialization.")
        try:
            firebase_admin.initialize_app()
        except Exception as e2:
            logging.error(f"Critical error initializing Firebase Admin: {e2}")

# Initialize Async Firestore client
db: AsyncClient = None  # type: ignore
try:
    if os.path.exists(settings.google_application_credentials):
        creds = service_account.Credentials.from_service_account_file(settings.google_application_credentials)
        db = AsyncClient(credentials=creds, database="default")
    else:
        logging.info("serviceAccountKey.json not found. Initializing Async Firestore client with Application Default Credentials.")
        db = AsyncClient(database="default")
except Exception as e:
    logging.warning(f"Failed to initialize Firestore with service account: {e}. Trying default initialization.")
    db = AsyncClient(database="default")

COLLECTION_NAME = "students"

# Singleton session management
_session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

async def make_lichess_request(
    url: str, 
    headers: dict, 
    method: str = "GET",
    data: Optional[str] = None,
    response_format: str = "json", 
    cooldown: float = 1.0
) -> Optional[Any]:
    """
    Выполняет запрос к Lichess API с ограничением частоты, обработкой 429 и повторными попытками.
    """
    max_retries = 3
    base_backoff = 61.0
    
    async with _get_lichess_sem():
        for attempt in range(1, max_retries + 1):
            try:
                session = await get_session()
                async with session.request(method, url, headers=headers, data=data) as response:
                    if response.status == 200:
                        if response_format == "json":
                            res_data = await response.json()
                        else:
                            res_data = await response.text()
                        await asyncio.sleep(cooldown)
                        return res_data
                    elif response.status == 429:
                        retry_after = response.headers.get("Retry-After")
                        wait_time = int(retry_after) if (retry_after and retry_after.isdigit()) else int(base_backoff * attempt)
                        logging.warning(
                            f"Lichess API returned 429 for {url}. "
                            f"Попытка {attempt}/{max_retries}. "
                            f"Указание Lichess (Retry-After): {retry_after} сек. "
                            f"Ожидание {wait_time}с под блокировкой..."
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logging.warning(f"Lichess API returned status {response.status} for {url}")
                        await asyncio.sleep(cooldown)
                        return None
            except Exception as e:
                logging.error(f"Error making Lichess request to {url} (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2.0 * attempt)
                else:
                    return None
        return None

async def get_lichess_ratings_batch(usernames: List[str]) -> Dict[str, dict]:
    """Fetch ratings and tactical stats from Lichess API for multiple users in a single request."""
    if not usernames:
        return {}
        
    url = "https://lichess.org/api/users"
    headers = {
        "Accept": "application/json",
        "Content-Type": "text/plain"
    }
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"
    
    # Lichess expects usernames separated by commas
    payload = ",".join(usernames)
    
    data = await make_lichess_request(
        url, 
        headers, 
        method="POST", 
        data=payload, 
        response_format="json", 
        cooldown=1.0
    )
    
    results = {}
    if data:
        for user_data in data:
            username = user_data.get("username", "").lower()
            if not username:
                continue
            results[username] = _parse_lichess_perfs(user_data)
            
    return results



# --- Students in-memory cache (TTL = 60 seconds) ---
_students_cache: Optional[List[Student]] = None
_students_cache_time: float = 0.0
_STUDENTS_CACHE_TTL: float = 60.0


def invalidate_students_cache() -> None:
    """Invalidate in-memory students cache. Call after any mutation."""
    global _students_cache, _students_cache_time
    _students_cache = None
    _students_cache_time = 0.0


async def add_student(student: Student) -> str:
    """Add a new student to Firestore."""
    student_dict = student.model_dump(exclude={"id"})
    _, doc_ref = await db.collection(COLLECTION_NAME).add(student_dict)
    invalidate_students_cache()
    return doc_ref.id


async def get_students() -> List[Student]:
    """Get all students from Firestore, with 60-second in-memory cache."""
    global _students_cache, _students_cache_time
    now = time.monotonic()
    if _students_cache is not None and (now - _students_cache_time) < _STUDENTS_CACHE_TTL:
        return _students_cache

    docs = db.collection(COLLECTION_NAME).stream()
    students = []
    async for doc in docs:
        data = doc.to_dict()
        if data is not None:
            data["id"] = doc.id
            students.append(Student(**data))

    _students_cache = students
    _students_cache_time = now
    return students


async def get_student_by_id(student_id: str) -> Optional[Student]:
    """Get a student by their ID."""
    doc = await db.collection(COLLECTION_NAME).document(student_id).get()
    if doc.exists:
        data = doc.to_dict()
        if data is not None:
            data["id"] = doc.id
            return Student(**data)
    return None

async def update_student(student_id: str, student_data: dict) -> None:
    """Update student data."""
    await db.collection(COLLECTION_NAME).document(student_id).update(student_data)
    invalidate_students_cache()

async def update_students_batch(updates: List[tuple]) -> None:
    """Perform batch updates in Firestore. updates is a list of (student_id, data_dict)."""
    if not updates:
        return
    batch = db.batch()
    for student_id, data in updates:
        doc_ref = db.collection(COLLECTION_NAME).document(student_id)
        batch.update(doc_ref, data)
    await batch.commit()
    invalidate_students_cache()

async def delete_student(student_id: str) -> None:
    """Delete a student by ID."""
    await db.collection(COLLECTION_NAME).document(student_id).delete()
    invalidate_students_cache()

async def search_students_by_name(name_query: str) -> List[Student]:
    """Search students by partial FIO match (uses cache)."""
    students = await get_students()
    return [s for s in students if name_query.lower() in s.fio.lower()]


async def get_lichess_rating(username: str) -> Optional[dict]:
    """Fetch ratings and tactical stats from Lichess API."""
    url = f"https://lichess.org/api/user/{username}"
    headers = {"Accept": "application/json"}
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"
    
    data = await make_lichess_request(url, headers, response_format="json", cooldown=1.0)
    if data:
        return _parse_lichess_perfs(data)
    return None

async def get_fsr_ratings(fsr_id: str) -> Optional[dict]:
    """Fetch Classical, Rapid, Blitz ratings from Ruchess (FSR) by scraping."""
    url = f"https://ratings.ruchess.ru/people/{fsr_id}"
    async with _get_fsr_lock():
        try:
            session = await get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    results: Dict[str, Optional[int]] = {"classical": None, "rapid": None, "blitz": None}
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    for li in soup.find_all("li", class_="list-group-item"):
                        text = li.get_text()
                        for key, label in [("classical", "Классические"), ("rapid", "Быстрые"), ("blitz", "Блиц")]:
                            if label in text:
                                b_tag = li.find("b")
                                if b_tag:
                                    results[key] = int(b_tag.text)
                    await asyncio.sleep(0.5)
                    return results
                else:
                    logging.warning(f"Ruchess returned status {response.status} for ID {fsr_id}")
            # Cooldown delay of 0.5s to prevent IP ban
            await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Error fetching FSR ratings for {fsr_id}: {e}")
    return None

async def get_fide_ratings(fide_id: str) -> Optional[dict]:
    """Fetch Classical, Rapid, Blitz ratings from FIDE via Lichess API."""
    url = f"https://lichess.org/api/fide/player/{fide_id}"
    headers = {"Accept": "application/json"}
    if settings.lichess_api_token:
        headers["Authorization"] = f"Bearer {settings.lichess_api_token}"
    
    data = await make_lichess_request(url, headers, response_format="json", cooldown=1.5)
    if data:
        return {
            "classical": data.get("standard"),
            "rapid": data.get("rapid"),
            "blitz": data.get("blitz")
        }
    return None

