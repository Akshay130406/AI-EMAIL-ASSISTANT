import os
import base64
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.generativeai as genai
from dotenv import load_dotenv
from email.message import EmailMessage

# 1. INITIAL SETUP
load_dotenv('libraries.env') 
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ Error: Missing GOOGLE_API_KEY in libraries.env")
else:
    genai.configure(api_key=api_key)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

def authenticate():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def send_reply(service, recipient, subject, body_text):
    message = EmailMessage()
    # Adding a professional signature
    signature = "\n\nRegards,\nAkshay (AI Assistant)"
    disclaimer = "\n\n---\n*Sent via Smart AI Automator*"
    
    message.set_content(body_text + signature + disclaimer)
    message['To'] = recipient
    
    # Clean subject to prevent long "Re: Re: Re:" chains
    clean_subject = subject.replace("Re: ", "").replace("re: ", "").strip()
    message['Subject'] = f"Re: {clean_subject}"
    
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    
    try:
        service.users().messages().send(userId="me", body={'raw': encoded_message}).execute()
        print(f"✅ AI Response sent to {recipient}")
    except Exception as e:
        print(f"❌ Error sending email: {e}")

def main():
    creds = authenticate()
    gmail = build('gmail', 'v1', credentials=creds)
    
    # Using the latest stable model
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    print("🔍 Scanning for unread emails...")
    
    results = gmail.users().messages().list(userId='me', q='is:unread').execute()
    messages = results.get('messages', [])

    if not messages:
        print("📭 Inbox is empty (no unread messages).")
        return

    for m in messages:
        msg = gmail.users().messages().get(userId='me', id=m['id']).execute()
        headers = msg['payload']['headers']
        
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
        snippet = msg.get('snippet', '')

        print(f"\n📑 Analyzing: {subject}")

        # Step 1: Triage (Intent Identification)
        triage_prompt = (
            f"Subject: {subject}. Body snippet: {snippet}. "
            "Task: Is this an update request? Reply ONLY 'UPDATE' or 'IGNORE'."
        )
        
        try:
            intent_response = model.generate_content(triage_prompt)
            intent = intent_response.text.strip().upper()

            if "UPDATE" in intent:
                # Step 2: Context-Aware Generation
                # Note: In app.py, this will be replaced by the dynamic sidebar input
                context = "I am Akshay. I have reviewed 37 research papers and am working on a Smart Medicine Reminder."
                
                reply_prompt = (
                    f"Context: {context}. Email: {snippet}. "
                    "Draft a professional 2-sentence reply based on the context."
                )
                
                reply_gen = model.generate_content(reply_prompt).text
                
                # Step 3: Action
                send_reply(gmail, sender, subject, reply_gen)
                
                # Mark as read
                gmail.users().messages().batchModify(
                    userId='me', 
                    body={'ids': [m['id']], 'removeLabelIds': ['UNREAD']}
                ).execute()
            else:
                print(f"⏭️ Action: {intent} - No reply needed.")
        
        except Exception as ai_err:
            print(f"⚠️ AI Error: {ai_err}")

if __name__ == "__main__":
    main()