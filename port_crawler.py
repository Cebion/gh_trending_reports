import sys
import requests
import json
import os
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader

# Get the GitHub access token from environment variables
access_token = os.getenv("GH_TOKEN")

# Calculate the date two weeks ago
two_weeks_ago = datetime.now() - timedelta(weeks=2)
two_weeks_ago_str = two_weeks_ago.strftime('%Y-%m-%d')

# Create a list of search queries
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

# Prepare data for the HTML template
repos = []

# For each search query, make a GET request to the GitHub API
for query in queries:
    url = f'https://api.github.com/search/repositories?q={query} created:>{two_weeks_ago_str}&sort=stars&order=desc'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {access_token}'  # Include the access token here
    }
    response = requests.get(url, headers=headers)

    # Check if the request was successful
    if response.status_code != 200:
        print(f"Request failed with status code {response.status_code}")
        continue

    # Parse the JSON response
    data = json.loads(response.text)

    # Check if 'items' is in the response
    if 'items' not in data:
        print(f"Unexpected response from GitHub API: {data}")
        continue
    
    # Add the results to our list of repos
    repos.extend([
        {
            'name': repo['name'], 
            'url': repo['html_url'], 
            'stars': repo['stargazers_count'], 
            'description': repo['description'] or "No description provided.",
            'creation_date': repo['created_at']  # Add the creation date
        } for repo in data['items']
    ])

# Load the Jinja2 template
env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')

# Render the template with the data and write it to an HTML file
with open('index.html', 'w') as f:
    f.write(template.render(repos=repos))
