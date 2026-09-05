import streamlit as st
import pandas as pd
import os
import time
from dotenv import load_dotenv
import google.generativeai as genai
from googleapiclient.discovery import build
from main import authenticate, send_reply

# 1. SETUP
load_dotenv('libraries.env')
api_key = os.getenv("GOOGLE_API_KEY")

if 'logs' not in st.session_state:
    st.session_state.logs = []

# 2. BEAUTIFUL UI CONFIG
st.set_page_config(page_title="AI Email Assistant", page_icon="🚀", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        background-color: #FF4B4B;
        color: white;
        font-weight: bold;
    }
    .stMetric {
        background-color: #1e2130;
        padding: 15px;
        border-radius: 15px;
    }
    </style>
    """, unsafe_allow_html=True)

# 3. HEADER & STATS
st.title("🤖 AI Email Assistant")
st.markdown("---")

col1, col2, col3 = st.columns(3)
col1.metric("Status", "Active", "Online")
col2.metric("Emails Processed", len(st.session_state.logs))
col3.metric("AI Model", "Gemini 2.5 Flash")

# 4. SIDEBAR
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=100)
st.sidebar.header("User Knowledge Base")
user_context = st.sidebar.text_area(
    "Your Current Context:", 
    value="Not available for 3 days",
    height=200
)

# 5. TABS
tab1, tab2 = st.tabs(["🚀 Control Center", "📜 Audit Logs"])

with tab1:
    st.subheader("Automated Inbox Management")
    
    if st.button("✨ Run Smart Inbox Scan"):
        # Configure AI
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') 
        
        with st.status("Initializing AI Engine...", expanded=True) as status_box:
            try:
                creds = authenticate()
                gmail = build('gmail', 'v1', credentials=creds)
                
                # Fetch unread emails
                results = gmail.users().messages().list(userId='me', q='is:unread').execute()
                messages = results.get('messages', [])

                if not messages:
                    st.success("Inbox is pristine! No new emails.")
                else:
                    for i, m in enumerate(messages):
                        # RATE LIMIT PROTECTION: Wait 12 seconds between emails to stay within 5/min limit
                        if i > 0:
                            time.sleep(12)
                            
                        msg = gmail.users().messages().get(userId='me', id=m['id']).execute()
                        headers = msg['payload']['headers']
                        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                        sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                        snippet = msg.get('snippet', '')
                        
                        # AI Action
                        prompt = f"Context: {user_context}. Email: {snippet}. Draft a professional 2-sentence update."
                        response = model.generate_content(prompt).text
                        
                        # EXECUTION: This sends the email to your Gmail Sent folder
                        send_reply(gmail, sender, subject, response)
                        
                        # LOGGING
                        st.session_state.logs.append({
                            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
                            "Subject": subject,
                            "Status": "✅ Replied"
                        })
                        
                        st.info(f"🔍 Handled: **{subject}**")
                
                status_box.update(label="Scan Complete!", state="complete", expanded=False)
                st.rerun() 
                
            except Exception as e:
                st.error(f"Error: {e}")

with tab2:
    st.subheader("Project History")
    if not st.session_state.logs:
        st.info("No activity recorded in this session.")
    else:
        df = pd.DataFrame(st.session_state.logs)
        st.dataframe(df.iloc[::-1], use_container_width=True) 
        
        if st.button("🗑️ Clear Activity History"):
            st.session_state.logs = []
            st.rerun()