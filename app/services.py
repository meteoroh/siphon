from app import db
from app.models import Video, Settings
from app.scraper import scrape_performer, is_video_allowed
from app.stash import check_stash_video
from app.tasks import update_task_progress
from datetime import datetime
import os

def scan_performer_service(performer, task_id=None):
    """
    Core logic for scanning a performer.
    Shared by manual scan (routes.py) and scheduled scan (scheduler.py).
    """
    if task_id:
        update_task_progress(task_id, progress=10, message=f"Starting scan for {performer.name}...")
    else:
        print(f"Starting scan for {performer.name}...")
    
    # 1. Scrape new videos
    videos = scrape_performer(performer, task_id)
    
    if task_id:
        update_task_progress(task_id, progress=50, message=f"Processing videos for {performer.name}...")
    
    # Get settings
    local_path_setting = Settings.query.filter_by(key='local_scan_path').first()
    local_path = local_path_setting.value if (local_path_setting and local_path_setting.value) else None
    
    # Check for site-specific path
    if performer.site == 'x':
        local_path_x_setting = Settings.query.filter_by(key='local_scan_path_x').first()
        if local_path_x_setting and local_path_x_setting.value:
            local_path = local_path_x_setting.value
    elif performer.site == 'pornhub':
        local_path_ph_setting = Settings.query.filter_by(key='local_scan_path_pornhub').first()
        if local_path_ph_setting and local_path_ph_setting.value:
            local_path = local_path_ph_setting.value
    elif performer.site == 'xhamster':
        local_path_xh_setting = Settings.query.filter_by(key='local_scan_path_xhamster').first()
        if local_path_xh_setting and local_path_xh_setting.value:
            local_path = local_path_xh_setting.value
    
    stash_check_setting = Settings.query.filter_by(key='stash_check_existing').first()
    check_stash = stash_check_setting.value == 'true' if stash_check_setting else True
    
    local_check_setting = Settings.query.filter_by(key='local_check_existing').first()
    check_local_files = local_check_setting.value == 'true' if local_check_setting else True
    
    local_filenames = []
    if local_path and check_local_files:
        if task_id:
            update_task_progress(task_id, message=f"Indexing local files for {performer.name}...")
        try:
            for root, dirs, files in os.walk(local_path):
                for file in files:
                    local_filenames.append(file)
        except Exception as e:
            print(f"Error scanning local path: {e}")

    # Helper to check if video exists locally
    def check_local(viewkey, title):
        if not check_local_files:
            return False
        if not local_filenames:
            return False
        # Optimization: Check viewkey first as it's unique and likely in filename
        for fname in local_filenames:
            if viewkey in fname:
                return True
        
        return False

    if task_id:
        update_task_progress(task_id, progress=50, message=f"Processing videos for {performer.name}...")
    
    # 2. Process EXISTING 'new' videos (Filter & Sync)
    existing_new_videos = Video.query.filter_by(performer_id=performer.id, status='new').all()
    for vid in existing_new_videos:
        # Filter check
        if not is_video_allowed(vid.title, performer, vid.duration):
            vid.status = 'ignored'
            continue
            
        # Sync check (Local & Stash)
        in_local = check_local(vid.viewkey, vid.title)
        if in_local:
            vid.status = 'downloaded'
            continue
            
        in_stash = False
        if check_stash:
            # We don't store media_ids in DB currently, so we can't pass them here for existing videos
            # unless we add a column. But for existing 'new' videos, we might have just scraped them?
            # No, 'existing_new_videos' are from DB.
            # So this fallback only works for freshly scraped videos in step 1.
            in_stash = check_stash_video(vid.url, vid.title, vid.viewkey)
            
        if in_stash:
            vid.status = 'downloaded'
            
    # 3. Process EXISTING 'downloaded' videos (Revert if missing)
    # This handles the case where user deletes a file locally
    # Only run this if we are actually checking!
    if check_local_files or check_stash:
        existing_downloaded_videos = Video.query.filter_by(performer_id=performer.id, status='downloaded').all()
        reverted_count = 0
        for vid in existing_downloaded_videos:
            # Check if still exists
            in_local = check_local(vid.viewkey, vid.title)
            
            in_stash = False
            if check_stash:
                in_stash = check_stash_video(vid.url, vid.title, vid.viewkey)
            
            # If we are checking both, and neither found -> revert
            # If we are only checking one, and it's not found -> revert?
            # Logic:
            # If checking local AND checking stash: if not in either -> new
            # If checking local ONLY: if not in local -> new
            # If checking stash ONLY: if not in stash -> new
            
            # Simplified:
            found = False
            if check_local_files and in_local: found = True
            if check_stash and in_stash: found = True
            
            # If we didn't find it in any of the enabled checks, revert
            # But wait, if we disable checking, we assume it's there? Or we just don't update?
            # If I disable checking, I probably don't want to revert 'downloaded' to 'new'.
            # So we should only revert if we CHECKED and didn't find.
            
            should_revert = True
            if check_local_files and in_local: should_revert = False
            if check_stash and in_stash: should_revert = False
            
            # If we disabled both checks, we shouldn't revert anything.
            if not check_local_files and not check_stash:
                should_revert = False
                
            if should_revert:
                vid.status = 'new'
                reverted_count += 1
            
    # Update last_scan
    performer.last_scan = datetime.utcnow()
            
    new_videos_count = 0
    total_videos = len(videos)
    
    for i, v_data in enumerate(videos):
        # Check if video already exists
        existing = Video.query.filter_by(performer_id=performer.id, viewkey=v_data['viewkey']).first()
        if not existing:
            # Check Stash
            in_stash = False
            if check_stash:
                in_stash = check_stash_video(v_data['url'], v_data['title'], v_data['viewkey'], v_data.get('media_ids'))
            
            # Check Local Path
            in_local = check_local(v_data['viewkey'], v_data['title'])

            if not is_video_allowed(v_data['title'], performer, v_data.get('duration')):
                status = 'ignored'
            else:
                status = 'downloaded' if (in_stash or in_local) else 'new'
            
            video = Video(
                performer_id=performer.id,
                title=v_data['title'],
                url=v_data['url'],
                viewkey=v_data['viewkey'],
                date=v_data.get('date'),
                duration=v_data.get('duration'),
                status=status
            )
            db.session.add(video)
            if status == 'new':
                new_videos_count += 1
        
        # Update progress for processing
        if task_id and total_videos > 0:
            percent = round(50 + ((i / total_videos) * 40), 1)
            update_task_progress(task_id, progress=percent, message=f"Processing {performer.name}: {i+1}/{total_videos}...")
    
    db.session.commit()
    
    if task_id:
        update_task_progress(task_id, progress=100, message=f"Scan complete for {performer.name}. Found {new_videos_count} new.")
        
    return {'new_count': new_videos_count, 'total_found': len(videos), 'new_video_ids': [v.id for v in db.session.new if isinstance(v, Video) and v.status == 'new']}
