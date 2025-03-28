from html import escape
from flask import Flask, request, render_template, redirect, url_for, g, Request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid
import random
import string

class CustomRequest(Request):
    def __init__(self, *args, **kwargs):
        super(CustomRequest, self).__init__(*args, **kwargs)
        self.max_form_parts = 50000000

app = Flask(__name__)
MEGABYTE = (2 ** 10) ** 2
app.config['MAX_CONTENT_LENGTH'] = None
app.config['MAX_FORM_MEMORY_SIZE'] = 50 * MEGABYTE
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pastes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Paste(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    short_id = db.Column(db.String(5), unique=True)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(10), default='text')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def generate_short_id(self):
        characters = string.ascii_letters + string.digits
        while True:
            short_id = ''.join(random.choice(characters) for _ in range(5))
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
        paste_type = 'code' if request.form.get('type') == 'on' else 'text'

        new_paste = Paste(content=content, type=paste_type)
        new_paste.short_id = new_paste.generate_short_id()

        db.session.add(new_paste)
        db.session.commit()
        return redirect(url_for('show_paste', short_id=new_paste.short_id))

    return render_template('index.html')

@app.route('/<short_id>')
def show_paste(short_id):
    paste = Paste.query.filter_by(short_id=short_id).first()
    if not paste:
        return "Paste nenalezen", 404

    created_at = paste.created_at.strftime("%d.%m.%Y %H:%M:%S")

    if paste.type == 'code':
        content = f'<pre class="bg-base-100 rounded whitespace-pre-wrap break-words max-w-full"><code class="rounded">{escape(paste.content)}</code></pre>'
    else:
        content = f'<pre class="bg-base-100 rounded whitespace-pre-wrap break-words max-w-full">{escape(paste.content)}</pre>'

    return render_template(
        'paste.html',
        content=content,
        short_id=short_id,
        created_at=created_at
    )

if __name__ == '__main__':
    app.run(debug=True)
