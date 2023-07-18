import sys
import requests
import json
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader

access_token = sys.argv[1]

two_weeks_ago = datetime.now() - timedelta(weeks=2)
two_weeks_ago_str = two_weeks_ago.strftime('%Y-%m-%d')

queries = [
    'topic:game',
    'topic:godot',
    'topic:love',
    'topic:löve',
    'topic:love2d',
    'topic:sdl2',
    'topic:"sdl port"',
    'topic:"sdl2 port"'
]

repos = []

for query in queries:
    url = f'https://api.github.com/search/repositories?q={query} created:>{two_weeks_ago_str}&sort=stars&order=desc'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {access_token}'
    }
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Request failed with status code {response.status_code}")
        continue

    data = json.loads(response.text)

    if 'items' not in data:
        print(f"Unexpected response from GitHub API: {data}")
        continue
    
    repos.extend([
        {
            'name': repo['name'], 
            'url': repo['html_url'], 
            'stars': repo['stargazers_count'], 
            'description': repo['description'] or "No description provided.",
            'created_at': datetime.strptime(repo['created_at'], "%Y-%m-%dT%H:%M:%SZ").date()
        } for repo in data['items']
    ])

env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')

with open('index.html', 'w') as f:
    f.write(template.render(repos=repos))

