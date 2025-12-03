import yt_dlp
import json

def check_multi_video_tweet(url):
    ydl_opts = {
        'outtmpl': '%(title)s [%(id)s].%(ext)s',
        'quiet': True,
        'simulate': True,
        'dump_single_json': True,
        'extract_flat': False
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        print(json.dumps(info, indent=2))

# Example multi-video tweet (replace with a known one if available)
# Using a placeholder or asking user for one might be needed, 
# but let's try to see if we can find one or just simulate the logic.
# For now, I'll just write the script structure.
if __name__ == "__main__":
    # This is a known multi-video tweet for testing purposes
    # If this doesn't work, I'll ask the user.
    # https://x.com/NASA/status/1863668273827382738 (Hypothetical)
    # Let's use a real one if possible, or just rely on documentation/logic.
    # Actually, I will just inspect the code logic first.
    pass
