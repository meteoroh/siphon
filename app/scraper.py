import yt_dlp
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import time
import logging

logger = logging.getLogger(__name__)

# --- yt-dlp Options (Used for PornHub) ---
YDL_OPTS = {
    'extract_flat': 'in_playlist',
    'quiet': True,
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

from app.tasks import update_task_progress

def scrape_xhamster_videos(performer_id, performer_type, task_id=None, use_cookies=False):
    """
    Scrapes videos for xHamster performers.
    """
    if performer_type == 'creator':
        base_url = f"https://xhamster.com/creators/{performer_id}/newest"
    elif performer_type == 'pornstar':
        base_url = f"https://xhamster.com/pornstars/{performer_id}/exclusive"
    else:
        logger.warning(f"Unknown xhamster performer type: {performer_type}")
        return []

    all_found_videos = []
    page_number = 1

    while True:
        if task_id:
            update_task_progress(task_id, message=f"Scanning page {page_number}...")
            
        if page_number == 1:
            current_url = base_url
        else:
            current_url = f"{base_url}/{page_number}"

        logger.info(f"Scraping xhamster page: {current_url}")
        
        try:
            cookies = {}
            if use_cookies:
                import http.cookiejar
                import os
                if os.path.exists('cookies.txt'):
                    try:
                        cj = http.cookiejar.MozillaCookieJar('cookies.txt')
                        cj.load()
                        # Convert to dict for requests
                        cookies = {cookie.name: cookie.value for cookie in cj}
                        logger.info("Loaded cookies from cookies.txt for xHamster scraping")
                    except Exception as e:
                        logger.error(f"Error loading cookies: {e}")

            response = requests.get(current_url, headers=HEADERS, cookies=cookies, timeout=15)
            if response.status_code == 404:
                break
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            link_tags = soup.select('div.thumb-list__item a.video-thumb-info__name')

            if not link_tags:
                break
            
            for link in link_tags:
                url = link.get('href')
                title = link.text.strip() 
                
                # Try to find duration
                duration = None
                parent_div = link.find_parent('div', class_='thumb-list__item')
                if parent_div:
                    duration_tag = parent_div.select_one('.thumb-image-container__duration')
                    if duration_tag:
                        duration = duration_tag.text.strip()

                if url and title:
                    try:
                        slug_with_key = url.split('/')[-1]
                        _, viewkey = slug_with_key.rsplit('-', 1)
                        all_found_videos.append({'title': title, 'viewkey': viewkey, 'url': url, 'duration': duration})
                    except ValueError:
                        continue
            
            page_number += 1
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            logger.error(f"An error occurred during request: {e}")
            break
            
    return all_found_videos

def scrape_pornhub_videos(performer_id, performer_type, task_id=None, use_cookies=False):
    """
    Scrapes videos for Pornhub performers using BeautifulSoup (better for duration/metadata).
    """
    if performer_type == 'model':
        base_url = f"https://www.pornhub.com/model/{performer_id}/videos"
    elif performer_type == 'pornstar':
        base_url = f"https://www.pornhub.com/pornstar/{performer_id}/videos/upload"
    else:
        logger.warning(f"Unknown pornhub performer type: {performer_type}")
        return []

    videos_data = []
    page_number = 1
    
    while True:
        if task_id:
            update_task_progress(task_id, message=f"Scanning page {page_number}...")
            
        current_url = f"{base_url}?page={page_number}"
        logger.info(f"Scraping pornhub page: {current_url}")
        
        try:
            cookies = {}
            if use_cookies:
                import http.cookiejar
                import os
                if os.path.exists('cookies.txt'):
                    try:
                        cj = http.cookiejar.MozillaCookieJar('cookies.txt')
                        cj.load()
                        # Convert to dict for requests
                        cookies = {cookie.name: cookie.value for cookie in cj}
                        logger.info("Loaded cookies from cookies.txt for Pornhub scraping")
                    except Exception as e:
                        logger.error(f"Error loading cookies: {e}")

            response = requests.get(current_url, headers=HEADERS, cookies=cookies, timeout=15)
            if response.status_code == 404:
                break
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Select video items
            # Try multiple selectors as PH layout varies
            video_items = soup.select('ul#videoCategory li.videoBox')
            if not video_items:
                video_items = soup.select('.videoUList .videoBox')
                
            if not video_items:
                # If no videos found on page 1, maybe empty. If page > 1, stop.
                break
                
            for item in video_items:
                title_tag = item.select_one('.title a')
                if not title_tag: continue
                
                title = title_tag.text.strip()
                url = "https://www.pornhub.com" + title_tag.get('href')
                
                # Extract viewkey
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                viewkey = query_params.get('viewkey', [None])[0]
                
                if not viewkey:
                    continue
                    
                # Extract duration
                duration = None
                duration_tag = item.select_one('.duration')
                if duration_tag:
                    duration = duration_tag.text.strip()
                
                videos_data.append({'title': title, 'viewkey': viewkey, 'url': url, 'duration': duration})
            
            # Check for next page button to decide whether to continue
            if page_number > 20: # Safety limit
                break
                
            page_number += 1
            time.sleep(1)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"An error occurred during request: {e}")
            break
            
    return videos_data

def format_duration(seconds):
    if not seconds:
        return None
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        else:
            return f"{m}:{s:02d}"
    except Exception:
        return str(seconds)

def parse_duration_to_minutes(duration_str):
    if not duration_str:
        return 0
    try:
        parts = list(map(int, duration_str.split(':')))
        if len(parts) == 2: # MM:SS
            return parts[0] + (parts[1] / 60)
        elif len(parts) == 3: # HH:MM:SS
            return (parts[0] * 60) + parts[1] + (parts[2] / 60)
        return 0
    except Exception:
        return 0

def is_video_allowed(title, performer, duration_str=None):
    # Check Minimum Duration
    if performer.min_duration > 0:
        minutes = parse_duration_to_minutes(duration_str)
        if minutes < performer.min_duration:
            return False # Too short

    # Global Blacklist
    from app.models import Settings
    global_blacklist_setting = Settings.query.filter_by(key='blacklist').first()
    global_blacklist = [kw.strip().lower() for kw in global_blacklist_setting.value.split(',')] if global_blacklist_setting and global_blacklist_setting.value else []
    
    # Global Whitelist
    global_whitelist_setting = Settings.query.filter_by(key='whitelist').first()
    global_whitelist = [kw.strip().lower() for kw in global_whitelist_setting.value.split(',')] if global_whitelist_setting and global_whitelist_setting.value else []

    # Performer Blacklist
    performer_blacklist = [kw.strip().lower() for kw in performer.blacklist_keywords.split(',')] if performer.blacklist_keywords else []
    
    # Performer Whitelist
    performer_whitelist = [kw.strip().lower() for kw in performer.whitelist_keywords.split(',')] if performer.whitelist_keywords else []

    title_lower = title.lower()
    
    # Check Blacklists (Global & Performer)
    if any(kw in title_lower for kw in global_blacklist) or any(kw in title_lower for kw in performer_blacklist):
        return False # Blacklisted
        
    # Check Whitelists (Global & Performer)
    if (global_whitelist or performer_whitelist):
        matches_global = any(kw in title_lower for kw in global_whitelist) if global_whitelist else False
        matches_performer = any(kw in title_lower for kw in performer_whitelist) if performer_whitelist else False
        
        if not (matches_global or matches_performer):
            return False # Not whitelisted

    return True

def filter_videos(videos, performer):
    filtered_videos = []
    for video in videos:
        if is_video_allowed(video['title'], performer, video.get('duration')):
            filtered_videos.append(video)
    return filtered_videos

def scrape_performer(performer, task_id=None):
    """
    Dispatcher function to scrape based on performer site.
    """
    videos = []
    if performer.site == 'xhamster':
        videos = scrape_xhamster_videos(performer.id, performer.type, task_id, performer.use_cookies)
    elif performer.site == 'pornhub':
        videos = scrape_pornhub_videos(performer.id, performer.type, task_id, performer.use_cookies)
    elif performer.site == 'x':
        from app.x_scraper import scrape_x_videos
        videos = scrape_x_videos(performer.id, task_id, performer.use_cookies)
    
    return videos
