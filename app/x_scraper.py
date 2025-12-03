import json
import time
import re
import logging
from playwright.sync_api import sync_playwright
from app.tasks import update_task_progress
from app.models import Video

logger = logging.getLogger(__name__)

def load_cookies(cookie_file):
    """Loads cookies from a JSON or Netscape format file."""
    cookies = []
    try:
        with open(cookie_file, 'r') as f:
            content = f.read()
            try:
                # Try JSON format first
                raw_cookies = json.loads(content)
                # Filter and fix cookies for Playwright
                valid_keys = {'name', 'value', 'url', 'domain', 'path', 'expires', 'httpOnly', 'secure', 'sameSite'}
                for cookie in raw_cookies:
                    # Create a new dict with only valid keys
                    clean_cookie = {k: v for k, v in cookie.items() if k in valid_keys}
                    
                    # Fix sameSite
                    if 'sameSite' in clean_cookie:
                        if clean_cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                            clean_cookie['sameSite'] = 'None'
                    
                    cookies.append(clean_cookie)
            except json.JSONDecodeError:
                # Fallback to Netscape format (simple parsing)
                for line in content.splitlines():
                    if not line.strip():
                        continue
                        
                    http_only = False
                    if line.startswith('#HttpOnly_'):
                        http_only = True
                        line = line[10:] # Remove prefix
                    elif line.startswith('#'):
                        continue
                        
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        cookie = {
                            'domain': parts[0],
                            'path': parts[2],
                            'secure': parts[3].upper() == 'TRUE',
                            'expires': int(parts[4]) if parts[4] else 0,
                            'name': parts[5],
                            'value': parts[6].strip(),
                            'httpOnly': http_only
                        }
                        cookies.append(cookie)
    except Exception as e:
        logger.error(f"Error loading cookies: {e}")
        return []
    return cookies

def extract_videos_from_json(data, video_links, username):
    """Recursively search for tweets with video media in the JSON response."""
    
    # Helper to process a single tweet object
    def process_tweet(tweet):
        if not tweet: return
        
        # Check legacy field (standard place for media)
        legacy = tweet.get('legacy', {})
        extended_entities = legacy.get('extended_entities', {})
        media_list = extended_entities.get('media', [])
        
        for media in media_list:
            if media.get('type') == 'video':
                # Found a video!
                tweet_id = legacy.get('id_str')
                if tweet_id:
                    video_url = f"https://x.com/{username}/status/{tweet_id}"
                    
                    # Extract metadata
                    text = legacy.get('full_text', '')
                    created_at = legacy.get('created_at') # e.g., "Wed Oct 10 20:19:24 +0000 2018"
                    
                    # Parse date
                    date_str = None
                    if created_at:
                        try:
                            # Parse X format
                            ts = time.strptime(created_at, '%a %b %d %H:%M:%S +0000 %Y')
                            date_str = time.strftime('%Y-%m-%d', ts)
                        except Exception:
                            pass
                    
                    # Duration is usually in video_info
                    video_info = media.get('video_info', {})
                    duration_ms = video_info.get('duration_millis')
                    duration = duration_ms / 1000 if duration_ms else None
                    
                    # Update if new or if upgrading from DOM to API
                    if tweet_id not in video_links or video_links[tweet_id].get('source') == 'dom':
                        video_links[tweet_id] = {
                            'id': tweet_id,
                            'url': video_url,
                            'text': text,
                            'date': date_str,
                            'duration': duration,
                            'source': 'api'
                        }

    # Recursive traversal to find 'result' objects that look like tweets
    def traverse(obj):
        if isinstance(obj, dict):
            if obj.get('__typename') == 'Tweet':
                process_tweet(obj)
            elif obj.get('__typename') == 'TweetWithVisibilityResults':
                # This wrapper contains the actual tweet
                if 'tweet' in obj:
                    process_tweet(obj['tweet'])
            elif 'tweet' in obj: # Sometimes nested like tweet_results -> result -> tweet
                traverse(obj['tweet'])
            elif 'result' in obj:
                traverse(obj['result'])
            
            for key, value in obj.items():
                traverse(value)
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)

    traverse(data)

def scrape_x_videos(username, task_id=None, use_cookies=False):
    # Default cookie file location
    cookie_file = "cookies.txt" 
    
    with sync_playwright() as p:
        # Headless mode for production
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        # Load cookies
        if use_cookies and cookie_file:
            cookies = load_cookies(cookie_file)
            if cookies:
                context.add_cookies(cookies)
                logger.info(f"Loaded {len(cookies)} cookies.")
            else:
                logger.warning("No cookies loaded. Login might fail.")

        page = context.new_page()
        
        # Dictionary to store video info: tweet_id -> {url, text, duration, ...}
        video_links = {}

        # Setup Response Interceptor
        def handle_response(response):
            # Intercept GraphQL responses for Timeline, UserMedia, UserTweets, etc.
            if "graphql" in response.url and ("User" in response.url or "Tweet" in response.url or "Timeline" in response.url):
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        extract_videos_from_json(data, video_links, username)
                except Exception:
                    pass

        page.on("response", handle_response)
        
        url = f"https://x.com/{username}/media"
        if task_id:
            update_task_progress(task_id, message=f"Opening {username}...")
        logger.info(f"Navigating to {url}...")
        
        try:
            page.goto(url)
            page.wait_for_timeout(5000)
            
            # Reload to ensure we capture the initial UserMedia request
            page.evaluate("window.scrollTo(0, 100)")
            page.wait_for_timeout(1000)
            
            # Check for error states
            try:
                page.wait_for_timeout(3000)
                content_text = page.content()
                
                if any(msg in content_text for msg in ["This account doesn’t exist", "This account does not exist", "계정이 존재하지 않습니다"]):
                    logger.error(f"Error: The account '{username}' does not exist.")
                    return []
                
                if page.locator("div[data-testid='emptyState']").count() > 0:
                     empty_text = page.locator("div[data-testid='emptyState']").inner_text()
                     if "exist" in empty_text or "존재하지" in empty_text:
                         logger.error(f"Error: The account '{username}' does not exist.")
                         return []

                if any(msg in content_text for msg in ["Account suspended", "계정이 일시 정지되었습니다"]):
                    logger.error(f"Error: The account '{username}' has been suspended.")
                    return []
                
                if any(msg in content_text for msg in ["These Tweets are protected", "비공개 계정입니다"]):
                    if page.locator(f"a[href*='/{username}/status/']").count() == 0:
                        logger.error(f"Error: The account '{username}' is protected and you are not following them.")
                        return []

            except Exception:
                pass

            # Check for sensitive content warning button
            try:
                warning_btn = page.locator("div[role='button']").filter(has_text="Yes, view profile").first
                if warning_btn.count() > 0:
                    logger.info("Found sensitive content warning. Clicking...")
                    warning_btn.click()
                    page.wait_for_timeout(3000)
                    page.reload()
                    page.wait_for_timeout(5000)
            except Exception:
                pass

            last_height = page.evaluate("document.body.scrollHeight")
            retries = 0
            max_retries = 3
            
            if task_id:
                update_task_progress(task_id, message="Scanning...")
            logger.info("Scanning media grid...")
            
            while True:
                # 1. DOM Scan
                links = page.locator(f"a[href*='/{username}/status/']").all()
                for link in links:
                    href = link.get_attribute("href")
                    if href:
                        full_url = f"https://x.com{href}" if href.startswith('/') else href
                        full_url = full_url.split('?')[0]
                        
                        if '/video/' in full_url:
                            # Extract ID
                            match = re.search(r'/status/(\d+)', full_url)
                            if match:
                                tweet_id = match.group(1)
                                if tweet_id not in video_links:
                                    # Try to get duration from DOM
                                    duration = None
                                    try:
                                        duration_el = link.locator("div[aria-label*='duration'], span").filter(has_text=re.compile(r'\d+:\d+')).first
                                        if duration_el.count() > 0:
                                            duration_text = duration_el.inner_text().strip()
                                            parts = duration_text.split(':')
                                            if len(parts) == 2:
                                                duration = int(parts[0]) * 60 + int(parts[1])
                                            elif len(parts) == 3:
                                                duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                                    except:
                                        pass

                                    video_links[tweet_id] = {
                                        'id': tweet_id,
                                        'url': f"https://x.com/{username}/status/{tweet_id}",
                                        'text': None,
                                        'duration': duration,
                                        'source': 'dom'
                                    }
                
                # 2. Scroll
                for _ in range(5):
                    page.keyboard.press("PageDown")
                    page.wait_for_timeout(500)
                
                page.wait_for_timeout(2000) 
                
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    retries += 1
                    if retries >= max_retries:
                        break
                    logger.info(f"No new content loaded. Retrying ({retries}/{max_retries})...")
                    page.evaluate("window.scrollBy(0, -500)")
                    page.wait_for_timeout(1000)
                    page.evaluate("window.scrollBy(0, 500)")
                    page.wait_for_timeout(1000)
                else:
                    retries = 0
                    last_height = new_height
                    if task_id:
                        update_task_progress(task_id, message=f"Found {len(video_links)} videos...")
                    
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            # Backfill metadata for DOM-only videos
            dom_videos = [v for v in video_links.values() if v.get('source') == 'dom']
            
            # Optimization: Filter out videos that already exist in the database
            if dom_videos:
                try:
                    # We need to check if we are in an app context. 
                    # scrape_x_videos is usually called from a task which has context.
                    existing_viewkeys = set()
                    # Get all viewkeys for this performer (if we knew the performer ID)
                    # But we only have username here. 
                    # So we can just query by viewkey.
                    # Since we might have many, let's query in bulk or check one by one?
                    # Bulk query is better.
                    viewkeys_to_check = [v['id'] for v in dom_videos]
                    existing_videos = Video.query.filter(Video.viewkey.in_(viewkeys_to_check)).all()
                    existing_viewkeys = {v.viewkey for v in existing_videos}
                    
                    # Filter out existing
                    videos_to_backfill = [v for v in dom_videos if v['id'] not in existing_viewkeys]
                    
                    if len(videos_to_backfill) < len(dom_videos):
                        logger.info(f"Skipping backfill for {len(dom_videos) - len(videos_to_backfill)} existing videos.")
                        dom_videos = videos_to_backfill
                        
                except Exception as e:
                    logger.warning(f"Could not check database for existing videos: {e}")
            
            if dom_videos:
                if task_id:
                    update_task_progress(task_id, message=f"Getting details for {len(dom_videos)} videos...")
                logger.info(f"Backfilling metadata for {len(dom_videos)} videos...")
                
                for i, video in enumerate(dom_videos):
                    try:
                        page.goto(video['url'])
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass
            
            browser.close()
            
            # Format for app
            formatted_videos = []
            for v in video_links.values():
                formatted_videos.append({
                    'title': v.get('text') or f"Tweet {v['id']}",
                    'viewkey': v['id'],
                    'url': v['url'],
                    'date': v.get('date'),
                    'duration': format_duration(v.get('duration')) if v.get('duration') else None
                })
            
            return formatted_videos

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
