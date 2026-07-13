
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .models import Student
from .database import get_session

STEPCHESS_ACTIVITY_URL = "https://stepchess.ru/users/get_student_activity/{stepchess_id}?page=1"
STEPCHESS_STATS_URL = "https://stepchess.ru/users/get_tasks_stats/{stepchess_id}/50/0"

async def get_stepchess_activity(stepchess_id: str) -> Dict[str, Any]:
    """Fetch recent activity for a Stepchess user."""
    url = STEPCHESS_ACTIVITY_URL.format(stepchess_id=stepchess_id)
    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                logging.warning(f"Stepchess Activity API returned {response.status} for {url}")
                return {}
    except Exception as e:
        logging.error(f"Error fetching Stepchess activity from {url}: {e}")
        return {}

async def get_stepchess_tasks_stats(stepchess_id: str) -> Dict[str, Any]:
    """Fetch tasks statistics for a Stepchess user using POST."""
    url = STEPCHESS_STATS_URL.format(stepchess_id=stepchess_id)
    try:
        session = await get_session()
        # Server expects POST with empty body based on CURL
        async with session.post(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                logging.warning(f"Stepchess Stats API returned {response.status} for {url}")
                return {}
    except Exception as e:
        logging.error(f"Error fetching Stepchess stats from {url}: {e}")
        return {}

def filter_stepchess_activity(activity_data: Dict[str, Any], stats_data: Dict[str, Any], days: int = 1) -> Dict[str, Any]:
    """Filter Stepchess activity and stats by date with detailed breakdown."""
    now = datetime.now()
    if days == 1:
        start_date = now.date()
    else:
        start_date = (now - timedelta(days=days-1)).date()

    # Build a lookup dictionary for puzzle results from stats_data
    puzzle_results = {}
    if stats_data and stats_data.get("status") == "ok":
        for task in stats_data.get("tasks_stats", []):
            p_id = task.get("puzzle_id")
            if p_id is not None:
                puzzle_results[p_id] = task.get("result")

    # Breakdown structure:
    # { "Course Name": { 
    #     "puzzles": 0, "puzzles_success": 0, "puzzles_attempts": 0,
    #     "controls": 0, "controls_success": 0, "controls_attempts": 0,
    #     "exams": 0, "exams_success": 0, "exams_attempts": 0,
    #     "time": 0, "efforts": 0, "success": 0, "tasks_count": 0, "solved_tasks_count": 0 
    # } }
    breakdown = {}

    def get_course_node(course_title):
        title = course_title or "Общие задачи"
        if title not in breakdown:
            breakdown[title] = {
                "puzzles": 0,
                "controls": 0,
                "exams": 0,
                "puzzles_success": 0,
                "controls_success": 0,
                "exams_success": 0,
                "puzzles_attempts": 0,
                "controls_attempts": 0,
                "exams_attempts": 0,
                "time": 0,
                "efforts": 0,
                "success": 0,
                "tasks_count": 0,
                "solved_tasks_count": 0,
                "controls_max_solved": []
            }
        return breakdown[title]

    # 1. Activity (Puzzles solved)
    if activity_data and activity_data.get("status") == "ok":
        for act in activity_data.get("activity", []):
            act_date_str = act.get("date")
            if act_date_str:
                try:
                    act_date = datetime.strptime(act_date_str, "%Y-%m-%d").date()
                    if act_date >= start_date:
                        node = get_course_node(act.get("course_title"))
                        node["puzzles"] += 1
                        
                        # Determine if the puzzle is solved.
                        # Unsolved puzzles have result == 0 in tasks_stats.
                        # If the puzzle is not in puzzle_results (e.g. older than the 50 limit),
                        # we default to True (solved) to maintain backward compatibility.
                        p_id = act.get("puzzle_id")
                        is_solved = True
                        if p_id in puzzle_results:
                            is_solved = (puzzle_results[p_id] != 0)
                        
                        if is_solved:
                            node["success"] += 1
                            node["puzzles_success"] += 1
                except ValueError:
                    continue

    # 2. Controls (Grouped by task_id to get unique tasks, success rates, and attempts)
    if activity_data and activity_data.get("status") == "ok":
        course_controls = {} # course_title -> { task_id -> {"results": [], "solved_counts": []} }
        for ctrl in activity_data.get("controls", []):
            last_attempt_str = ctrl.get("last_attempt")
            if last_attempt_str:
                try:
                    last_attempt_date = datetime.strptime(last_attempt_str, "%Y-%m-%d %H:%M:%S").date()
                    if last_attempt_date >= start_date:
                        c_title = ctrl.get("course_title")
                        task_id = ctrl.get("task_id")
                        result = ctrl.get("result")
                        solved_count = ctrl.get("solved_count")
                        
                        node = get_course_node(c_title)
                        node["controls_attempts"] += 1
                        
                        if c_title not in course_controls:
                            course_controls[c_title] = {}
                        if task_id not in course_controls[c_title]:
                            course_controls[c_title][task_id] = {"results": [], "solved_counts": []}
                        course_controls[c_title][task_id]["results"].append(result)
                        if solved_count is not None:
                            course_controls[c_title][task_id]["solved_counts"].append(solved_count)
                except ValueError:
                    continue

        for c_title, tasks in course_controls.items():
            node = get_course_node(c_title)
            node["controls"] = len(tasks)
            successful_controls = sum(1 for t_info in tasks.values() if any(r == 1 for r in t_info["results"]))
            node["controls_success"] = successful_controls
            node["success"] += successful_controls
            
            max_solved_list = []
            for t_info in tasks.values():
                if t_info["solved_counts"]:
                    max_solved_list.append(max(t_info["solved_counts"]))
            if max_solved_list:
                node["controls_max_solved"] = max_solved_list

    # 3. Exams (Grouped by task_id to get unique tasks, success rates, and attempts)
    if activity_data and activity_data.get("status") == "ok":
        course_exams = {} # course_title -> { task_id -> [results] }
        for exam in activity_data.get("exams", []):
            last_attempt_str = exam.get("last_attempt")
            if last_attempt_str:
                try:
                    last_attempt_date = datetime.strptime(last_attempt_str, "%Y-%m-%d %H:%M:%S").date()
                    if last_attempt_date >= start_date:
                        c_title = exam.get("course_title")
                        task_id = exam.get("task_id")
                        result = exam.get("result")
                        
                        node = get_course_node(c_title)
                        node["exams_attempts"] += 1
                        
                        if c_title not in course_exams:
                            course_exams[c_title] = {}
                        if task_id not in course_exams[c_title]:
                            course_exams[c_title][task_id] = []
                        course_exams[c_title][task_id].append(result)
                except ValueError:
                    continue

        for c_title, tasks in course_exams.items():
            node = get_course_node(c_title)
            node["exams"] = len(tasks)
            successful_exams = sum(1 for results in tasks.values() if any(r == 1 for r in results))
            node["exams_success"] = successful_exams
            node["success"] += successful_exams

    # 4. Task Stats (Time and Efforts)
    if stats_data and stats_data.get("status") == "ok":
        for task in stats_data.get("tasks_stats", []):
            task_date_str = task.get("date")
            if task_date_str:
                try:
                    task_date = datetime.strptime(task_date_str, "%Y-%m-%d").date()
                    if task_date >= start_date:
                        node = get_course_node(task.get("course_title"))
                        node["time"] += (task.get("time_spent") or 0)
                        node["efforts"] += (task.get("efforts") or 0)
                        node["tasks_count"] += 1
                        
                        is_solved = (task.get("result", 0) != 0)
                        node["puzzles_attempts"] += (1 if is_solved else 0) + (task.get("efforts") or 0)
                        
                        if is_solved:
                            node["solved_tasks_count"] += 1
                except ValueError:
                    continue

    return breakdown
