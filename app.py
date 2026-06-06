import streamlit as tv
import sqlite3
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime
from dateutil import parser 
import pytz 
import json
import re
from dotenv import load_dotenv

def uni_data():
    conn = sqlite3.connect('timetable.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM classes")
    rows = cursor.fetchall()
    conn.close()
    return rows

def google_calend():
    if Path('token.json').exists():
        try:
            creds = Credentials.from_authorized_user_file('token.json')
            work = build('calendar', 'v3', credentials=creds)
            now = datetime.datetime.utcnow().isoformat() + 'Z'
            events_info = work.events().list(
                calendarId='primary',
                timeMin=now,
                maxResults=30,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            return events_info.get('items', [])
        except Exception as e:
            print(f"Network/Server Error: {e}")
            return []
    return []
 
# --- FEATURE BLOCK: CALENDAR CRUD OPERATIONS ---
def add(summary, start_time):
    try:
        creds = Credentials.from_authorized_user_file('token.json')
        work = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': summary,
            'start': {'dateTime': parser.parse(start_time).isoformat(), 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': (parser.parse(start_time) + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'Asia/Kolkata'},
        }
        work.events().insert(calendarId='primary', body=event).execute()
        return True
    except Exception as e:
        print(f"Add error: {e}")
        return False

def delete_event(title):
    try:
        creds = Credentials.from_authorized_user_file('token.json')
        work = build('calendar', 'v3', credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        
        events_info = work.events().list(
            calendarId='primary',
            q=title,
            timeMin=now,
            maxResults=10
        ).execute()
        events = events_info.get('items', [])
        
        if not events:
            return False
            
        work.events().delete(calendarId='primary', eventId=events[0]['id']).execute()
        return True
    except Exception as e:
        print(f"Delete error: {e}")
        return False

events = google_calend()

with tv.sidebar:
    now_ist = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
    tv.title("SMART TIMETABLE ASSISTANT")
    tv.caption(now_ist.strftime("%A, %d %b %Y"))
    tv.write("---")

    section = tv.radio("Select Section", [
        "🏫 College Timetable",
        "📆 Google Events",
    ])
    tv.write("---")

    if section == "🏫 College Timetable":
        data = uni_data()
        for row in data:
            tv.info(f"**{row[0]}**\n\n📅 {row[1]} | ⏰ {row[2]} - {row[3]}")

    elif section == "📆 Google Events":
        if tv.button("🔄 Sync"):
            tv.session_state.calendar_events = google_calend()
            tv.rerun()
        if not events:
            tv.warning("NO EVENTS SCHEDULED")
        else:
            for e in events:
                name = e.get('summary', 'No Title')
                full_time = e.get('start', {}).get('dateTime')
                if full_time:
                    ist_time = parser.parse(full_time).astimezone(pytz.timezone("Asia/Kolkata"))
                    clean = ist_time.strftime("%d %b %Y | %I:%M %p")
                else:
                    clean = "All Day"
                tv.success(f"**{name}**\n\n {clean}") 

tv.write("-----------------")
tv.header("😎 Assistant:")
api_key = tv.secrets["GEMINI_API_KEY"]
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=api_key
)

user_input = tv.chat_input("chat")

if user_input:
    with tv.spinner("wait.."):
        database = uni_data()      
        events = google_calend()
        context = "you are a chill intelligent friendly assistant for students. Use 'dear' and be concise."

        formatted_events = []
        for e in events:
            summary = e.get('summary', 'Untitled Event')
            start = e.get('start', {}).get('dateTime') or e.get('start', {}).get('date', 'All Day')
            end = e.get('end', {}).get('dateTime') or e.get('end', {}).get('date', 'All Day')
            formatted_events.append(f"- Event: '{summary}' from {start} to {end}")
        brain = f"""
        COLLEGE CLASSES (from SQLite):
        {database}

        PERSONAL EVENTS (from Google):
        {events}
        """
        current_now = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        prompt = f"""
        System: {context}
        Bhai, here is my Master Schedule:
        Current Time: {current_now.strftime("%Y-%m-%d %H:%M:%S")}
        Location: India (IST)
        {brain}

        The user asked: {user_input}
        
        CRITICAL STEP - CLASH CHECK WITH LOCATION:
        Before adding any event, deeply analyze if the requested time overlaps with:
        1. COLLEGE CLASSES (from SQLite Database)
        2. PERSONAL EVENTS (from Google Calendar)
        
        NOTE ON FREE SLOTS: If a college class session is explicitly named "Free lecture", "Free", or "Library", do NOT consider it a clash. Treat it as a free slot and allow the event to be added.
        
        RULE 1 (NO CLASH): If there is ABSOLUTELY NO clash (or if the overlap is only with a "Free" or "Library" slot), respond ONLY with a valid JSON array of objects wrapped in `[]`. No extra text, no markdown.
        Example:
        [
          {{"action": "add", "title": "meeting", "time": "2026-06-05T19:00:00"}}
        ]

        RULE 2 (CLASH DETECTED): If there is a real clash with a mandatory class or calendar event, DO NOT SEND JSON. 
        Instead, reply naturally in Hindi/English as a protective friend. You must explicitly mention the LOCATION of the clash.
        - If it clashes with a mandatory class, say: "Bro, at that time you have your [Class Name] class in the timetable"
        - If it clashes with a calendar event, say: "Bro, at that time [Event Name] is already scheduled in your Google Calendar."
        In both cases, suggest a free time slot based on the context.
        
        RULE 3 (DELETE): If user asks to delete an event, respond with this JSON format inside the list:
        [ {{"action": "delete", "title": "event name to delete"}} ]
        """
        try:
            raw_response = llm.invoke(prompt)
            responsee = raw_response.content
        except Exception as api_err:
            responsee = "api issue."
            tv.error(f"API Error: {api_err}")

        # --- OPTIMIZED REGEX EXTRACTION ENGINE ---
        # Isolates pure structured configurations, discarding outer formatting anomalies
        json_match = re.search(r'\[\s*\{.*\}\s*\]', responsee, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{.*\}', responsee, re.DOTALL)

        if json_match:
            try:
                clean_json = json_match.group(0).strip()
                data = json.loads(clean_json)
                
                if not isinstance(data, list):
                    actions_list = [data]
                else:
                    actions_list = data
                
                success_count = 0
                for item in actions_list:
                    action = item.get('action', '')
                    
                    if action == 'add':
                        if add(item['title'], item['time']):
                            success_count += 1
              
                    elif action == 'delete':
                        if delete_event(item['title']):
                            success_count += 1
                
                if success_count > 0:
                    tv.success(f"✅ Done bro.")
                    import time
                    time.sleep(2)
                    tv.rerun()
                else:
                    tv.error("task not initiated")
                        
            except Exception as e:
                tv.error(f"JSON Parsing Error: {e}")
        else:
            with tv.chat_message("assistant"):
                tv.write(responsee)