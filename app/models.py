from app import db
from datetime import datetime

class Performer(db.Model):
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    site = db.Column(db.String(64), nullable=False) # 'pornhub' or 'xhamster'
    type = db.Column(db.String(64), nullable=False) # 'model', 'pornstar', 'creator'
    blacklist_keywords = db.Column(db.Text, nullable=True) # JSON string or comma-separated
    whitelist_keywords = db.Column(db.Text, nullable=True) # JSON string or comma-separated
    scheduled_scan_enabled = db.Column(db.Boolean, default=True)
    auto_download = db.Column(db.Boolean, default=False)
    use_cookies = db.Column(db.Boolean, default=False)
    min_duration = db.Column(db.Integer, default=0) # Minimum duration in minutes
    last_scan = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    videos = db.relationship('Video', backref='performer', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'site': self.site,
            'type': self.type,
            'scheduled_scan_enabled': self.scheduled_scan_enabled,
            'auto_download': self.auto_download
        }

    @property
    def profile_url(self):
        if self.site == 'pornhub':
            if self.type == 'model':
                return f"https://www.pornhub.com/model/{self.id}"
            elif self.type == 'pornstar':
                return f"https://www.pornhub.com/pornstar/{self.id}"
        elif self.site == 'xhamster':
            if self.type == 'creator':
                return f"https://xhamster.com/creators/{self.id}"
            elif self.type == 'pornstar':
                return f"https://xhamster.com/pornstars/{self.id}"
        elif self.site == 'x':
            return f"https://x.com/{self.id}"
        return "#"

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    performer_id = db.Column(db.String(64), db.ForeignKey('performer.id'), nullable=False)
    title = db.Column(db.String(256), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    viewkey = db.Column(db.String(64), nullable=False)
    date = db.Column(db.String(32), nullable=True) # YYYY-MM-DD
    duration = db.Column(db.String(32), nullable=True) # e.g., "10:05"
    media_ids = db.Column(db.Text, nullable=True) # Comma-separated list of media IDs
    status = db.Column(db.String(32), default='new') # 'new', 'downloaded', 'ignored', 'blacklisted'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
