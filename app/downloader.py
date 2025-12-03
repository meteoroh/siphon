import yt_dlp
import os
from app import db
from app.models import Video
from app.models import Video
import logging

logger = logging.getLogger(__name__)

class YtDlpLogger:
    def debug(self, msg):
        # Filter out verbose debug messages if needed, or log at DEBUG level
        # For now, we'll log at DEBUG, but app logger is at INFO, so these might be hidden
        # unless we change app level.
        # To see download progress details in logs, we might want to log some at INFO.
        if msg.startswith('[download]'):
            logger.info(msg)
        else:
            logger.debug(msg)

    def info(self, msg):
        logger.info(msg)

    def warning(self, msg):
        logger.warning(msg)

    def error(self, msg):
        logger.error(msg)
FRAGMENT_RETRY_LIMIT = 20
DOWNLOAD_BASE_DIR = 'downloads' # Default, should be configurable

from app.tasks import update_task_progress

def download_video(task_id, video_id, trigger_autotag=True):
    # We need to create a new app context since this runs in a thread
    from app import create_app
    app = create_app(with_scheduler=False)
    
    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            update_task_progress(task_id, message="Video not found")
            raise Exception("Video not found")

        # Get download path from settings
        from app.models import Settings
        local_path_setting = Settings.query.filter_by(key='local_scan_path').first()
        base_dir = local_path_setting.value if (local_path_setting and local_path_setting.value) else DOWNLOAD_BASE_DIR

        # Check for site-specific path (X)
        is_x_video = video.performer.site == 'x'
        if is_x_video:
            local_path_x_setting = Settings.query.filter_by(key='local_scan_path_x').first()
            if local_path_x_setting and local_path_x_setting.value:
                base_dir = local_path_x_setting.value
        # Check for site-specific path (Pornhub)
        elif video.performer.site == 'pornhub':
            local_path_ph_setting = Settings.query.filter_by(key='local_scan_path_pornhub').first()
            if local_path_ph_setting and local_path_ph_setting.value:
                base_dir = local_path_ph_setting.value
        # Check for site-specific path (xHamster)
        elif video.performer.site == 'xhamster':
            local_path_xh_setting = Settings.query.filter_by(key='local_scan_path_xhamster').first()
            if local_path_xh_setting and local_path_xh_setting.value:
                base_dir = local_path_xh_setting.value

        performer_name = video.performer.name
        download_dir = os.path.join(base_dir, performer_name)
        os.makedirs(download_dir, exist_ok=True)
        try:
            os.chmod(download_dir, 0o755)
        except Exception:
            pass

        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    if total > 0:
                        percent = round((downloaded / total) * 100, 1)
                        update_task_progress(task_id, progress=percent, message=f"Downloading {video.performer.name}: {percent:.1f}%", total_bytes=total, downloaded_bytes=downloaded)
                except Exception:
                    pass
            elif d['status'] == 'finished':
                update_task_progress(task_id, progress=99, message=f"Processing {video.performer.name}...")

        # Default template
        outtmpl = '%(title)s [%(id)s].%(ext)s'
        
        # Custom template for X to ensure uniqueness and traceability
        if is_x_video:
            outtmpl = f'%(title)s [x-{video.viewkey}-%(id)s].%(ext)s'

        ydl_opts = {
            'paths': {'home': download_dir},
            'outtmpl': outtmpl,
            'fragment_retries': FRAGMENT_RETRY_LIMIT,
            'skip_unavailable_fragments': False,
            'quiet': False, # We want logs now
            'logger': YtDlpLogger(),

            'progress_hooks': [progress_hook]
        }

        # Add cookies if enabled for performer
        if video.performer.use_cookies:
            cookie_file = 'cookies.txt'
            if os.path.exists(cookie_file):
                ydl_opts['cookiefile'] = cookie_file
                logger.info(f"Using cookies for download (Performer: {performer_name})")
            else:
                logger.warning(f"Cookies enabled for {performer_name} but cookies.txt not found")

        try:
            downloaded_files = []
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video.url, download=True)
                
                # Handle multi-video tweets (playlist)
                if 'entries' in info:
                    entries = info['entries']
                else:
                    entries = [info]
                    
                for entry in entries:
                    filename = ydl.prepare_filename(entry)
                    
                    if not os.path.isabs(filename):
                        norm_filename = os.path.normpath(filename)
                        norm_download_dir = os.path.normpath(download_dir)
                        
                        if not norm_filename.startswith(norm_download_dir):
                             filename = os.path.join(download_dir, filename)
                        
                        filename = os.path.abspath(filename)
                    
                    downloaded_files.append({'filename': filename, 'info': entry})
            
            video.status = 'downloaded'
            db.session.commit()
            
            # --- Stash Integration ---
            try:
                from app.stash import StashClient
                import time
                
                stash = StashClient()
                if stash.is_configured():
                    update_task_progress(task_id, progress=99, message=f"Syncing {video.performer.name} with Stash...")
                    
                    # 1. Trigger Scan (Scan the directory once)
                    # Scanning the folder is more robust for new directories than scanning individual files
                    job_id = stash.scan_file(download_dir)
                    
                    if job_id:
                        logger.info(f"Stash scan job started: {job_id}")
                        stash.wait_for_job(job_id)
                    
                    for item in downloaded_files:
                        filename = item['filename']
                        entry_info = item['info']
                        
                        # 2. Find Scene
                        basename = os.path.basename(filename)
                        scene_id = stash.find_scene_by_path(basename)
                                
                        # 3. Prepare Metadata & Scrape
                        if scene_id:
                            # Basic Metadata
                            upload_date = entry_info.get('upload_date')
                            formatted_date = None
                            if upload_date and len(upload_date) == 8:
                                formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                                
                            # Find Performer in Stash
                            performer_ids = []
                            performer_id = stash.find_performer(video.performer.name)
                            if performer_id:
                                performer_ids.append(performer_id)
                                logger.info(f"Found Stash performer {video.performer.name} ({performer_id})")
                            else:
                                logger.warning(f"Stash performer not found: {video.performer.name}")

                            video_data = {
                                'title': entry_info.get('title', video.title),
                                'url': video.url,
                                'date': formatted_date,
                                'description': entry_info.get('description'),
                                'performer_ids': performer_ids
                            }
                            
                            # Scrape Metadata (if enabled)
                            if trigger_autotag:
                                logger.info(f"Scraping scene {scene_id} with builtin_autotag...")
                                scraped_data = stash.scrape_scene(scene_id)
                                
                                if scraped_data:
                                    logger.info(f"Scrape successful. Merging data...")
                                    
                                    if scraped_data.get('tags'):
                                        video_data['tag_ids'] = [t['stored_id'] for t in scraped_data['tags'] if t.get('stored_id')]
                                        
                                    if scraped_data.get('studio') and scraped_data['studio'].get('stored_id'):
                                        video_data['studio_id'] = scraped_data['studio']['stored_id']
                                        
                                    performers_list = scraped_data.get('performers') or []
                                    scraped_performer_ids = [p['stored_id'] for p in performers_list if p.get('stored_id')]
                                    if scraped_performer_ids:
                                        for pid in scraped_performer_ids:
                                            if pid not in video_data['performer_ids']:
                                                video_data['performer_ids'].append(pid)
                                else:
                                    logger.warning(f"No scrape results found for scene {scene_id}")
                            else:
                                logger.info("Skipping AutoTag (batch mode)")

                            # 4. Single Update
                            stash.update_scene(scene_id, video_data)
                            logger.info(f"Updated Stash scene {scene_id} for {basename}")
                            
                        else:
                            logger.warning(f"Stash scene not found for {basename} after scan.")
                        
            except Exception as e:
                logger.error(f"Stash integration error: {e}")
                # Don't fail the download task just because Stash sync failed
            # -------------------------

            update_task_progress(task_id, progress=100, message=f"Download complete for {video.performer.name}")
            return {'video_id': video_id, 'status': 'success'}
        except Exception as e:
            update_task_progress(task_id, message=f"Error: {str(e)}")
            raise e

