"""plugins/utility_life.py — 🌱 LIFE tools: Notes, Habit Tracker,
Expense Tracker, Bookmark Manager, Contacts, Calendar, Flashcard Maker,
Quiz Maker, Poll Maker, Dictionary. Thin voice wrapper over
core/utility_tools.py. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_life",
    "description": (
        "Life tools — notes, habit tracker (streak), expense tracker, "
        "bookmark manager, contacts, calendar events, flashcard maker + "
        "quiz, quiz maker, poll maker + vote, dictionary. Call when the "
        "user says: note koro, habit banao, kharcha likho, bookmark koro, "
        "contact save koro, event likho, flashcard banao, quiz banao, poll "
        "banao, shobder mane ki."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "note_add | note_list | habit_add | habit_tick | habit_status | expense_add | expense_summary | bookmark_add | bookmark_list | contact_add | contact_find | calendar_add | calendar_today | flashcard_add | flashcard_quiz | quiz | poll_make | poll_vote | dictionary"},
            "text": {"type": "STRING", "description": "Note text / poll question / quiz topic."},
            "name": {"type": "STRING", "description": "Habit / contact / event name."},
            "amount": {"type": "NUMBER", "description": "Expense amount."},
            "what": {"type": "STRING", "description": "What the expense was for."},
            "category": {"type": "STRING", "description": "Expense category."},
            "url": {"type": "STRING", "description": "Bookmark URL."},
            "title": {"type": "STRING", "description": "Bookmark / event title."},
            "phone": {"type": "STRING", "description": "Contact phone."},
            "email": {"type": "STRING", "description": "Contact email."},
            "when": {"type": "STRING", "description": "Event time, e.g. 2026-11-20 15:00."},
            "question": {"type": "STRING", "description": "Flashcard question."},
            "answer": {"type": "STRING", "description": "Flashcard answer."},
            "options": {"type": "STRING", "description": "Poll options, comma-separated."},
            "index": {"type": "NUMBER", "description": "Poll option number to vote for."},
            "word": {"type": "STRING", "description": "Word to look up."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "note_add":
            return u.note_add(str(p.get("text") or ""))
        if action == "note_list":
            return u.note_list()
        if action == "habit_add":
            return u.habit_add(str(p.get("name") or ""))
        if action == "habit_tick":
            return u.habit_tick(str(p.get("name") or ""))
        if action == "habit_status":
            return u.habit_status()
        if action == "expense_add":
            return u.expense_add(float(p.get("amount") or 0),
                                 str(p.get("what") or ""),
                                 str(p.get("category") or ""))
        if action == "expense_summary":
            return u.expense_summary()
        if action == "bookmark_add":
            return u.bookmark_add(str(p.get("url") or ""),
                                  str(p.get("title") or ""))
        if action == "bookmark_list":
            return u.bookmark_list()
        if action == "contact_add":
            return u.contact_add(str(p.get("name") or ""),
                                 str(p.get("phone") or ""),
                                 str(p.get("email") or ""))
        if action == "contact_find":
            return u.contact_find(str(p.get("name") or ""))
        if action == "calendar_add":
            return u.calendar_add(str(p.get("title") or ""),
                                  str(p.get("when") or ""))
        if action == "calendar_today":
            return u.calendar_today()
        if action == "flashcard_add":
            return u.flashcard_add(str(p.get("question") or ""),
                                   str(p.get("answer") or ""))
        if action == "flashcard_quiz":
            return u.flashcard_quiz()
        if action == "quiz":
            return u.quiz_make(str(p.get("text") or ""), 3)
        if action == "poll_make":
            return u.poll_make(str(p.get("text") or ""),
                               str(p.get("options") or ""))
        if action == "poll_vote":
            return u.poll_vote(int(p.get("index") or 1))
        if action == "dictionary":
            return u.dictionary_lookup(str(p.get("word") or ""))
        return u.note_list()
    except Exception as e:
        return f"Life tool chalate parlam na: {e}"
