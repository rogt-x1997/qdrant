import streamlit as st
from qdrant_client import QdrantClient
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
import logging
from twilio.rest import Client
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
import time

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = None

EMAIL_CONFIG = {
   'to': "morande.swapnil@outlook.com", 
   'from': os.getenv("EMAIL_FROM"),
   'password': os.getenv("EMAIL_PASSWORD"),
   'smtp_server': "smtp.office365.com",
   'smtp_port': 587
}

TWILIO_CONFIG = {
   'account_sid': os.getenv("TWILIO_ACCOUNT_SID"),
   'auth_token': os.getenv("TWILIO_AUTH_TOKEN"),
   'from_number': os.getenv("TWILIO_FROM_NUMBER"),
   'to_number': os.getenv("TWILIO_TO_NUMBER")
}

if 'last_check_time' not in st.session_state:
   st.session_state.last_check_time = None
if 'health_history' not in st.session_state:
   st.session_state.health_history = []
if 'response_times' not in st.session_state:
   st.session_state.response_times = []

@st.cache_resource
def get_qdrant_client():
   return QdrantClient(
       url=QDRANT_HOST,
       api_key=QDRANT_API_KEY,
       timeout=10.0
   )

def list_collections():
    try:
        client = get_qdrant_client()
        collections = client.get_collections()
        return [col.name for col in collections.collections]
    except Exception as e:
        logger.error(f"Failed to list collections: {str(e)}")
        return []

def send_email_alert(status: str, details: str):
   try:
       msg = MIMEMultipart()
       msg['From'] = EMAIL_CONFIG['from']
       msg['To'] = EMAIL_CONFIG['to']
       msg['Subject'] = f"Qdrant Monitor Alert - {status}"
       msg.attach(MIMEText(details, 'plain'))
       
       with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
           server.starttls()
           server.login(EMAIL_CONFIG['from'], EMAIL_CONFIG['password'])
           server.send_message(msg)
       return True
   except Exception as e:
       st.error(f"Failed to send email: {str(e)}")
       return False

def send_sms_alert(message: str):
   try:
       client = Client(TWILIO_CONFIG['account_sid'], TWILIO_CONFIG['auth_token'])
       client.messages.create(
           body=message,
           from_=TWILIO_CONFIG['from_number'],
           to=TWILIO_CONFIG['to_number']
       )
       return True
   except Exception as e:
       st.error(f"Failed to send SMS: {str(e)}")
       return False

def check_api_health(collection_name):
    start_time = time.time()
    try:
        client = get_qdrant_client()
        # First check if collection exists
        collections = client.get_collections()
        if collection_name not in [col.name for col in collections.collections]:
            return False, f"Collection '{collection_name}' not found", None
            
        # Try to get basic collection info without detailed config
        try:
            collection_info = client.get_collection(collection_name)
            response_time = (time.time() - start_time) * 1000
            
            # Extract only necessary info to avoid validation errors
            safe_info = {
                "name": collection_info.name,
                "status": "green",
                "vectors_count": collection_info.vectors_count,
                "points_count": collection_info.points_count,
                "segments_count": collection_info.segments_count
            }
            return True, safe_info, response_time
        except Exception as collection_error:
            logger.error(f"Collection info error: {str(collection_error)}")
            return False, f"Failed to get collection info: {str(collection_error)}", None
            
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        return False, f"Failed to connect to Qdrant: {str(e)}", None

def update_metrics(status: bool, response_time: float = None):
   now = datetime.now()
   st.session_state.last_check_time = now
   st.session_state.health_history.append((now, status))
   if response_time:
       st.session_state.response_times.append((now, response_time))
   
   cutoff = now - timedelta(hours=24)
   st.session_state.health_history = [(t, s) for t, s in st.session_state.health_history if t > cutoff]
   st.session_state.response_times = [(t, r) for t, r in st.session_state.response_times if t > cutoff]

def main():
   st.set_page_config(
       page_title="Qdrant Monitor",
       page_icon="🔍",
       layout="wide",
       initial_sidebar_state="expanded"
   )

   st.markdown("""
       <style>
       .main-header {
           font-size: 2.5rem;
           font-weight: bold;
           color: #1E88E5;
           text-align: center;
           margin-bottom: 2rem;
       }
       </style>
       <div class="main-header">🔍 Qdrant API Monitor</div>
   """, unsafe_allow_html=True)
   
   st.sidebar.header("⚙️ Settings")
   
   collections = list_collections()
   if not collections:
       st.error("⚠️ Failed to fetch collections. Please check your Qdrant connection settings.")
       return

   selected_collection = st.sidebar.selectbox(
       "Select Collection",
       collections,
       index=0 if collections else None
   )
   
   refresh_interval = st.sidebar.slider(
       "Auto Refresh Interval (seconds)",
       min_value=30,
       max_value=300,
       value=60,
       step=30
   )
   
   alert_threshold = st.sidebar.number_input(
       "Response Time Alert Threshold (ms)",
       min_value=100,
       max_value=1000,
       value=500
   )
   
   col1, col2 = st.columns(2)
   
   with col1:
       st.subheader("📊 API Status")
       check_button = st.button("🔄 Check Now")
       
       if check_button or (
           st.session_state.last_check_time is None or 
           (datetime.now() - st.session_state.last_check_time).seconds >= refresh_interval
       ):
           with st.spinner("Checking API status..."):
               status, details, response_time = check_api_health(selected_collection)
               update_metrics(status, response_time)
               
               if status:
                   st.success("✅ API is healthy")
                   st.metric("Response Time", f"{response_time:.2f} ms")
                   if response_time > alert_threshold:
                       st.warning(f"⚠️ Response time above threshold ({alert_threshold} ms)")
                   with st.expander("Details"):
                       st.json(details)
               else:
                   st.error(f"❌ API is down: {details}")
                   if st.button("🚨 Send Alerts"):
                       email_sent = send_email_alert("API Down", str(details))
                       sms_sent = send_sms_alert(f"Qdrant API is down: {str(details)[:100]}...")
                       
                       if email_sent:
                           st.success("📧 Email alert sent")
                       if sms_sent:
                           st.success("📱 SMS alert sent")
   
   with col2:
       st.subheader("📈 Performance Metrics")
       if st.session_state.response_times:
           df = pd.DataFrame(
               st.session_state.response_times,
               columns=['timestamp', 'response_time']
           ).set_index('timestamp')
           
           fig = go.Figure()
           fig.add_trace(go.Scatter(
               x=df.index,
               y=df['response_time'],
               mode='lines+markers',
               name='Response Time',
               line=dict(color='#1E88E5')
           ))
           
           fig.update_layout(
               title="API Response Time Trend",
               xaxis_title="Time",
               yaxis_title="Response Time (ms)",
               height=400,
               template="plotly_white"
           )
           
           fig.add_hline(
               y=alert_threshold,
               line_dash="dash",
               line_color="red",
               annotation_text="Alert Threshold"
           )
           
           st.plotly_chart(fig, use_container_width=True)
           
           col_stats1, col_stats2 = st.columns(2)
           with col_stats1:
               st.metric(
                   "Average Response Time",
                   f"{df['response_time'].mean():.2f} ms"
               )
           with col_stats2:
               st.metric(
                   "Max Response Time",
                   f"{df['response_time'].max():.2f} ms"
               )
       else:
           st.info("Waiting for performance data...")
   
   st.subheader("📋 Health History")
   if st.session_state.health_history:
       history_df = pd.DataFrame(
           st.session_state.health_history,
           columns=['timestamp', 'status']
       ).set_index('timestamp')
       
       uptime = (history_df['status'].sum() / len(history_df)) * 100
       st.metric("Uptime (24h)", f"{uptime:.2f}%")
       
       st.dataframe(
           history_df.tail(10).style.applymap(
               lambda x: 'background-color: #90EE90' if x else 'background-color: #FFB6C6'
           )
       )
   else:
       st.info("No health history available yet...")

if __name__ == "__main__":
   main()