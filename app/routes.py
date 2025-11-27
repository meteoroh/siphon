from flask import Blueprint, render_template, request, jsonify
from datetime import datetime
from app.models import Performer, Video, db
from app.scraper import scrape_performer
from app.downloader import download_video
from app.downloader import download_video
import os

main = Blueprint('main', __name__)
main = Blueprint('main', __name__)

def run_scan_task(task_id, performer_id):
    from app import create_app
    app = create_app(with_scheduler=False)
    
    with app.app_context():
        from app.models import Performer
        from app.services import scan_performer_service
        from app.tasks import update_task_progress
        
        performer = Performer.query.get(performer_id)
        if not performer:
            update_task_progress(task_id, message="Performer not found", status="failed")
            return
            
        result = scan_performer_service(performer, task_id)
        

        return result

@main.route('/scan/<performer_id>', methods=['POST'])
def scan_performer(performer_id):
    from app.tasks import start_task
    task_id = start_task(run_scan_task, performer_id)
    return render_template('components/progress_bar.html', task_id=task_id, message="Initializing scan...", progress=0)

@main.route('/')
def index():
    performers = Performer.query.all()
    return render_template('index.html', performers=performers)

@main.route('/performers', methods=['GET', 'POST'])
def performers():
    if request.method == 'POST':
        name = request.form.get('name')
        p_id = request.form.get('id')
        site = request.form.get('site')
        p_type = request.form.get('type')
        
        if Performer.query.get(p_id):
            return "Performer ID already exists", 400
            
        performer = Performer(id=p_id, name=name, site=site, type=p_type)
        db.session.add(performer)
        db.session.commit()
        
        # Return partial HTML for HTMX
        # Return row HTML for HTMX
        return render_template('components/performer_row.html', performer=performer)

    performers_query = Performer.query
    search_query = request.args.get('q')
    if search_query:
        performers_query = performers_query.filter(Performer.name.ilike(f'%{search_query}%'))
    
    performers = performers_query.all()
    return render_template('index.html', performers=performers)

@main.route('/performers/<performer_id>')
def performer_details(performer_id):
    performer = Performer.query.get_or_404(performer_id)
    # Include all videos (new, downloaded, ignored)
    videos = performer.videos.order_by(Video.created_at.desc()).all()
    return render_template('performer.html', performer=performer, videos=videos)

@main.route('/performers/<performer_id>/settings', methods=['POST'])
def update_performer_settings(performer_id):
    performer = Performer.query.get_or_404(performer_id)
    performer.blacklist_keywords = request.form.get('blacklist_keywords')
    performer.whitelist_keywords = request.form.get('whitelist_keywords')
    performer.scheduled_scan_enabled = 'scheduled_scan_enabled' in request.form
    db.session.commit()
    return "<div class='alert alert-success'>Settings saved!</div>"


@main.route('/videos/<int:video_id>/unignore', methods=['POST'])
def unignore_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.status = 'new'
    db.session.commit()
    return render_template('components/video_row.html', video=video)

@main.route('/videos/<int:video_id>/ignore', methods=['POST'])
def ignore_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.status = 'ignored'
    db.session.commit()
    return render_template('components/video_row.html', video=video)

@main.route('/performers/<performer_id>/edit', methods=['POST'])
def edit_performer(performer_id):
    performer = Performer.query.get_or_404(performer_id)
    performer.name = request.form.get('name')
    performer.site = request.form.get('site')
    performer.type = request.form.get('type')
    db.session.commit()
    return "OK"

@main.route('/performers/<performer_id>/delete', methods=['DELETE'])
def delete_performer(performer_id):
    performer = Performer.query.get_or_404(performer_id)
    # Delete associated videos first (cascade should handle this but explicit is safer with SQLite sometimes)
    Video.query.filter_by(performer_id=performer.id).delete()
    db.session.delete(performer)
    db.session.commit()
    return ""

@main.route('/download/batch', methods=['POST'])
def download_batch():
    video_ids = request.form.getlist('video_ids')
    if not video_ids:
        return "<div class='alert alert-warning'>No videos selected.</div>"
        
    from app.tasks import start_task
    from app.downloader import download_video
    
    # We will return a main message + OOB swaps for each video button
    response_content = ""
    
    # Monitor batch completion (no global callback needed anymore)
    from app.tasks import monitor_batch_completion
    
    # Collect all task IDs created in the loop
    all_task_ids = []
    for vid in video_ids:
        # Enable per-video tagging now that it is targeted and safe
        task_id = start_task(download_video, vid, trigger_autotag=True)
        all_task_ids.append(task_id)
        
        pb_html = render_template('components/progress_bar.html', task_id=task_id, message="Queued", progress=0)
        response_content += f'<div hx-swap-oob="outerHTML:#btn-download-{vid}">{pb_html}</div>'
        # Also remove the ignore button via OOB
        response_content += f'<div hx-swap-oob="delete:#btn-ignore-{vid}"></div>'

    monitor_batch_completion(all_task_ids, None)
    
    return response_content

@main.route('/ignore/batch', methods=['POST'])
def ignore_batch():
    video_ids = request.form.getlist('video_ids')
    count = 0
    response_content = ""
    for vid in video_ids:
        video = Video.query.get(vid)
        if video:
            video.status = 'ignored'
            count += 1
            row_html = render_template('components/video_row.html', video=video, oob=True)
            response_content += row_html
    db.session.commit()
    return response_content

@main.route('/unignore/batch', methods=['POST'])
def unignore_batch():
    video_ids = request.form.getlist('video_ids')
    count = 0
    response_content = ""
    for vid in video_ids:
        video = Video.query.get(vid)
        if video:
            video.status = 'new'
            count += 1
            row_html = render_template('components/video_row.html', video=video, oob=True)
            response_content += row_html
    db.session.commit()
    return response_content

@main.route('/download/<int:video_id>', methods=['POST'])
def download_video_route(video_id):
    from app.tasks import start_task
    from app.downloader import download_video
    
    task_id = start_task(download_video, video_id)
    
    # Return initial progress bar and remove ignore button
    pb_html = render_template('components/progress_bar.html', task_id=task_id, message="Starting download...", progress=0)
    return f'{pb_html}<div hx-swap-oob="delete:#btn-ignore-{video_id}"></div>'

@main.route('/task/status/<task_id>', methods=['GET'])
def task_status(task_id):
    from app.tasks import get_task_progress
    task = get_task_progress(task_id)
    
    if not task:
        return "Task not found", 404
        
    if task['status'] == 'completed':
        # Check if it was a scan task (result has 'new_count')
        if task.get('result') and isinstance(task['result'], dict) and 'new_count' in task['result']:
             return f"""
            <div class="alert alert-success py-1 px-2 small">
                Scan complete.
                <script>setTimeout(() => location.reload(), 1000);</script>
            </div>
            """
        
        # Check if it was a download task (result has 'video_id')
        if task.get('result') and isinstance(task['result'], dict) and 'video_id' in task['result']:
            video_id = task['result']['video_id']
            video = Video.query.get(video_id)
            if video:
                # Return the updated row via OOB swap
                return render_template('components/video_row.html', video=video, oob=True)
        
        # Default fallback
        return """
        <button class="btn btn-success btn-sm" disabled>
            Downloaded
        </button>
        """
    elif task['status'] == 'failed':
        return f"""
        <button class="btn btn-danger btn-sm" disabled title="{task['message']}">
            Failed
        </button>
        <div class="text-danger small">{task['message']}</div>
        """
    else:
        # Return updated progress bar
        return render_template('components/progress_bar.html', 
                             task_id=task_id, 
                             message=task['message'], 
                             progress=task['progress'])

from app.models import Settings

@main.route('/settings', methods=['GET'])
def settings():
    blacklist = Settings.query.filter_by(key='blacklist').first()
    whitelist = Settings.query.filter_by(key='whitelist').first()
    telegram_token = Settings.query.filter_by(key='telegram_token').first()
    telegram_chat_id = Settings.query.filter_by(key='telegram_chat_id').first()
    stash_url = Settings.query.filter_by(key='stash_url').first()
    stash_api_key = Settings.query.filter_by(key='stash_api_key').first()
    stash_path_mapping = Settings.query.filter_by(key='stash_path_mapping').first()
    stash_check_existing = Settings.query.filter_by(key='stash_check_existing').first()
    schedule_interval = Settings.query.filter_by(key='schedule_interval').first()
    local_scan_path = Settings.query.filter_by(key='local_scan_path').first()
    local_check_existing = Settings.query.filter_by(key='local_check_existing').first()
    yt_dlp_auto_update = Settings.query.filter_by(key='yt_dlp_auto_update').first()
    yt_dlp_last_updated = Settings.query.filter_by(key='yt_dlp_last_updated').first()
    
    # Get yt-dlp version
    import subprocess
    try:
        ytdlp_version = subprocess.check_output(['uv', 'run', 'yt-dlp', '--version'], text=True).strip()
    except Exception:
        ytdlp_version = "Unknown"

    # Get next scheduled scan time
    from app.scheduler import scheduler
    next_scan_time = None
    try:
        job = scheduler.get_job('scheduled_scan')
        if job and job.next_run_time:
            next_scan_time = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        pass

    return render_template('settings.html', 
                           blacklist=blacklist.value if blacklist else '',
                           whitelist=whitelist.value if whitelist else '',
                           telegram_token=telegram_token.value if telegram_token else '',
                           telegram_chat_id=telegram_chat_id.value if telegram_chat_id else '',
                           stash_url=stash_url.value if stash_url else '',
                           stash_api_key=stash_api_key.value if stash_api_key else '',
                           stash_path_mapping=stash_path_mapping.value if stash_path_mapping else '',
                           stash_check_existing=stash_check_existing.value if stash_check_existing else 'true',
                           schedule_interval=schedule_interval.value if schedule_interval else '60',
                           local_scan_path=local_scan_path.value if local_scan_path else '',
                           local_check_existing=local_check_existing.value if local_check_existing else 'true',
                           yt_dlp_auto_update=yt_dlp_auto_update.value if yt_dlp_auto_update else 'false',
                           yt_dlp_version=ytdlp_version,
                           yt_dlp_last_updated=yt_dlp_last_updated.value if yt_dlp_last_updated else 'Never',
                           next_scan_time=next_scan_time)

@main.route('/settings/logs')
def get_logs():
    log_file = 'logs/siphon.log'
    if not os.path.exists(log_file):
        return "No logs found."
    
    try:
        with open(log_file, 'r') as f:
            # Read last 1000 lines roughly
            # For simplicity, read all and take last N lines
            lines = f.readlines()
            last_lines = lines[-200:] # Last 200 lines
            return "".join(last_lines)
    except Exception as e:
        return f"Error reading logs: {e}"

@main.route('/settings/logs/clear', methods=['POST'])
def clear_logs():
    log_file = 'logs/siphon.log'
    try:
        open(log_file, 'w').close()
        return "Logs cleared."
    except Exception as e:
        return f"Error clearing logs: {e}"

@main.route('/settings/<key>', methods=['POST'])
def update_settings(key):
    if key not in ['blacklist', 'whitelist', 'telegram', 'stash', 'schedule', 'localpath', 'autoupdate']:
        return "Invalid setting", 400
    
    if key == 'telegram':
        token = request.form.get('telegram_token')
        chat_id = request.form.get('telegram_chat_id')
        
        s_token = Settings.query.filter_by(key='telegram_token').first() or Settings(key='telegram_token')
        s_token.value = token
        db.session.add(s_token)
        
        s_chat = Settings.query.filter_by(key='telegram_chat_id').first() or Settings(key='telegram_chat_id')
        s_chat.value = chat_id
        db.session.add(s_chat)
    elif key == 'stash':
        url = request.form.get('stash_url')
        api_key = request.form.get('stash_api_key')
        path_mapping = request.form.get('stash_path_mapping')
        check_existing = 'true' if request.form.get('stash_check_existing') else 'false'
        
        s_url = Settings.query.filter_by(key='stash_url').first() or Settings(key='stash_url')
        s_url.value = url
        db.session.add(s_url)
        
        s_key = Settings.query.filter_by(key='stash_api_key').first() or Settings(key='stash_api_key')
        s_key.value = api_key
        db.session.add(s_key)

        s_mapping = Settings.query.filter_by(key='stash_path_mapping').first() or Settings(key='stash_path_mapping')
        s_mapping.value = path_mapping
        db.session.add(s_mapping)

        s_check = Settings.query.filter_by(key='stash_check_existing').first() or Settings(key='stash_check_existing')
        s_check.value = check_existing
        db.session.add(s_check)
    elif key == 'schedule':
        interval = request.form.get('schedule_interval')
        s_interval = Settings.query.filter_by(key='schedule_interval').first() or Settings(key='schedule_interval')
        s_interval.value = interval
        db.session.add(s_interval)
        
        # Update Scheduler Job
        from app.scheduler import scheduler, scheduled_scan
        try:
            if int(interval) > 0:
                scheduler.add_job(id='scheduled_scan', func=scheduled_scan, trigger='interval', minutes=int(interval), replace_existing=True)
            else:
                scheduler.remove_job('scheduled_scan')
        except Exception as e:
            print(f"Error updating scheduler: {e}")
            
    elif key == 'localpath':
        path = request.form.get('local_scan_path')
        check_existing = 'true' if request.form.get('local_check_existing') else 'false'
        
        s_path = Settings.query.filter_by(key='local_scan_path').first() or Settings(key='local_scan_path')
        s_path.value = path
        db.session.add(s_path)

        l_check = Settings.query.filter_by(key='local_check_existing').first() or Settings(key='local_check_existing')
        l_check.value = check_existing
        db.session.add(l_check)
        
    elif key == 'autoupdate':
        enabled = 'true' if request.form.get('yt_dlp_auto_update') == 'on' else 'false'
        s_auto = Settings.query.filter_by(key='yt_dlp_auto_update').first() or Settings(key='yt_dlp_auto_update')
        s_auto.value = enabled
        db.session.add(s_auto)
        
        # Update Scheduler for Auto Update
        from app.scheduler import scheduler, auto_update_ytdlp
        try:
            if enabled == 'true':
                # Run once a day
                scheduler.add_job(id='auto_update_ytdlp', func=auto_update_ytdlp, trigger='interval', hours=24, replace_existing=True)
            else:
                scheduler.remove_job('auto_update_ytdlp')
        except Exception as e:
            print(f"Error updating scheduler for auto-update: {e}")

    else:
        value = request.form.get(key)
        setting = Settings.query.filter_by(key=key).first() or Settings(key=key)
        setting.value = value
        db.session.add(setting)
    
    db.session.commit()
    return "<div class='alert alert-success mt-3 mb-0'>Settings saved!</div>"

@main.route('/settings/update-ytdlp', methods=['POST'])
def update_ytdlp_route():
    import subprocess
    from datetime import datetime
    try:
        # Using uv pip install -U yt-dlp
        result = subprocess.run(['uv', 'pip', 'install', '-U', 'yt-dlp'], capture_output=True, text=True)
        if result.returncode == 0:
            # Update last updated time
            s_last = Settings.query.filter_by(key='yt_dlp_last_updated').first() or Settings(key='yt_dlp_last_updated')
            s_last.value = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.session.add(s_last)
            db.session.commit()
            
            # Get new version
            new_version = subprocess.check_output(['uv', 'run', 'yt-dlp', '--version'], text=True).strip()
            
            return f"<div class='alert alert-success'>yt-dlp updated successfully to {new_version}!<br>Last Updated: {s_last.value}</div>"
        else:
            return f"<div class='alert alert-danger'>Update failed:<br><pre>{result.stderr}</pre></div>"
    except Exception as e:
        return f"<div class='alert alert-danger'>Error: {str(e)}</div>"

from app.notifications import send_telegram_message

@main.route('/settings/telegram/test', methods=['POST'])
def test_telegram():
    success, message = send_telegram_message("🔔 <b>Siphon Test Notification</b>\n\nThis is a test message from your Siphon instance.")
    if success:
        return f"<div class='alert alert-success mt-3 mb-0'>{message}</div>"
    else:
        return f"<div class='alert alert-danger mt-3 mb-0'>Error: {message}</div>"

from app.stash import test_stash_connection

@main.route('/settings/stash/test', methods=['POST'])
def test_stash():
    success, message = test_stash_connection()
    if success:
        return f"<div class='alert alert-success mt-3 mb-0'>{message}</div>"
    else:
        return f"<div class='alert alert-danger mt-3 mb-0'>Error: {message}</div>"

@main.route('/settings/export', methods=['GET'])
def export_performers():
    import json
    from io import BytesIO
    from flask import send_file
    
    performers = Performer.query.all()
    export_data = []
    
    for p in performers:
        # Get ignored videos
        ignored_videos = []
        for v in p.videos.filter_by(status='ignored').all():
            ignored_videos.append({
                'title': v.title,
                'url': v.url,
                'viewkey': v.viewkey,
                'duration': v.duration
            })
            
        p_data = {
            'id': p.id,
            'name': p.name,
            'site': p.site,
            'type': p.type,
            'scheduled_scan_enabled': p.scheduled_scan_enabled,
            'blacklist_keywords': p.blacklist_keywords,
            'whitelist_keywords': p.whitelist_keywords,
            'last_scan': p.last_scan.isoformat() if p.last_scan else None,
            'ignored_videos': ignored_videos
        }
        export_data.append(p_data)
        
    # Create JSON file in memory
    json_str = json.dumps(export_data, indent=2)
    mem = BytesIO()
    mem.write(json_str.encode('utf-8'))
    mem.seek(0)
    
    return send_file(
        mem,
        as_attachment=True,
        download_name=f'siphon_performers_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
        mimetype='application/json'
    )

@main.route('/settings/import', methods=['POST'])
def import_performers():
    import json
    
    if 'file' not in request.files:
        return "<div class='alert alert-danger'>No file uploaded</div>"
        
    file = request.files['file']
    if file.filename == '':
        return "<div class='alert alert-danger'>No file selected</div>"
        
    if not file.filename.endswith('.json'):
        return "<div class='alert alert-danger'>Invalid file type. Please upload a JSON file.</div>"
        
    try:
        data = json.load(file)
        if not isinstance(data, list):
            return "<div class='alert alert-danger'>Invalid JSON format. Expected a list of performers.</div>"
            
        count_updated = 0
        count_created = 0
        
        for p_data in data:
            p_id = p_data.get('id')
            if not p_id:
                continue
                
            performer = Performer.query.get(p_id)
            if performer:
                # Update existing
                performer.name = p_data.get('name', performer.name)
                performer.site = p_data.get('site', performer.site)
                performer.type = p_data.get('type', performer.type)
                performer.scheduled_scan_enabled = p_data.get('scheduled_scan_enabled', performer.scheduled_scan_enabled)
                
                # Merge keywords (simple concatenation with comma check would be messy, 
                # let's just overwrite if provided, or maybe append? 
                # Plan said "merge". Let's try to be smart about it.)
                
                def merge_keywords(current, new):
                    if not new: return current
                    if not current: return new
                    # Split by comma, strip, set, join
                    c_set = set([k.strip() for k in current.split(',') if k.strip()])
                    n_set = set([k.strip() for k in new.split(',') if k.strip()])
                    return ', '.join(sorted(list(c_set.union(n_set))))

                performer.blacklist_keywords = merge_keywords(performer.blacklist_keywords, p_data.get('blacklist_keywords'))
                performer.whitelist_keywords = merge_keywords(performer.whitelist_keywords, p_data.get('whitelist_keywords'))
                
                count_updated += 1
            else:
                # Create new
                performer = Performer(
                    id=p_id,
                    name=p_data.get('name'),
                    site=p_data.get('site'),
                    type=p_data.get('type'),
                    scheduled_scan_enabled=p_data.get('scheduled_scan_enabled', True),
                    blacklist_keywords=p_data.get('blacklist_keywords'),
                    whitelist_keywords=p_data.get('whitelist_keywords')
                )
                if p_data.get('last_scan'):
                    try:
                        performer.last_scan = datetime.fromisoformat(p_data.get('last_scan'))
                    except:
                        pass
                db.session.add(performer)
                count_created += 1
            
            # Process ignored videos
            ignored_videos = p_data.get('ignored_videos', [])
            for v_data in ignored_videos:
                viewkey = v_data.get('viewkey')
                if not viewkey: continue
                
                # Check if video exists
                video = Video.query.filter_by(performer_id=p_id, viewkey=viewkey).first()
                if video:
                    if video.status != 'downloaded': # Don't overwrite downloaded status
                        video.status = 'ignored'
                else:
                    # Create new ignored video record
                    video = Video(
                        performer_id=p_id,
                        title=v_data.get('title', 'Unknown'),
                        url=v_data.get('url', ''),
                        viewkey=viewkey,
                        duration=v_data.get('duration'),
                        status='ignored'
                    )
                    db.session.add(video)
                    
        db.session.commit()
        return f"<div class='alert alert-success'>Import successful! Created {count_created}, Updated {count_updated} performers.</div>"
        
    except Exception as e:
        return f"<div class='alert alert-danger'>Error importing file: {str(e)}</div>"

