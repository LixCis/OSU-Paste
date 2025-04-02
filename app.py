from html import escape
from flask import Flask, request, render_template, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
import uuid
import random
import string
from pytz import timezone

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[]
)

MEGABYTE = (2 ** 10) ** 2
app.config['MAX_FORM_MEMORY_SIZE'] = 3 * MEGABYTE  # 3 MB limit
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pastes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

TZ = timezone('Europe/Prague')

class Paste(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    short_id = db.Column(db.String(5), unique=True)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(10), default='text')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(TZ))
    is_private = db.Column(db.Boolean, default=False)
    password = db.Column(db.String(255), nullable=True)

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
        return handle_post_request()
    return render_template('index.html')

@limiter.limit("5 per minute")
def handle_post_request():
    content = request.form['content']

    if len(content) > 3_000_000:
        return render_template('error.html', message="Chyba: Maximální velikost pasty je 3MB!", code=413), 413

    paste_type = 'code' if request.form.get('type') == 'on' else 'text'
    is_private = request.form.get('is_private') == 'on'
    password = request.form.get('password') if is_private else None

    new_paste = Paste(content=content, type=paste_type)
    new_paste.short_id = new_paste.generate_short_id()
    new_paste.is_private = is_private
    new_paste.password = password

    db.session.add(new_paste)
    db.session.commit()

    return redirect(url_for('show_paste', short_id=new_paste.short_id))

@app.route('/<short_id>', methods=['GET', 'POST'])
def show_paste(short_id):
    paste = Paste.query.filter_by(short_id=short_id).first()
    if not paste:
        return render_template('error.html', message="Paste nenalezen", code=404), 404

    created_at = paste.created_at.strftime("%d.%m.%Y %H:%M:%S")

    if paste.is_private:
        if request.method == 'POST':
            password = request.form.get('password')
            if password == paste.password:
                # Heslo správné, zobrazíme paste
                if paste.type == 'code':
                    content = f'<pre class="rounded whitespace-pre-wrap break-words max-w-full"><code class="rounded">{escape(paste.content)}</code></pre>'
                else:
                    content = f'<pre class="rounded whitespace-pre-wrap break-words max-w-full">{escape(paste.content)}</pre>'
                return render_template('paste.html', content=content, short_id=short_id, created_at=created_at)

            else:
                # Nesprávné heslo, zobrazíme chybovou hlášku
                return render_template('paste.html', short_id=short_id, created_at=created_at, error="Nesprávné heslo.")

        return render_template('paste_password.html', short_id=short_id)  # Stránka pro zadání hesla

    # Pokud paste není soukromé, zobrazíme jej bez hesla
    if paste.type == 'code':
        content = f'<pre class="rounded whitespace-pre-wrap break-words max-w-full"><code class="rounded">{escape(paste.content)}</code></pre>'
    else:
        content = f'<pre class="rounded whitespace-pre-wrap break-words max-w-full">{escape(paste.content)}</pre>'

    return render_template('paste.html', content=content, short_id=short_id, created_at=created_at)

@app.errorhandler(413)
def request_entity_too_large(e):
    return render_template('error.html', message="Chyba: Příliš velký požadavek! Maximální velikost pasty jsou 3MB (3000000 znaků).", code=413), 413

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return render_template('error.html', message="Překročený limit požadavků! Zkuste to za chvíli znovu.", code=429), 429

if __name__ == '__main__':
    app.run(debug=True)
