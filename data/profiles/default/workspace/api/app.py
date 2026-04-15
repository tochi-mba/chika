from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/sum')
def sum_endpoint():
    try:
        a = float(request.args.get('a'))
        b = float(request.args.get('b'))
    except (TypeError, ValueError):
        return jsonify({'error': 'a and b must be valid numbers'}), 400
    result = a + b
    if result == int(result):
        result = int(result)
    return jsonify({'sum': result})

if __name__ == '__main__':
    app.run(port=8765)
