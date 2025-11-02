# **Churro's Recipe Scraper 🍳**

A web application built with Flask to scrape recipes from websites and YouTube videos, extract key information using AI, and store them in a user-specific S3 bucket. Includes a web interface for managing recipes and user accounts.

## **Features**

* **URL Scraping:** Enter a URL (website or YouTube) to scrape recipe content.  
* **YouTube Transcript Extraction:** Automatically extracts transcripts from YouTube videos using yt-dlp.  
* **Photo OCR:** Upload a photo of a recipe, and client-side Tesseract.js extracts the text.  
* **AI Parsing (Groq):** Uses an AI model (via Groq API) to parse scraped text or OCR output into a structured recipe format (ingredients, method) with metric conversions.  
* **S3 Storage:** Saves the final Markdown recipe content to an AWS S3 bucket, organized by user ID.  
* **Web Interface:** A simple, responsive UI to add, view, edit, and delete recipes.  
* **User Authentication:** Supports multiple users with different roles (Admin, Family, User). Recipes are specific to each user.  
* **Admin Dashboard:** Provides an overview of users, total recipes, and usage analytics (requires Admin role).

## **Technology Stack**

* **Backend:** Python, Flask  
* **Database:** PostgreSQL (using Flask-SQLAlchemy and Flask-Migrate)  
* **Storage:** AWS S3 (using Boto3)  
* **AI:** Groq API (via OpenAI client library)  
* **Web Scraping/Parsing:** Requests, Beautiful Soup 4  
* **YouTube:** yt-dlp  
* **OCR:** Tesseract.js (Client-side JavaScript)  
* **Frontend:** HTML, CSS, JavaScript (with Marked.js for Markdown rendering)  
* **Authentication:** Flask-Login  
* **Environment:** python-dotenv  
* **Deployment (Example):** Gunicorn, Railway

## **Project Structure**

├── .flaskenv           \# Environment variables for Flask CLI (e.g., FLASK\_APP)  
├── .env                \# Environment variables (API keys, DB URL, secrets) \- \*DO NOT COMMIT\*  
├── Procfile            \# Deployment configuration (e.g., for Heroku, Railway)  
├── auth.py             \# Flask Blueprint for authentication routes (login, logout, register)  
├── models.py           \# SQLAlchemy database models (User, Recipe)  
├── recipe\_scraper\_s3.py \# Main Flask application file, contains API routes, core logic  
├── requirements.txt    \# Python dependencies  
├── youtube\_cookies.txt \# Optional: Cookies for yt-dlp authentication \- \*DO NOT COMMIT\*  
├── instance/           \# Instance-specific files (e.g., SQLite DB if used locally) \- \*DO NOT COMMIT\*  
├── migrations/         \# Flask-Migrate migration scripts  
│   ├── versions/       \# Individual migration files  
│   └── ...  
├── templates/          \# HTML templates (e.g., admin\_dashboard.html, login.html)  
│   └── ...  
└── venv/               \# Virtual environment directory \- \*DO NOT COMMIT\*

* **recipe\_scraper\_s3.py**: The main entry point containing the Flask app, API endpoints, S3 interaction, and scraping logic.  
* **models.py**: Defines the database structure using SQLAlchemy.  
* **auth.py**: Handles user login, registration, and logout using Flask-Login.  
* **templates/**: Contains HTML files rendered by Flask (like the admin dashboard).  
* **migrations/**: Stores database schema changes managed by Flask-Migrate.  
* **.env**: Stores sensitive configuration like API keys and database URLs. **Crucial:** Add this to your .gitignore.  
* **requirements.txt**: Lists all Python packages needed for the project.

## **Setup and Installation**

1. **Clone the repository:**  
   git clone \<your-repo-url\>  
   cd \<repo-name\>

2. **Create and activate a virtual environment:**  
   python \-m venv venv  
   \# On Windows  
   venv\\Scripts\\activate  
   \# On macOS/Linux  
   source venv/bin/activate

3. **Install dependencies:**  
   pip install \-r requirements.txt

4. Set up Environment Variables:  
   Create a .env file in the root directory and add the following variables:  
   \# Database (PostgreSQL recommended for deployment)  
   DATABASE\_URL=postgresql://user:password@host:port/database\_name

   \# Flask secret key (generate a random string)  
   SECRET\_KEY=your\_very\_secret\_random\_string

   \# AWS Credentials for S3  
   AWS\_ACCESS\_KEY\_ID=your\_aws\_access\_key  
   AWS\_SECRET\_ACCESS\_KEY=your\_aws\_secret\_key  
   AWS\_S3\_BUCKET=your\_s3\_bucket\_name  
   AWS\_REGION=your\_s3\_bucket\_region \# e.g., us-east-1

   \# Groq API Key for recipe parsing  
   GROQ\_API\_KEY=your\_groq\_api\_key

   Optionally, create a .flaskenv file for Flask CLI settings:  
   FLASK\_APP=recipe\_scraper\_s3.py  
   FLASK\_ENV=development \# Change to 'production' for deployment

5. Set up the Database:  
   Initialize and apply database migrations:  
   \# (Only needed the first time if migrations folder doesn't exist)  
   \# flask db init 

   \# Create migration files based on models.py changes  
   flask db migrate \-m "Initial database setup" 

   \# Apply migrations to the database  
   flask db upgrade 

   *(Repeat migrate and upgrade whenever you change models.py)*  
6. **YouTube Cookies (Optional but Recommended):**  
   * To avoid potential YouTube authentication issues (like bot detection), export your YouTube login cookies using a browser extension (e.g., "Get cookies.txt LOCALLY").  
   * Save the exported cookies in **Netscape format** to a file named youtube\_cookies.txt in the root project directory. **Add youtube\_cookies.txt to your .gitignore file.** The script will automatically try to use this file if it exists.  
7. **Tesseract.js:** No server-side setup needed. It runs in the user's browser via the included CDN link.

## **Running the Application**

* **Development Server:**  
  flask run

  Access the app at https://web-production-e407.up.railway.app  
* **Production Server (using Gunicorn):**  
  gunicorn "recipe\_scraper\_s3:app" 

  *(Ensure your main Flask app instance is named app in recipe\_scraper\_s3.py)*

## **Deployment**

This application is suitable for deployment on platforms like Railway, Render. Ensure you configure environment variables and database connections correctly on your chosen platform using their specific methods (e.g., Railway's Variables tab). Use the Procfile to define the startup command (e.g., web: gunicorn "recipe\_scraper\_s3:app").
