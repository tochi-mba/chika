from flask import Flask, request
import json

app = Flask(__name__)

@app.route('/chika_api/save_score', methods=['POST'])
def save_score():
    data = request.get_json(force=True)
    score = data.get('score')
    with open('latest_score.json','w') as f:
        json.dump({'score': score}, f)
    return {'status': 'ok', 'saved_score': score}

@app.route('/')
def index():
    return 'Chika Math Server Running'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8010)