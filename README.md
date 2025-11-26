# Siphon

Siphon is a powerful, self-hosted web application for managing and downloading video content from performer-based sites. It integrates seamlessly with **Stash** to organize your library and supports **Telegram** for notifications.

## Features

- **Performer Scraping:** Automatically finds new videos for tracked performers using `yt-dlp`.
- **Stash Integration:**
    - Checks if videos already exist in your Stash library.
    - Triggers scans and updates metadata (Title, Date, Performer, URL) automatically upon download.
    - Global auto-tagging support.
- **Smart Downloads:**
    - Batch downloading with progress tracking.
    - "Ignore" list to skip unwanted videos.
    - Configurable download directories.
- **Notifications:** Get Telegram alerts for new videos found during scheduled scans.
- **Docker & VPN:** Built-in Docker support with VPN configuration for secure downloading.
- **Modern UI:** Clean, responsive Web GUI built with Flask and HTMX.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- (Optional) Stash instance
- (Optional) Telegram Bot Token

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/siphon.git
    cd siphon
    ```

2.  **Configure Environment:**
    Create a `.env` file (optional, mostly handled via UI settings):
    ```env
    FLASK_APP=run.py
    FLASK_ENV=production
    ```

3.  **Run with Docker:**
    ```bash
    docker-compose up -d
    ```

4.  **Access the UI:**
    Open `http://localhost:5000` in your browser.

## Configuration

Go to the **Settings** page to configure:
- **Stash:** URL, API Key, and Path Mappings.
- **Telegram:** Bot Token and Chat ID.
- **Local Paths:** Download directory and scan targets.
- **Scheduler:** Interval for background scans.

## Development

To run locally without Docker:

1.  Install dependencies:
    ```bash
    uv sync
    ```

2.  Run the app:
    ```bash
    uv run run.py
    ```

## License

MIT
