import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "change_this_secret"
    SQLALCHEMY_DATABASE_URI = 'sqlite:///goatmanager.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'your_email@gmail.com'
    MAIL_PASSWORD = 'your_app_password'
    UPLOAD_FOLDER = os.path.join("static", "uploads")
