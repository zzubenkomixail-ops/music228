import os
from flask import Flask

app = Flask(name)

@app.route('/')
def home():
    return "Bot is running!"

if name == "main":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
