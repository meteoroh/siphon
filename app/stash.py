import requests
from app.models import Settings
import time
import logging

logger = logging.getLogger(__name__)

class StashClient:
    def _get_config(self):
        url = Settings.query.filter_by(key='stash_url').first()
        api_key = Settings.query.filter_by(key='stash_api_key').first()
        path_mapping = Settings.query.filter_by(key='stash_path_mapping').first()
        
        if not url or not url.value:
            return None, None, None
        
        return url.value, api_key.value if api_key else None, path_mapping.value if path_mapping else None

    def __init__(self):
        self.url, self.api_key, self.path_mapping = self._get_config()
        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["ApiKey"] = self.api_key

    def is_configured(self):
        return bool(self.url)

    def _apply_path_mapping(self, path):
        """Applies path mapping to a local path."""
        if not self.path_mapping:
            return path
            
        # Support multiple mappings separated by newline or semicolon
        mappings = self.path_mapping.replace('\n', ';').split(';')
        
        for mapping in mappings:
            if '=' not in mapping:
                continue
                
            local_prefix, remote_prefix = mapping.split('=', 1)
            local_prefix = local_prefix.strip()
            remote_prefix = remote_prefix.strip()
            
            if path.startswith(local_prefix):
                new_path = path.replace(local_prefix, remote_prefix, 1)
                logger.info(f"Mapped path: {path} -> {new_path}")
                return new_path
                
        return path

    def _post(self, query, variables=None):
        if not self.url:
            raise Exception("Stash URL not configured")
            
        try:
            response = requests.post(self.url, json={'query': query, 'variables': variables}, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error querying Stash: {e}")
            return None

    def test_connection(self):
        if not self.url:
            return False, "Stash URL not configured."
        
        query = "{ version { version } }"
        data = self._post(query)
        
        if data and 'data' in data and 'version' in data['data']:
            return True, f"Connected to Stash v{data['data']['version']['version']}"
        else:
            return False, "Invalid response from Stash."

    def check_video_exists(self, url, title, viewkey=None, alternative_ids=None):
        if not self.url:
            return False

        # 1. Check by URL (Exact Match)
        query_url = """
        query FindSceneByUrl($url: String!) {
          findScenes(scene_filter: {
            url: {value: $url, modifier: EQUALS}
          }) {
            count
          }
        }
        """
        data = self._post(query_url, {'url': url})
        if data and 'data' in data and 'findScenes' in data['data'] and data['data']['findScenes']['count'] > 0:
            return True

        # 2. Check by Viewkey/Title (Path Match)
        search_terms = []
        if viewkey:
            search_terms.append(viewkey)
        
        if alternative_ids:
            search_terms.extend(alternative_ids)
            
        if not search_terms and title:
            search_terms.append(title)
            
        if not search_terms:
            return False
            
        query_path = """
        query FindSceneByPath($path: String!) {
          findScenes(scene_filter: {
            path: {value: $path, modifier: INCLUDES}
          }) {
            count
          }
        }
        """
        
        for term in search_terms:
            data = self._post(query_path, {'path': term})
            if data and 'data' in data and 'findScenes' in data['data'] and data['data']['findScenes']['count'] > 0:
                return True
            
        return False

    def scan_file(self, path):
        """Triggers a metadata scan for a specific file path."""
        if not self.url:
            return False
            
        # Path Mapping Logic
        path = self._apply_path_mapping(path)
            
        query = """
        mutation MetadataScan($paths: [String!]) {
          metadataScan(input: {paths: $paths, scanGenerateCovers: true})
        }
        """
        # Stash expects a list of paths
        data = self._post(query, {'paths': [path]})
        if data and 'data' in data and 'metadataScan' in data['data']:
            return data['data']['metadataScan'] # Returns Job ID
        return None

    def auto_tag(self, path=None):
        """Triggers auto-tagging. If path is None, tags all files."""
        if not self.url:
            return False
            
        variables = {
            'performers': ["*"],
            'studios': ["*"],
            'tags': ["*"]
        }
        
        if path:
            # Path Mapping Logic
            path = self._apply_path_mapping(path)
            variables['paths'] = [path]
        else:
            variables['paths'] = None
            
        query = """
        mutation MetadataAutoTag($paths: [String!], $performers: [String!], $studios: [String!], $tags: [String!]) {
          metadataAutoTag(input: {paths: $paths, performers: $performers, studios: $studios, tags: $tags})
        }
        """
        data = self._post(query, variables)
        return data is not None

    def wait_for_job(self, job_id, timeout=30):
        """Waits for a Stash job to complete."""
        if not self.url or not job_id:
            return False
            
        query = """
        query FindJob($id: ID!) {
          findJob(input: {id: $id}) {
            status
          }
        }
        """
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            data = self._post(query, {'id': job_id})
            if data and 'data' in data and 'findJob' in data['data']:
                status = data['data']['findJob']['status']
                if status == 'FINISHED':
                    return True
                elif status in ['FAILED', 'CANCELLED']:
                    return False
            time.sleep(1)
            
        return False

    def find_scene_by_path(self, path):
        """Finds a scene ID by its file path or viewkey."""
        if not self.url:
            return None
            
        # Optimization: Extract viewkey if present in filename [viewkey]
        # This is much more robust than searching for the full filename which might have special chars
        import re
        search_term = path
        viewkey_match = re.search(r'\[([a-zA-Z0-9\-_]+)\]', path)
        if viewkey_match:
            search_term = viewkey_match.group(1)
            logger.debug(f"Searching Stash by viewkey: {search_term}")
        
        query = """
        query FindSceneIdByPath($path: String!) {
          findScenes(scene_filter: {
            path: {value: $path, modifier: INCLUDES}
          }) {
            scenes {
              id
              files {
                path
              }
            }
          }
        }
        """
        data = self._post(query, {'path': search_term})
        if data and 'data' in data and 'findScenes' in data['data']:
            scenes = data['data']['findScenes']['scenes']
            
            # If we searched by viewkey, we might get multiple results (unlikely but possible)
            # We should try to match the filename if possible, but if we only have one result, it's probably it.
            if len(scenes) == 1:
                return scenes[0]['id']
                
            for scene in scenes:
                # Double check if any file path matches exactly or ends with our path
                for f in scene.get('files', []):
                    if f['path'] == path or f['path'].endswith(path):
                        return scene['id']
                    # Also check if viewkey is in the path
                    if viewkey_match and viewkey_match.group(1) in f['path']:
                         return scene['id']
                         
        return None

    def find_performer(self, name):
        """Finds a performer ID by name."""
        if not self.url or not name:
            return None
            
        query = """
        query FindPerformerByName($name: String!) {
          findPerformers(performer_filter: {
            name: {value: $name, modifier: EQUALS}
          }) {
            performers {
              id
              name
            }
          }
        }
        """
        data = self._post(query, {'name': name})
        if data and 'data' in data and 'findPerformers' in data['data']:
            performers = data['data']['findPerformers']['performers']
            if performers:
                return performers[0]['id']
        return None

    def scrape_scene(self, scene_id):
        """Scrapes a scene using builtin_autotag."""
        if not self.url or not scene_id:
            return None
            
        query = """
        query ScrapeSingleScene($source: ScraperSourceInput!, $input: ScrapeSingleSceneInput!) {
          scrapeSingleScene(source: $source, input: $input) {
            title
            tags {
              stored_id
              name
            }
            performers {
              stored_id
              name
            }
            studio {
              stored_id
              name
            }
          }
        }
        """
        
        variables = {
            'source': {
                'scraper_id': 'builtin_autotag'
            },
            'input': {
                'scene_id': scene_id
            }
        }
        
        data = self._post(query, variables)
        if data and 'data' in data and 'scrapeSingleScene' in data['data']:
            # scrapeSingleScene returns a LIST of results
            results = data['data']['scrapeSingleScene']
            if results:
                return results[0]
        return None

    def update_scene(self, scene_id, video_data):
        """Updates scene metadata."""
        if not self.url or not scene_id:
            return False
            
        query = """
        mutation SceneUpdate($input: SceneUpdateInput!) {
          sceneUpdate(input: $input) {
            id
          }
        }
        """
        
        # We need to construct the input object properly
        scene_input = {
            'id': scene_id
        }
        if video_data.get('title'): scene_input['title'] = video_data['title']
        if video_data.get('url'): scene_input['url'] = video_data['url']
        if video_data.get('description'): scene_input['details'] = video_data['description']
        if video_data.get('date'): scene_input['date'] = video_data['date']
        if video_data.get('performer_ids'): scene_input['performer_ids'] = video_data['performer_ids']
        if video_data.get('tag_ids'): scene_input['tag_ids'] = video_data['tag_ids']
        if video_data.get('studio_id'): scene_input['studio_id'] = video_data['studio_id']
        
        data = self._post(query, {'input': scene_input})
        return data is not None


# Wrapper functions for backward compatibility
def get_stash_config():
    client = StashClient()
    return client.url, client.api_key

def check_stash_video(url, title, viewkey=None, alternative_ids=None):
    client = StashClient()
    return client.check_video_exists(url, title, viewkey, alternative_ids)

def test_stash_connection():
    client = StashClient()
    return client.test_connection()
