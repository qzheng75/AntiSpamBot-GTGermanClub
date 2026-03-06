"""
AntiSpamBot - GroupMe Bot for Fighting Spam
Fixed version with improved error handling and diagnostics
"""

import json
import os
import requests
import logging
from dotenv import load_dotenv
from typing import Optional, Dict, List, Any

# Load environment variables
load_dotenv()

# Setup logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration
API_ROOT = 'https://api.groupme.com/v3/'
GROUPME_TOKEN = os.environ.get('GROUPME_TOKEN')

# List of spam keywords/patterns to watch for
SPAM_KEYWORDS = [
    'viagra',
    'casino',
    'lottery',
    'click here',
    'free money',
    # Add more as needed
]

# Whitelist of users who can never be kicked
WHITELIST = []  # Add user IDs who should never be kicked


def log_debug(message: str, data: Any = None):
    """Log debug information"""
    if data:
        logger.info(f"DEBUG: {message} - {json.dumps(data, default=str)}")
    else:
        logger.info(f"DEBUG: {message}")


def log_error(message: str, error: Exception = None):
    """Log errors"""
    if error:
        logger.error(f"ERROR: {message} - {type(error).__name__}: {str(error)}")
    else:
        logger.error(f"ERROR: {message}")


def is_spam(text: str) -> bool:
    """Check if message is spam"""
    if not text:
        return False
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SPAM_KEYWORDS)


def get_memberships(group_id: str, token: str) -> List[Dict[str, Any]]:
    """
    Get list of members in a group
    
    Args:
        group_id: GroupMe group ID
        token: GroupMe API token
    
    Returns:
        List of member objects with membership_id and user_id
    
    Raises:
        ValueError: If API response is invalid
        requests.RequestException: If API request fails
    """
    
    try:
        url = f'{API_ROOT}groups/{group_id}'
        log_debug(f"Fetching members from {url}")
        
        # Log token info (first 8 chars only for security)
        token_preview = token[:8] + '...' if token and len(token) > 20 else 'NO TOKEN'
        log_debug(f"Using token: {token_preview}")
        
        if not token:
            raise ValueError("Token is empty!")
        
        response = requests.get(
            url,
            params={'token': token},
            timeout=10
        )
        
        log_debug(f"API Response Status: {response.status_code}")
        
        # Check for HTTP errors
        if response.status_code != 200:
            log_error(f"API returned status {response.status_code}")
            log_debug(f"Response text: {response.text}")
            if response.status_code == 401:
                log_error("401 Unauthorized - Token is invalid or expired!")
                log_error("Verify GROUPME_TOKEN environment variable is set correctly")
            response.raise_for_status()
        
        # Parse JSON
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            log_error(f"Failed to parse JSON response", e)
            raise ValueError(f"Invalid JSON response: {response.text}")
        
        log_debug(f"Raw API response keys: {list(data.keys())}")
        
        # Handle different response formats
        # Format 1: Traditional wrapper with 'response' key
        if 'response' in data:
            response_obj = data['response']
            if isinstance(response_obj, dict) and 'members' in response_obj:
                members = response_obj['members']
                log_debug(f"Found {len(members)} members (format: response.members)")
                return members
            else:
                log_error("'response' key exists but no 'members' found")
                log_debug(f"'response' contents: {response_obj}")
                raise ValueError("'members' not found in response object")
        
        # Format 2: Direct members key (if API changed)
        elif 'members' in data:
            members = data['members']
            log_debug(f"Found {len(members)} members (format: direct)")
            return members
        
        # Format 3: Data is members directly
        elif isinstance(data, list):
            log_debug(f"Found {len(data)} members (format: direct list)")
            return data
        
        # Unknown format
        else:
            log_error(f"Unexpected response format. Keys: {list(data.keys())}")
            log_debug(f"Full response: {json.dumps(data, indent=2)}")
            raise ValueError(f"Unexpected API response structure. Expected 'response' or 'members' key, got: {list(data.keys())}")
    
    except requests.RequestException as e:
        log_error(f"Request failed", e)
        raise
    except Exception as e:
        log_error(f"Unexpected error in get_memberships", e)
        raise


def get_membership_id(group_id: str, user_id: str, token: str) -> Optional[str]:
    """
    Get membership ID for a user in a group
    
    Args:
        group_id: GroupMe group ID
        user_id: GroupMe user ID
        token: GroupMe API token
    
    Returns:
        Membership ID string, or None if not found
    """
    
    try:
        members = get_memberships(group_id, token)
        
        # Find member with matching user_id
        for member in members:
            # Try different possible ID field names
            member_id = member.get('user_id') or member.get('id')
            
            if member_id == user_id:
                # Return membership_id (the actual ID needed for kicking)
                membership_id = member.get('membership_id') or member.get('id')
                log_debug(f"Found membership_id {membership_id} for user {user_id}")
                return membership_id
        
        log_debug(f"User {user_id} not found in group")
        return None
    
    except Exception as e:
        log_error(f"Error getting membership_id for user {user_id}", e)
        return None


def kick_user(group_id: str, user_id: str, token: str) -> bool:
    """
    Remove a user from a group
    
    Args:
        group_id: GroupMe group ID
        user_id: GroupMe user ID to kick
        token: GroupMe API token
    
    Returns:
        True if successful, False otherwise
    """
    
    # Check whitelist
    if user_id in WHITELIST:
        log_debug(f"User {user_id} is whitelisted, not kicking")
        return False
    
    try:
        # Get membership ID
        membership_id = get_membership_id(group_id, user_id, token)
        
        if not membership_id:
            log_error(f"Could not find membership_id for user {user_id}")
            return False
        
        # Kick user
        url = f'{API_ROOT}groups/{group_id}/members/{membership_id}/remove'
        log_debug(f"Kicking user at {url}")
        
        response = requests.post(
            url,
            params={'token': token},
            timeout=10
        )
        
        log_debug(f"Kick response status: {response.status_code}")
        
        if response.status_code in [200, 204]:
            logger.info(f"Successfully kicked user {user_id} from group {group_id}")
            return True
        else:
            log_error(f"Kick failed with status {response.status_code}")
            log_debug(f"Response: {response.text}")
            return False
    
    except Exception as e:
        log_error(f"Error kicking user {user_id}", e)
        return False


def receive(event, context):
    """
    Main Lambda handler
    
    Args:
        event: Lambda event (contains the GroupMe webhook payload)
        context: Lambda context
    
    Returns:
        HTTP response dict
    """
    
    try:
        log_debug("Received webhook event")
        
        # IMPORTANT: Check if token is set
        if not GROUPME_TOKEN:
            log_error("GROUPME_TOKEN environment variable not set!")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'GROUPME_TOKEN not configured'})
            }
        
        # Parse the message
        try:
            if isinstance(event.get('body'), str):
                message = json.loads(event['body'])
            else:
                message = event.get('body', {})
        except json.JSONDecodeError as e:
            log_error(f"Failed to parse message body", e)
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON'})
            }
        
        log_debug("Parsed message", {
            'user_id': message.get('user_id'),
            'group_id': message.get('group_id'),
            'text': message.get('text', '')[:50]
        })
        
        # Validate required fields
        if not message.get('group_id') or not message.get('user_id'):
            log_error("Message missing required fields (group_id or user_id)")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing required fields'})
            }
        
        # Check for spam
        text = message.get('text', '')
        if is_spam(text):
            logger.info(f"Spam detected from {message.get('name')} in group {message['group_id']}")
            log_debug(f"Spam message: {text}")
            
            # Attempt to kick user
            if kick_user(message['group_id'], message['user_id'], GROUPME_TOKEN):
                return {
                    'statusCode': 200,
                    'body': json.dumps({'status': 'user_kicked'})
                }
            else:
                logger.warning(f"Failed to kick user {message['user_id']}")
                return {
                    'statusCode': 200,
                    'body': json.dumps({'status': 'spam_detected_but_kick_failed'})
                }
        
        # Not spam, pass through
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'ok'})
        }
    
    except Exception as e:
        log_error(f"Unhandled exception in receive handler", e)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }


# Allow importing functions for testing
__all__ = ['receive', 'kick_user', 'get_membership_id', 'get_memberships']