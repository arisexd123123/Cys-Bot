
import json
import os
import datetime

# File to store collected keys
KEYS_FILE = "collected_keys.json"

def initialize_keys_file():
    """Initialize keys file if it doesn't exist"""
    if not os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'w') as f:
            json.dump([], f)

def save_key(key, user_id=None, username=None, source=None):
    """Save a detected key"""
    initialize_keys_file()
    
    # Load existing keys
    try:
        with open(KEYS_FILE, 'r') as f:
            keys = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        keys = []
    
    # Check if key already exists
    for existing_key in keys:
        if existing_key.get('key') == key:
            # Update existing key entry
            existing_key['count'] = existing_key.get('count', 1) + 1
            existing_key['last_seen'] = datetime.datetime.now().isoformat()
            
            # Save updated keys
            with open(KEYS_FILE, 'w') as f:
                json.dump(keys, f, indent=2)
            
            return False  # Not a new key
    
    # Add new key entry
    key_entry = {
        'key': key,
        'user_id': user_id,
        'username': username,
        'source': source,
        'timestamp': datetime.datetime.now().isoformat(),
        'count': 1
    }
    
    keys.append(key_entry)
    
    # Save updated keys
    with open(KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=2)
    
    return True  # New key

def get_all_keys():
    """Get all saved keys"""
    initialize_keys_file()
    
    try:
        with open(KEYS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []
