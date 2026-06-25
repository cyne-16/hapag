from flask import Flask
from pymongo import MongoClient
from dotenv import load_dotenv
from flask_login import LoginManager
import os
import certifi

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  

# Connect to MongoDB Atlas
import certifi
client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
db = client["hapag"]  # This creates a database called "hapag"

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # Redirect to login if not logged in

# Import routes (we'll create these next)
from routes import *

if __name__ == "__main__":
    app.run(debug=True)