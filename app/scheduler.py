from flask_apscheduler import APScheduler
from app.models import Settings, Performer
from app.scraper import scrape_performer
from app.routes import db # Need app context

scheduler = APScheduler()

def scheduled_scan():
    with scheduler.app.app_context():
        print("Starting scheduled scan...")
        from app.services import scan_performer_service
        
        performers = Performer.query.filter_by(scheduled_scan_enabled=True).all()
        total_new = 0
        
        for performer in performers:
            try:
                result = scan_performer_service(performer)
                total_new += result['new_count']
            except Exception as e:
                print(f"Error scanning {performer.name}: {e}")
        
        if total_new > 0:
            from app.notifications import send_telegram_message
            send_telegram_message(f"<b>Scheduled Scan Completed</b>\nFound {total_new} new videos.")

def auto_update_ytdlp():
    import subprocess
    from datetime import datetime
    from app import create_app, db
    from app.models import Settings
    
    from app.models import Settings
    
    app = create_app(with_scheduler=False)
    with app.app_context():
        try:
            print("Starting auto-update of yt-dlp...")
            subprocess.run(['uv', 'pip', 'install', '-U', 'yt-dlp'], check=True)
            
            s_last = Settings.query.filter_by(key='yt_dlp_last_updated').first() or Settings(key='yt_dlp_last_updated')
            s_last.value = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.session.add(s_last)
            db.session.commit()
            
            print("yt-dlp auto-updated successfully.")
        except Exception as e:
            print(f"Error auto-updating yt-dlp: {e}")

def init_scheduler(app):
    # Default config
    app.config['SCHEDULER_API_ENABLED'] = True
    
    scheduler.init_app(app)
    
    if not scheduler.running:
        scheduler.start()
    
    # Add job if not exists (or update)
    # For simplicity, we'll add a default job that runs every hour, but checks if it should run
    try:
        scheduler.add_job(id='scheduled_scan', func=scheduled_scan, trigger='interval', minutes=60, replace_existing=True)
    except Exception:
        pass # Job might already exist or scheduler issue
