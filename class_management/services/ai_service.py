import os
import json
from google import genai
from django.conf import settings
from .models import Announcement, GroupSet, StudentFeedback

def get_gemini_client():
    api_key = getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY')
    return genai.Client(api_key=api_key)

def query_class_ai(user, prompt, history=None):
    """
    Executes permission-aware AI query over ASMS context with Google Gemini 3.7 Flash.
    """
    client = get_gemini_client()
    
    # Construct Authoritative Context from ORM
    user_context = f"User: {user.get_full_name()} | Role: {user.role}\n"
    
    system_instruction = f"""
You are the official ASMS (Academic School Management System) Class Management AI Assistant.
You assist university students, class representatives, lecturers, and administrators with university academics, timetable schedules, course materials, announcements, study groups, attendance, and polls.

POLICIES:
1. PERMISSION-AWARE & PRIVATE: Only use the authoritative context provided. Never reveal private information of other students.
2. CITATION & ACCURACY: Answer precisely with correct venues, course codes, timetable slots, group members, and session codes.
3. TONE: Courteous, academic, concise, and structured.

USER IDENTITY:
{user_context}
"""

    contents = []
    if history:
        for msg in history:
            role = 'user' if msg.get('sender') == 'user' else 'model'
            contents.append({'role': role, 'parts': [{'text': msg.get('text', '')}]})
            
    contents.append({'role': 'user', 'parts': [{'text': prompt}]})

    response = client.models.generate_content(
        model='gemini-3.7-flash',
        contents=contents,
        config={
            'system_instruction': system_instruction,
            'temperature': 0.7,
        }
    )
    return response.text or 'No response generated.'


def ai_draft_announcement(raw_notes, subject_code='General', urgency='NORMAL'):
    """
    Enhances raw notes from class reps into institutional announcements.
    """
    client = get_gemini_client()
    prompt = f"""
Turn these raw notes from a university class representative into a formal, clear university announcement:
Raw notes: "{raw_notes}"
Course/Subject: {subject_code}
Urgency: {urgency}

Format your output as:
TITLE: <Clear concise title>
CONTENT: <Polite, professional announcement body with bullet points for key details (Date, Time, Venue, Action Required)>
"""
    response = client.models.generate_content(
        model='gemini-3.7-flash',
        contents=prompt,
        config={'temperature': 0.5}
    )
    text = response.text or ''
    
    import re
    title_match = re.search(r'TITLE:\s*(.+)', text, re.IGNORECASE)
    content_match = re.search(r'CONTENT:\s*([\s\S]+)', text, re.IGNORECASE)
    
    return {
        'title': title_match.group(1).strip() if title_match else 'Class Notice',
        'content': content_match.group(1).strip() if content_match else text
    }


def ai_summarize_feedback():
    """
    Synthesizes all student feedback into an executive briefing.
    """
    client = get_gemini_client()
    feedbacks = list(StudentFeedback.objects.values('category', 'title', 'message', 'status'))
    
    prompt = f"""
Analyze and summarize the following anonymous student feedback for the university academic department:
{json.dumps(feedbacks, default=str)}

Provide a structured briefing report:
1. Executive Summary
2. Top Common Complaints & Academic Bottlenecks
3. Positive Highlights & Commendations
4. Recommended Concrete Action Steps for Lecturers & Class Reps
"""
    response = client.models.generate_content(
        model='gemini-3.7-flash',
        contents=prompt,
        config={'temperature': 0.4}
    )
    return response.text
