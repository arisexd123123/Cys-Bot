
import os
import json
import time
import base64
import hashlib
import requests
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")  # format: username/repo
BACKUP_INTERVAL = 3600  # seconds between backups (default: 1 hour)

# Files to backup
FILES_TO_BACKUP = [
    "generated_keys.json",
    "redeemed_keys.json",
    "key_manager.py",
    "key_system.py",
    "warns.json",
    "levels.json",
    "ticket_stats.json",
    "automod_settings.json",
    "blacklisted_words.json"
]

def encrypt_filename(filename):
    """Simple obfuscation of filenames in the repo"""
    hash_obj = hashlib.md5(filename.encode())
    return f"data_{hash_obj.hexdigest()[:8]}.json"

def backup_file(filename):
    """Backup a single file to GitHub repo"""
    if not os.path.exists(filename):
        print(f"File {filename} does not exist, skipping")
        return False
    
    # Read the file content
    try:
        with open(filename, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return False
    
    # Encrypt the filename for storage
    encrypted_name = encrypt_filename(filename)
    
    # Create or update the file in GitHub
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{encrypted_name}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # First check if file exists to get the SHA
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        # File exists, get SHA for update
        sha = response.json()["sha"]
        data = {
            "message": f"Update {encrypted_name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(content.encode()).decode(),
            "sha": sha
        }
    else:
        # File doesn't exist, create it
        data = {
            "message": f"Create {encrypted_name} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(content.encode()).decode()
        }
    
    # Send the request
    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        print(f"Successfully backed up {filename} to {encrypted_name}")
        return True
    else:
        print(f"Error backing up {filename}: {response.status_code} - {response.text}")
        return False

def run_backup():
    """Backup all files to GitHub repo"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("Error: GitHub token or repo not configured. Please set GITHUB_TOKEN and GITHUB_REPO environment variables.")
        return False
    
    success_count = 0
    for filename in FILES_TO_BACKUP:
        if backup_file(filename):
            success_count += 1
    
    # Create a backup record with timestamp
    backup_record = {
        "timestamp": datetime.now().isoformat(),
        "files_backed_up": success_count,
        "total_files": len(FILES_TO_BACKUP)
    }
    
    # Save the backup record
    backup_record_file = "backup_record.json"
    try:
        if os.path.exists(backup_record_file):
            with open(backup_record_file, 'r') as f:
                records = json.load(f)
        else:
            records = []
        
        records.append(backup_record)
        
        with open(backup_record_file, 'w') as f:
            json.dump(records, f, indent=2)
    except Exception as e:
        print(f"Error updating backup record: {e}")
    
    print(f"Backup completed: {success_count}/{len(FILES_TO_BACKUP)} files backed up successfully")
    return success_count > 0

def start_backup_loop():
    """Start a loop to periodically backup files"""
    print(f"Starting GitHub backup service - will backup every {BACKUP_INTERVAL} seconds")
    while True:
        print(f"Running backup at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        run_backup()
        print(f"Next backup scheduled at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(BACKUP_INTERVAL)

if __name__ == "__main__":
    # Run a single backup when script is called directly
    run_backup()
