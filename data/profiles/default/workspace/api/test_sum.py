import urllib.request, json, sys

url = 'http://127.0.0.1:8765/sum?a=3&b=4'
r = urllib.request.urlopen(url)
body = r.read().decode()
data = json.loads(body)
print('Response:', body)
assert data.get('sum') == 7, f'Expected 7, got {data.get("sum")}'
print('PASS: sum == 7')
sys.exit(0)
