import argparse
import json
import time
import re
from playwright.sync_api import sync_playwright

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
                    if line.startswith('#') or not line.strip():
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        cookie = {
                            'domain': parts[0],
                            'path': parts[2],
                            'secure': parts[3] == 'TRUE',
                            'expires': int(parts[4]) if parts[4] else 0,
                            'name': parts[5],
                            'value': parts[6].strip()
                        }
                        cookies.append(cookie)
    except Exception as e:
        print(f"Error loading cookies: {e}")
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
                # Construct the link. 
                # We can use the tweet ID (id_str) or the expanded_url
                tweet_id = legacy.get('id_str')
                if tweet_id:
                    # Check if it's a mixed post (multiple media)
                    # The user wants specific video links like .../video/1
                    # But X links usually just point to the status.
                    # If we want to be specific, we can append /video/1
                    
                    # Note: In mixed media, there might be multiple videos?
                    # Usually X allows 1 video or up to 4 photos, or mixed.
                    # If mixed, we might want to capture all videos.
                    
                    video_url = f"https://x.com/{username}/status/{tweet_id}"
                    
                    # Extract metadata
                    text = legacy.get('full_text', '')
                    
                    # Duration is usually in video_info
                    video_info = media.get('video_info', {})
                    duration_ms = video_info.get('duration_millis')
                    duration = duration_ms / 1000 if duration_ms else None
                    
                    # Update if new or if upgrading from DOM to API
                    if tweet_id not in video_links or video_links[tweet_id].get('source') == 'dom':
                        # print(f"Updating metadata for {tweet_id} (Source: API)")
                        video_links[tweet_id] = {
                            'id': tweet_id,
                            'url': video_url,
                            'text': text,
                            'duration': duration,
                            'source': 'api'
                        }
                        # print(f"Found video (API): {video_url}") # Quiet mode

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

def scrape_videos(username, cookie_file, output_file):
    with sync_playwright() as p:
        # Headless mode for production
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        # Load cookies
        if cookie_file:
            cookies = load_cookies(cookie_file)
            if cookies:
                context.add_cookies(cookies)
                print(f"Loaded {len(cookies)} cookies.")
            else:
                print("No cookies loaded. Login might fail.")

        page = context.new_page()
        
        # Dictionary to store video info: tweet_id -> {url, text, duration, ...}
        video_links = {}

        # Setup Response Interceptor
        def handle_response(response):
            # Intercept GraphQL responses for Timeline, UserMedia, UserTweets, etc.
            if "graphql" in response.url and ("User" in response.url or "Tweet" in response.url or "Timeline" in response.url):
                # print(f"Processing API response: {response.url}")
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        data = response.json()
                        
                        # Debug: Dump one TweetDetail response to file
                        # if "TweetDetail" in response.url:
                        #     with open("debug_response.json", "w") as f:
                        #         json.dump(data, f, indent=2)
                                
                        extract_videos_from_json(data, video_links, username)
                except Exception:
                    pass

        page.on("response", handle_response)
        
        url = f"https://x.com/{username}/media"
        print(f"Navigating to {url}...")
        
        try:
            page.goto(url)
            page.wait_for_timeout(5000)
            
            # Reload to ensure we capture the initial UserMedia request
            page.evaluate("window.scrollTo(0, 100)")
            page.wait_for_timeout(1000)
            
            # Check for error states (Suspended, Not Found, Protected)
            try:
                # Wait a bit for content to load
                page.wait_for_timeout(3000)
                
                # Get page text for broader checking
                content_text = page.content()
                # print(f"Page Title: {page.title()}") # Debug
                
                # Check for "This account doesn’t exist" (English and Korean)
                if any(msg in content_text for msg in ["This account doesn’t exist", "This account does not exist", "계정이 존재하지 않습니다"]):
                    print(f"Error: The account '{username}' does not exist.")
                    return
                
                # Check for generic "Empty State" header which often appears for invalid accounts
                if page.locator("div[data-testid='emptyState']").count() > 0:
                     empty_text = page.locator("div[data-testid='emptyState']").inner_text()
                     if "exist" in empty_text or "존재하지" in empty_text:
                         print(f"Error: The account '{username}' does not exist.")
                         return

                # Check for "Account suspended" (English and Korean)
                if any(msg in content_text for msg in ["Account suspended", "계정이 일시 정지되었습니다"]):
                    print(f"Error: The account '{username}' has been suspended.")
                    return
                
                # Check for "These Tweets are protected" (English and Korean)
                if any(msg in content_text for msg in ["These Tweets are protected", "비공개 계정입니다"]):
                    # Double check if we can actually see content (maybe we follow them)
                    if page.locator(f"a[href*='/{username}/status/']").count() == 0:
                        print(f"Error: The account '{username}' is protected and you are not following them.")
                        return

            except Exception:
                pass

            # Check for sensitive content warning button
            try:
                warning_btn = page.locator("div[role='button']").filter(has_text="Yes, view profile").first
                if warning_btn.count() > 0:
                    print("Found sensitive content warning. Clicking...")
                    warning_btn.click()
                    page.wait_for_timeout(3000)
                    page.reload()
                    page.wait_for_timeout(5000)
            except Exception:
                pass

            last_height = page.evaluate("document.body.scrollHeight")
            retries = 0
            max_retries = 3
            
            print("Scanning media grid...")
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
                                        # Look for the duration label inside the link
                                        # It's usually a div or span with text like "0:15"
                                        duration_el = link.locator("div[aria-label*='duration'], span").filter(has_text=re.compile(r'\d+:\d+')).first
                                        if duration_el.count() > 0:
                                            duration_text = duration_el.inner_text().strip()
                                            # Convert "MM:SS" to seconds
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
                                        'text': None, # Text is not visible in grid view
                                        'duration': duration,
                                        'source': 'dom'
                                    }
                                    # print(f"Found video (DOM): {full_url}") # Quiet mode
                
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
                    print(f"No new content loaded. Retrying ({retries}/{max_retries})...")
                    page.evaluate("window.scrollBy(0, -500)")
                    page.wait_for_timeout(1000)
                    page.evaluate("window.scrollBy(0, 500)")
                    page.wait_for_timeout(1000)
                else:
                    retries = 0
                    last_height = new_height
                    
        except KeyboardInterrupt:
            print("\nStopping scrape...")
        except Exception as e:
            print(f"\nAn error occurred: {e}")
        finally:
            # Backfill metadata for DOM-only videos
            dom_videos = [v for v in video_links.values() if v.get('source') == 'dom']
            if dom_videos:
                print(f"\nBackfilling metadata for {len(dom_videos)} videos...")
                for i, video in enumerate(dom_videos):
                    # Simple progress indicator
                    print(f"\rProcessing {i+1}/{len(dom_videos)}", end="", flush=True)
                    try:
                        # Navigate to the status page to trigger the API
                        page.goto(video['url'])
                        # Wait for the API to fire and be intercepted
                        page.wait_for_timeout(2000) # Reduced from 3000
                    except Exception:
                        pass
                print() # Newline after progress

            print(f"\nTotal unique videos found: {len(video_links)}")
            
            # Convert to list for JSON output
            output_data = list(video_links.values())
            
            # Sort by ID (approximate time order)
            output_data.sort(key=lambda x: x['id'], reverse=True)
            
            # Determine output format based on extension
            if output_file.endswith('.json'):
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
            else:
                # Fallback to text list of URLs
                with open(output_file, 'w') as f:
                    for item in output_data:
                        f.write(item['url'] + '\n')
            
            print(f"Saved data to {output_file}")
            browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape X video links.")
    parser.add_argument("username", help="X username (without @)")
    parser.add_argument("--cookies", help="Path to cookies file (json or netscape)", default="cookies.json")
    parser.add_argument("--output", help="Output file (json or txt)", default="videos.json")
    
    args = parser.parse_args()
    
    scrape_videos(args.username, args.cookies, args.output)
