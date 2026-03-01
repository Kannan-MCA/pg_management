import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import app

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'pg-management-super-secret-2026'
    # ✅ CORRECT SQLite URL format: sqlite:///filename.db (relative path)
    SQLALCHEMY_DATABASE_URI = 'sqlite:///pg_management.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class DevelopmentConfig(Config):
    DEBUG = True

# Add to app config (top section)
UPLOAD_FOLDER = 'static/uploads/rooms'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS