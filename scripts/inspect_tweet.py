import logging
import json
from playwright.sync_api import sync_playwright
from app.x_scraper import load_cookies, extract_videos_from_json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def inspect_tweet(tweet_url):
    cookie_file = "cookies.txt"
    username = tweet_url.split('/')[3]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        
        # Load cookies
        cookies = load_cookies(cookie_file)
        if cookies:
            context.add_cookies(cookies)
            logger.info(f"Loaded {len(cookies)} cookies.")
        
        page = context.new_page()
        video_links = {}
        
        def handle_response(response):
            if "graphql" in response.url and ("TweetDetail" in response.url):
                try:
                    if "application/json" in response.headers.get("content-type", ""):
                        logger.info("Intercepted TweetDetail response!")
                        data = response.json()
                        extract_videos_from_json(data, video_links, username)
                except Exception as e:
                    logger.error(f"Error parsing response: {e}")

        page.on("response", handle_response)
        
        logger.info(f"Navigating to {tweet_url}...")
        page.goto(tweet_url)
        page.wait_for_timeout(5000) # Wait for load
        
        browser.close()
        
        print("\n--- Extraction Results ---")
        if not video_links:
            print("No videos found.")
        else:
            for tweet_id, data in video_links.items():
                print(f"Tweet ID: {tweet_id}")
                print(f"URL: {data['url']}")
                print(f"Media IDs: {data.get('media_ids', [])}")
                print("-" * 20)

if __name__ == "__main__":
    inspect_tweet("https://x.com/SpaceX/status/1959923485809254706")
