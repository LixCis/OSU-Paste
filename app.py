from html import escape

from flask import Flask, request, jsonify, render_template, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid
import random
import string
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pastes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Paste(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    short_id = db.Column(db.String(5), unique=True)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def generate_short_id(self):
        characters = string.ascii_letters + string.digits
        while True:
            short_id = ''.join(random.choice(characters) for i in range(5))
            if Paste.query.filter_by(short_id=short_id).first() is None:
                return short_id

@app.before_request
def before_request():
    if not hasattr(g, 'db_initialized'):
        with app.app_context():
            db.create_all()
            g.db_initialized = True

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        content = request.form['content']
        new_paste = Paste(content=content)
        new_paste.short_id = new_paste.generate_short_id()
        db.session.add(new_paste)
        db.session.commit()
        return redirect(url_for('show_paste', short_id=new_paste.short_id))
    return render_template('index.html')

@app.route('/<short_id>')
def show_paste(short_id):
    paste = Paste.query.filter_by(short_id=short_id).first()
    if paste:
        content = escape(paste.content)
        created_at = paste.created_at.strftime("%Y-%m-%d %H:%M:%S")
        return render_template('paste.html', content=content, short_id=short_id, created_at=created_at)
    return "Paste nenalezen", 404

if __name__ == '__main__':
    app.run(debug=True)
