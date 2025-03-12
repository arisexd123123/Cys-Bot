
import random
import string
import json
import datetime
import os

# File to store generated keys
GENERATED_KEYS_FILE = "generated_keys.json"
REDEEMED_KEYS_FILE = "redeemed_keys.json"

def initialize_key_files():
    """Initialize key files if they don't exist"""
    for file_path in [GENERATED_KEYS_FILE, REDEEMED_KEYS_FILE]:
        if not os.path.exists(file_path):
            with open(file_path, 'w') as f:
                json.dump([], f)
            print(f"Created new file: {file_path}")
        else:
            # Validate the file contains valid JSON
            try:
                with open(file_path, 'r') as f:
                    json.load(f)
            except json.JSONDecodeError:
                # Reset corrupted file
                with open(file_path, 'w') as f:
                    json.dump([], f)
                print(f"Reset corrupted file: {file_path}")

def generate_key(length=16, prefix="KEY-"):
    """Generate a unique license key"""
    # Use stronger randomness
    random.seed(os.urandom(16))
    
    # Generate random characters
    characters = string.ascii_uppercase + string.digits
    random_chars = ''.join(random.choice(characters) for _ in range(length))
    
    # Format the key with prefix and dashes for readability
    parts = [random_chars[i:i+4] for i in range(0, len(random_chars), 4)]
    formatted_key = prefix + '-'.join(parts)
    
    return formatted_key

def save_generated_key(key, key_type="standard", expires_in_days=None, max_uses=1, created_by=None):
    """Save a generated key with metadata"""
    initialize_key_files()
    
    # Load existing keys
    try:
        with open(GENERATED_KEYS_FILE, 'r') as f:
            keys = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        keys = []
    
    # Check if key already exists
    for existing_key in keys:
        if existing_key.get('key') == key:
            return False, "Key already exists"
    
    # Set expiration date if specified
    expiration_date = None
    if expires_in_days is not None:
        expiration_date = (datetime.datetime.now() + 
                          datetime.timedelta(days=expires_in_days)).isoformat()
    
    # Add new key with metadata
    key_entry = {
        'key': key,
        'type': key_type,
        'created_at': datetime.datetime.now().isoformat(),
        'created_by': created_by,
        'expires_at': expiration_date,
        'max_uses': max_uses,
        'uses_remaining': max_uses,
        'redeemed_by': []
    }
    
    keys.append(key_entry)
    
    # Save updated list
    with open(GENERATED_KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=2)
    
    return True, key_entry

def redeem_key(key, user_id, username=None):
    """Redeem a key for a user"""
    initialize_key_files()
    
    # Clean up input key (remove any extra spaces or formatting)
    key = key.strip()
    
    # Check if user provided a valid key
    if not key:
        return False, "Please provide a valid key"
    
    # Load existing keys
    try:
        with open(GENERATED_KEYS_FILE, 'r') as f:
            generated_keys = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"Error loading generated keys file: {GENERATED_KEYS_FILE}")
        return False, "No keys available - system error"
        
    # Load redeemed keys
    try:
        with open(REDEEMED_KEYS_FILE, 'r') as f:
            redeemed_keys = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"Error loading redeemed keys file: {REDEEMED_KEYS_FILE}")
        redeemed_keys = []
    
    # Look for the key
    key_found = False
    key_entry = None
    
    for i, entry in enumerate(generated_keys):
        if entry.get('key') == key:
            key_found = True
            key_entry = entry
            
            # Check if expired
            if entry.get('expires_at'):
                expiry_date = datetime.datetime.fromisoformat(entry['expires_at'])
                if datetime.datetime.now() > expiry_date:
                    return False, "Key has expired"
            
            # Check if uses remaining
            if entry.get('uses_remaining', 0) <= 0:
                return False, "Key has no uses remaining"
                
            # Check if user already redeemed
            if user_id in [r.get('user_id') for r in entry.get('redeemed_by', [])]:
                return False, "You have already redeemed this key"
                
            # Update the key use
            redemption = {
                'user_id': user_id,
                'username': username,
                'redeemed_at': datetime.datetime.now().isoformat()
            }
            
            # Add to redeemed list
            entry['redeemed_by'].append(redemption)
            
            # Decrease uses remaining
            entry['uses_remaining'] = entry.get('uses_remaining', 1) - 1
            
            # Add to redeemed keys file
            redeemed_entry = {
                'key': key,
                'user_id': user_id,
                'username': username,
                'redeemed_at': datetime.datetime.now().isoformat(),
                'key_type': entry.get('type', 'standard')
            }
            redeemed_keys.append(redeemed_entry)
            
            break
    
    if not key_found:
        return False, "Invalid key"
    
    # Save updated lists
    with open(GENERATED_KEYS_FILE, 'w') as f:
        json.dump(generated_keys, f, indent=2)
        
    with open(REDEEMED_KEYS_FILE, 'w') as f:
        json.dump(redeemed_keys, f, indent=2)
    
    return True, key_entry

def get_all_generated_keys():
    """Get all generated keys"""
    initialize_key_files()
    
    try:
        with open(GENERATED_KEYS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def get_all_redeemed_keys():
    """Get all redeemed keys"""
    initialize_key_files()
    
    try:
        with open(REDEEMED_KEYS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def get_keys_for_user(user_id):
    """Get all keys redeemed by a specific user"""
    redeemed_keys = get_all_redeemed_keys()
    user_keys = [key for key in redeemed_keys if key.get('user_id') == user_id]
    return user_keys

def test_key_system():
    """Test if the key system is working correctly"""
    try:
        # Initialize files
        initialize_key_files()
        
        # Generate a test key
        test_key = generate_key()
        
        # Save the test key
        save_result = save_generated_key(test_key, key_type="test", max_uses=1)
        
        # Get all keys
        all_keys = get_all_generated_keys()
        
        return {
            "status": "success",
            "test_key": test_key,
            "save_result": save_result,
            "key_count": len(all_keys)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# Run a quick test when module is loaded
if __name__ == "__main__":
    print("Testing key system...")
    test_result = test_key_system()
    print(f"Test result: {test_result}")
