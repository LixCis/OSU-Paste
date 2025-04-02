from html import escape

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, render_template, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta
import uuid
import random
import string
from pytz import timezone
from collections import defaultdict
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="redis://localhost:6379",
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window",
)

MEGABYTE = (2 ** 10) ** 2
MAX_DB_SIZE = 7 * MEGABYTE * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = 3 * MEGABYTE
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pastes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

TZ = timezone('Europe/Prague')
failed_logins = defaultdict(list)

class Paste(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    short_id = db.Column(db.String(5), unique=True)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(10), default='text')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(TZ))
    expiration_date = db.Column(db.DateTime, nullable=False)
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

def get_db_size():
    db_path = os.path.join(app.instance_path, 'pastes.db')
    return os.path.getsize(db_path)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if get_db_size() >= MAX_DB_SIZE:
            error_message = "Chyba: Databáze dosáhla maximální velikosti. Nový paste nemůže být uložen."
            return render_template('index.html', error_message=error_message)

        return handle_post_request()
    return render_template('index.html')

@limiter.limit("5 per minute")
def handle_post_request():
    content = request.form['content']

    db_path = os.path.join(app.instance_path, 'pastes.db')
    current_db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    new_paste_size = len(content.encode('utf-8'))
    available_space = MAX_DB_SIZE - current_db_size

    if len(content) > 3_000_000:
        return render_template('error.html', message="Chyba: Maximální velikost paste jsou 3MB!", code=413), 413

    if new_paste_size > available_space:
        return render_template('error.html', message="Chyba: Nedostatek místa v databázi! Nemůžete uložit tak velký paste.", code=413), 413

    paste_type = 'code' if request.form.get('type') == 'on' else 'text'
    is_private = request.form.get('is_private') == 'on'
    password = request.form.get('password') if is_private else None

    if is_private and not password:
        is_private = False
        password = None

    if password and len(password) > 65:
        return render_template('error.html', message="Chyba: Maximální délka hesla je 64 znaků!", code=400), 400

    hashed_password = generate_password_hash(password) if password else None

    new_paste = Paste(
        content=content,
        type=paste_type,
        expiration_date=datetime.now(TZ) + timedelta(days=7),
    )
    new_paste.short_id = new_paste.generate_short_id()
    new_paste.is_private = is_private
    new_paste.password = hashed_password

    db.session.add(new_paste)
    db.session.commit()

    return redirect(url_for('show_paste', short_id=new_paste.short_id))

@app.route('/<short_id>', methods=['GET', 'POST'])
def show_paste(short_id):
    paste = Paste.query.filter_by(short_id=short_id).first()
    if not paste:
        return render_template('error.html', message="Paste nenalezen", code=404), 404

    created_at = paste.created_at.strftime("%d.%m.%Y %H:%M:%S")
    expiration_date = paste.expiration_date.strftime("%d.%m.%Y %H:%M:%S")

    if paste.expiration_date.astimezone(TZ) < datetime.now(TZ).astimezone(TZ):
        db.session.delete(paste)
        db.session.commit()
        return render_template('error.html', message="Paste expiroval a byl smazán.", code=410), 410

    if paste.is_private:
        ip_address = get_remote_address()
        failed_attempts = failed_logins[ip_address]

        failed_logins[ip_address] = [attempt for attempt in failed_attempts if attempt > datetime.now(TZ) - timedelta(minutes=1)]

        if len(failed_logins[ip_address]) >= 5:
            return render_template('error.html', message="Překročený limit pokusů zadání hesla. Zkuste to za minutu znovu.", code=429), 429

        if request.method == 'POST':
            password = request.form.get('password')
            action = request.form.get('action')

            if action == 'delete':
                if check_password_hash(paste.password, password):
                    db.session.delete(paste)
                    db.session.commit()
                    return render_template('success.html', short_id=paste.short_id)
                else:
                    failed_logins[ip_address].append(datetime.now(TZ))
                    return render_template('paste.html', content=paste.content, short_id=short_id, created_at=created_at, paste=paste, expiration_date=expiration_date, error="Nesprávné heslo pro smazání.")

            if check_password_hash(paste.password, password):
                return render_template('paste.html', content=escape(paste.content), short_id=short_id, created_at=created_at, paste=paste, expiration_date=expiration_date)

            failed_logins[ip_address].append(datetime.now(TZ))
            return render_template('paste_password.html', short_id=short_id, expiration_date=expiration_date, error="Nesprávné heslo pro zobrazení.")

        return render_template('paste_password.html', short_id=short_id, expiration_date=expiration_date)

    return render_template('paste.html', content=escape(paste.content), short_id=short_id, created_at=created_at, paste=paste, expiration_date=expiration_date)

@app.errorhandler(413)
def request_entity_too_large(e):
    return render_template('error.html', message="Chyba: Příliš velký požadavek! Maximální velikost paste jsou 3MB.", code=413), 413

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return render_template('error.html', message="Překročený limit požadavků! Zkuste to za minutu znovu.", code=429), 429

def delete_expired_pastes():
    current_time = datetime.now(TZ)
    expired_pastes = Paste.query.filter(Paste.expiration_date < current_time).all()
    for paste in expired_pastes:
        db.session.delete(paste)
    db.session.commit()

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(delete_expired_pastes, 'interval', hours=1)
scheduler.start()

if __name__ == '__main__':
    app.run(debug=True)
