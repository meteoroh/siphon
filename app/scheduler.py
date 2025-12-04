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
        auto_download_count = 0
        
        from app.tasks import start_task
        from app.downloader import download_video
        
        for performer in performers:
            try:
                result = scan_performer_service(performer)
                total_new += result['new_count']
                
                # Trigger Auto-Download
                if performer.auto_download and result.get('new_video_ids'):
                    print(f"Triggering auto-download for {performer.name} ({len(result['new_video_ids'])} videos)...")
                    for vid_id in result['new_video_ids']:
                        # Double check status to be safe (though service should filter)
                        # We can't easily check DB here without re-querying, but the ID is fresh.
                        # Just fire the task.
                        start_task(download_video, vid_id, trigger_autotag=True)
                        auto_download_count += 1
                        
            except Exception as e:
                print(f"Error scanning {performer.name}: {e}")
        
        if total_new > 0:
            from app.notifications import send_telegram_message
            msg = f"<b>Scheduled Scan Completed</b>\nFound {total_new} new videos."
            if auto_download_count > 0:
                msg += f"\nStarted {auto_download_count} automatic downloads."
            send_telegram_message(msg)

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
            # Update and sync in one go
            subprocess.run(['uv', 'sync', '--upgrade-package', 'yt-dlp'], check=True)
            
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
    
    # Add job based on saved settings
    with app.app_context():
        try:
            interval_setting = Settings.query.filter_by(key='schedule_interval').first()
            interval = int(interval_setting.value) if interval_setting and interval_setting.value.isdigit() else 60
            
            if interval > 0:
                scheduler.add_job(id='scheduled_scan', func=scheduled_scan, trigger='interval', minutes=interval, replace_existing=True)
            else:
                # Ensure job is removed if interval is 0 (in case of persistent job store)
                try:
                    scheduler.remove_job('scheduled_scan')
                except Exception:
                    pass
        except Exception as e:
            print(f"Error initializing scheduler job: {e}")
