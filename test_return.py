import sys
import re
sys.path.insert(0, r'C:\Users\aarad\OneDrive\Desktop\LMS')
from app import app

with app.test_client() as client:
    # Test user login
    print("1. GET /user/login:")
    response = client.get("/user/login")
    text = response.get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', text)
    token = match.group(1) if match else None
    print(f"   Has CSRF token: {token is not None}")
    print(f"   Has Return text: {'Return' in text}")

    # Login
    if token:
        print("\n2. POST /user/login:")
        response = client.post(
            "/user/login",
            data=dict(username="TestUser", password="testpass123", csrf_token=token),
            follow_redirects=False,
        )
        print(f"   Status: {response.status_code}, Location: {response.location}")

    # Check dashboard for return functionality
    print("\n3. GET / (dashboard):")
    response = client.get("/", follow_redirects=True)
    text = response.get_data(as_text=True)
    print(f"   Dashboard loaded: {len(text)} chars")
    print(f"   Has 'Returned Books': {'Returned Books' in text}")
    print(f"   Has 'Logout': {'Logout' in text}")

    # Check issues page
    print("\n4. GET /issues:")
    response = client.get("/issues", follow_redirects=True)
    text = response.get_data(as_text=True)
    print(f"   Issues page loaded: {len(text)} chars")
    print(f"   Has 'Return': {'Return' in text}")