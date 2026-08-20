"""Representative Stack Exchange API v2.3 payloads. Not live responses."""

from __future__ import annotations

SO_QUESTION_ID = 123
DS_QUESTION_ID = 123
SO_QUESTION_B_ID = 456
SO_QUESTION_C_ID = 789

QUESTION_SO_A = {
    "question_id": SO_QUESTION_ID,
    "title": "How do I groupby in pandas?",
    "link": "https://stackoverflow.com/questions/123/how-do-i-groupby-in-pandas",
    "score": 12,
    "view_count": 400,
    "answer_count": 3,
    "creation_date": 1175714200,
    "last_activity_date": 1175800600,
    "tags": ["python", "pandas"],
    "is_answered": True,
    "accepted_answer_id": 999,
    "content_license": "CC BY-SA 4.0",
    "owner": {"user_id": 42, "display_name": "alice"},
}

QUESTION_DS_A = {
    "question_id": DS_QUESTION_ID,
    "title": "What is a training/validation split?",
    "link": "https://datascience.stackexchange.com/questions/123/what-is-a-training-validation-split",
    "score": 4,
    "view_count": 80,
    "answer_count": 1,
    "creation_date": 1175714300,
    "last_activity_date": 1175714300,
    "tags": ["machine-learning"],
    "is_answered": False,
    "owner": {"user_id": 7, "display_name": "bob"},
}

QUESTION_SO_B = {
    "question_id": SO_QUESTION_B_ID,
    "title": "SQL join types",
    "link": "https://stackoverflow.com/questions/456/sql-join-types",
    "score": 2,
    "view_count": 50,
    "answer_count": 0,
    "creation_date": 1175714400,
    "last_activity_date": 1175714400,
    "tags": ["sql"],
    "is_answered": False,
}

QUESTION_SO_C = {
    "question_id": SO_QUESTION_C_ID,
    "title": "No owner or accepted answer",
    "link": "https://stackoverflow.com/questions/789/no-owner",
    "score": 0,
    "view_count": 9,
    "answer_count": 0,
    "creation_date": 1175714500,
    "last_activity_date": 1175714500,
    "tags": ["python"],
    "is_answered": False,
}

QUESTION_MALFORMED_STATS = {
    "question_id": 321,
    "title": "Bad stats",
    "link": "https://stackoverflow.com/questions/321/bad-stats",
    "score": "not-a-number",
    "view_count": -4,
    "answer_count": 2,
    "creation_date": 1175714600,
    "last_activity_date": 1175714600,
    "tags": ["python"],
    "is_answered": True,
}

MISSING_ID_ITEM = {
    "title": "Missing identity",
    "score": 1,
}

QUESTIONS_PAGE_1 = {
    "items": [QUESTION_SO_A, QUESTION_SO_B],
    "has_more": True,
    "quota_max": 300,
    "quota_remaining": 299,
}

QUESTIONS_PAGE_2 = {
    "items": [QUESTION_SO_C],
    "has_more": False,
    "quota_max": 300,
    "quota_remaining": 298,
}

QUESTIONS_EMPTY = {
    "items": [],
    "has_more": False,
    "quota_max": 300,
    "quota_remaining": 297,
}

QUESTIONS_WITH_BACKOFF = {
    "items": [QUESTION_SO_A],
    "has_more": True,
    "backoff": 5,
    "quota_max": 300,
    "quota_remaining": 296,
}

QUESTIONS_MALFORMED = {"items": "not-a-list"}

API_ERROR = {
    "error_id": 400,
    "error_message": "site is required",
    "error_name": "bad_parameter",
}
