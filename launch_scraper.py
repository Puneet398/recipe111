#!/usr/bin/env python3
"""
Recipe Scraper UI Launcher
A simple script to start the Recipe Scraper web interface
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path
from recipe_scraper_s3 import app

def check_dependencies():
    """Check if required packages are installed"""
    # Map package names to their import names
    package_imports = {
        'flask': 'flask',
        'flask-cors': 'flask_cors',
        'requests': 'requests', 
        'beautifulsoup4': 'bs4',
        'openai': 'openai',
        'yt-dlp': 'yt_dlp',
        'boto3': 'boto3',          # Added boto3
        'flask-sqlalchemy': 'flask_sqlalchemy', # Added sqlalchemy
        'flask-login': 'flask_login',     # Added flask-login
        'flask-migrate': 'flask_migrate'  # Added flask-migrate
    }
    
    missing_packages = []
    
    for package, import_name in package_imports.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n💡 Install missing packages with:")
        print(f"   pip install {' '.join(missing_packages)}")
        return False
    
    return True

def check_api_keys():
    """Check if API keys are available"""
    all_keys_found = True
    
    # 1. Check Groq Key (for text scraping)
    groq_key = os.getenv('GROQ_API_KEY')
    if not groq_key:
        print("❌ GROQ_API_KEY environment variable not set (for text scraping)")
        all_keys_found = False
    else:
        print("✅ GROQ_API_KEY found (for text scraping)")

    # 2. Check OpenAI Key (for image scraping)
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        print("❌ OPENAI_API_KEY environment variable not set (for image scraping)")
        all_keys_found = False
    else:
        print("✅ OPENAI_API_KEY found (for image scraping)")

    # 3. Check AWS Keys (for S3 storage)
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_bucket = os.getenv('AWS_S3_BUCKET')

    if not all([aws_access_key, aws_secret_key, aws_bucket]):
        print("❌ AWS S3 environment variables (ID, KEY, or BUCKET) not set (for storage)")
        all_keys_found = False
    else:
        print("✅ AWS S3 configuration found (for storage)")
        
    if not all_keys_found:
        print("\n⚠️  One or more configurations are missing. Please set them in your environment.")
        # We don't exit, as the app itself will raise a specific error
        
    return True


def start_flask_app():
    """Start the Flask application"""
    try:
        
        print("🍳 Starting Recipe Scraper UI...")
        print("📺 Supports YouTube videos, web recipes, and image uploads!")
        print("🌐 Opening browser to: http://localhost:5000")
        print("=" * 50)
        
        # Open browser after a short delay
        def open_browser():
            time.sleep(1.5)
            webbrowser.open('http://localhost:5000')
        
        import threading
        threading.Thread(target=open_browser, daemon=True).start()
        
        # Start Flask app
        app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
        
    except ImportError:
        print("❌ Could not import Flask app")
        print("💡 Make sure 'recipe_scraper_s3.py' is in the same directory")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        sys.exit(1)



def main():
    """Main function"""
    print("🚀 Recipe Scraper UI Launcher")
    print("=" * 40)
    
    # Check current directory
    current_dir = Path.cwd()
    print(f"📁 Working directory: {current_dir}")
    
    # Note: Cannot check S3 recipes from here easily, so this check is removed.
    
    # Check dependencies
    print("\n🔍 Checking dependencies...")
    if not check_dependencies():
        sys.exit(1)
    
    print("✅ All dependencies found")
    
    # Check API key
    print("\n🔑 Checking API configuration...")
    check_api_keys()
    
    # Start the application
    print("\n🎯 Starting application...")
    try:
        start_flask_app()
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
        print("Thanks for using Recipe Scraper!")

if __name__ == "__main__":
    main()