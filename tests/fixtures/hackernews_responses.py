"""Representative Hacker News Firebase API payloads. Not live responses."""

from __future__ import annotations

STORY_A_ID = 1001
STORY_B_ID = 1002
STORY_C_ID = 1003
MISSING_ID = 1099
DELETED_ID = 1098
DEAD_ID = 1097
COMMENT_ID = 1096

TOPSTORIES_IDS = [STORY_A_ID, STORY_B_ID, STORY_C_ID, 1004, 1005]
NEWSTORIES_IDS = [STORY_B_ID, 1010]
BESTSTORIES_IDS = [STORY_A_ID, STORY_C_ID]

STORY_A = {
    "id": STORY_A_ID,
    "type": "story",
    "by": "alice",
    "time": 1175714200,
    "title": "Example AI education tool",
    "url": "https://example.com/ai-edu",
    "score": 120,
    "descendants": 15,
    "kids": [2001, 2002],
}

STORY_B = {
    "id": STORY_B_ID,
    "type": "story",
    "by": "bob",
    "time": 1175714300,
    "title": "Text-only story",
    "text": "Ask HN: how do you teach Python?",
    "score": 8,
    "descendants": 0,
}

STORY_C = {
    "id": STORY_C_ID,
    "type": "story",
    "by": "carol",
    "time": 1175714400,
    "title": "Score only",
    "url": "https://example.com/score-only",
    "score": 3,
}

DELETED_ITEM = {
    "id": DELETED_ID,
    "type": "story",
    "deleted": True,
}

DEAD_ITEM = {
    "id": DEAD_ID,
    "type": "story",
    "dead": True,
    "title": "Removed story",
    "by": "gone",
}

COMMENT_ITEM = {
    "id": COMMENT_ID,
    "type": "comment",
    "by": "dave",
    "time": 1175714500,
    "text": "A comment, not a story",
    "parent": STORY_A_ID,
}

MALFORMED_FEED = {"error": "not-a-list"}
MALFORMED_ITEM = ["not", "an", "object"]
