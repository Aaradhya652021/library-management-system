import sys
import re
sys.path.insert(0, r'C:\Users\aarad\OneDrive\Desktop\LMS')
from app import app

# Find the issue_return function
with open('C:\\Users\\aarad\\OneDrive\\Desktop\\LMS\\app.py') as f:
    content = f.read()

# Find the issue_return function
match = re.search(r'def issue_return\(.*?return redirect\(url_for\("([^"]+)"\).*?\)', content, re.DOTALL)
if match:
    print('Found redirect in issue_return to:', match.group(1))
else:
    print('No redirect to user_dashboard found')
    
# Check what endpoints exist
print('Registered endpoints:')
for rule in app.url_map.iter_rules():
    if rule.endpoint and 'issue_return' in rule.endpoint:
        print(f'  {rule.endpoint}: {rule}')