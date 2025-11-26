import requests
from app.models import Settings

def send_telegram_message(message):
    token = Settings.query.filter_by(key='telegram_token').first()
    chat_id = Settings.query.filter_by(key='telegram_chat_id').first()
    
    if not token or not chat_id or not token.value or not chat_id.value:
        return False, "Telegram settings not configured."
        
    url = f"https://api.telegram.org/bot{token.value}/sendMessage"
    payload = {
        'chat_id': chat_id.value,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True, "Message sent successfully."
    except Exception as e:
        return False, str(e)
