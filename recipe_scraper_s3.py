#!/usr/bin/env python3

from fileinput import filename
import glob
from multiprocessing import context
import os
import sys
import subprocess
import webbrowser
import json
import boto3
import http.cookiejar
from datetime import datetime
import base64 
from flask import Flask, redirect, render_template, render_template_string, jsonify, request, session, url_for
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse
import openai
import yt_dlp
from dotenv import load_dotenv
from botocore.exceptions import ClientError, NoCredentialsError
from PIL import Image, ImageOps
# Pytesseract is no longer used by the backend
# import pytesseract 
import traceback
from auth import auth_bp
from models import User, Recipe, db
# from admin import admin_bp
from flask_migrate import Migrate
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from google import genai
from google.genai import types




load_dotenv()

app = Flask(__name__)
# CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = os.getenv("SECRET_KEY", "default_secret")

# db = SQLAlchemy(app)


migrate = Migrate(app, db)
db.init_app(app)

# app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(auth_bp, url_prefix='/auth')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login' 

with app.app_context():
    db.create_all()


class S3Storage:
    def __init__(self):
        self.bucket_name = os.getenv('AWS_S3_BUCKET')
        if not self.bucket_name:
            raise ValueError("AWS_S3_BUCKET environment variable is required")
        
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_REGION', 'us-east-1')
            )
            # Test connection
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except (NoCredentialsError, ClientError) as e:
            raise ValueError(f"AWS S3 configuration error: {str(e)}")
    
# In class S3Storage:
    def save_recipe(self, filename, content, recipe_name, user_id):
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=f"recipes/{user_id}/{filename}",  # <--- Uses user_id
                Body=content.encode('utf-8'),
                ContentType='text/markdown',
                Metadata={
                    'created': datetime.now().isoformat(),
                    'type': 'recipe',
                    'recipe-name': recipe_name
                }
            )
            return True
        except ClientError:
            return False
        
        
    def get_recipe(self, filename, user_id):
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=f"recipes/{user_id}/{filename}"  # <--- Uses user_id
            )
            return response['Body'].read().decode('utf-8')
        except ClientError:
            return None
        
    def get_recipe_metadata(self, key):
        """
        Helper function to get just the metadata and last-modified time of an S3 object.
        This uses a fast HEAD request instead of downloading the whole file.
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=key
            )
            # S3 metadata keys are auto-lowercased, so 'recipe-name' is correct
            return response.get('Metadata', {}), response.get('LastModified')
        except ClientError:
            return None, None
    
# In class S3Storage:
    def list_recipes(self, user_id):
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"recipes/{user_id}/recipe_"  # <--- Uses user_id
            )
            
            recipes = []
            for obj in response.get('Contents', []):
                filename = obj['Key'].replace(f'recipes/{user_id}/', '') 
                if not filename.endswith('.md'):
                    continue
                        
                try:
                    metadata, last_modified = self.get_recipe_metadata(obj['Key'])
                    
                    if metadata and 'recipe-name' in metadata:
                        recipe_name = metadata.get('recipe-name', 'Unknown Recipe')
                        created = metadata.get('created', last_modified.isoformat() if last_modified else datetime.now().isoformat())
                    else:
                        content = self.get_recipe(filename, user_id) 
                        if content and content.startswith('# '):
                            recipe_name = content.split('\n')[0][2:].strip()
                        else:
                            recipe_name = "Unknown Recipe"
                        created = obj['LastModified'].isoformat()

                    recipes.append({
                        'filename': filename,
                        'name': recipe_name,
                        'created': created
                    })
                except Exception as e:
                    print(f"Failed to process {filename}: {e}")
                    continue
            
            return sorted(recipes, key=lambda x: x['created'], reverse=True)
        except ClientError:
            return []
        

    # In class S3Storage:

    def list_all_recipes_admin(self):
        """
        Admin-only function to list all recipes from all users.
        """
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix="recipes/"
            )
            
            recipes = []
            # This dict will store counts like {'user_id_1': 10, 'user_id_2': 5}
            user_recipe_counts = {} 

            for page in pages:
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    # Path is "recipes/USER_ID/FILENAME"
                    # We must ignore the "folder" itself
                    if key.endswith('/'):
                        continue

                    parts = key.split('/')
                    # Ensure the path is valid (recipes/user_id/filename)
                    if len(parts) != 3 or not parts[2].startswith('recipe_'):
                        continue 

                    user_id = parts[1]
                    filename = parts[2]

                    try:
                        # Update this user's recipe count
                        user_recipe_counts[user_id] = user_recipe_counts.get(user_id, 0) + 1

                        # Get metadata (fast)
                        metadata, last_modified = self.get_recipe_metadata(obj['Key'])
                        
                        if metadata and 'recipe-name' in metadata:
                            recipe_name = metadata.get('recipe-name', 'Unknown Recipe')
                            created = metadata.get('created', last_modified.isoformat() if last_modified else datetime.now().isoformat())
                        else:
                            # Slow fallback for old files (should be rare)
                            content = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)['Body'].read().decode('utf-8')
                            if content and content.startswith('# '):
                                recipe_name = content.split('\n')[0][2:].strip()
                            else:
                                recipe_name = "Unknown Recipe"
                            created = obj['LastModified'].isoformat()

                        recipes.append({
                            'filename': filename,
                            'name': recipe_name,
                            'created': created,
                            'user_id': user_id  # Add user_id for the admin view
                        })
                    except Exception as e:
                        print(f"Failed to process admin recipe {filename}: {e}")
                        continue
            
            sorted_recipes = sorted(recipes, key=lambda x: x['created'], reverse=True)
            # Return both the list and the counts dictionary
            return sorted_recipes, user_recipe_counts

        except ClientError as e:
            print(f"Admin recipe list failed: {e}")
            return [], {}

    def delete_recipe(self, filename, user_id):
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=f"recipes/{user_id}/{filename}"  # <--- Uses user_id
            )
            return True
        except ClientError:
            return False
class RecipeScraper:
    def __init__(self, storage):
        self.cookie_file_path = 'browser_cookies.txt'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # --- Client for Groq (Text) ---
        groq_api_key = os.getenv('GROQ_API_KEY')
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")
        
        self.ai_client = openai.OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        
        # --- Client for OpenAI (Vision) ---
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not gemini_api_key:
            # We don't raise an error here because the text scraping is still functional
            print("Warning: GEMINI_API_KEY environment variable not found. Vision model functionality will be disabled.")
            self.vision_client = None
        else:
            self.vision_client = genai.Client(api_key=gemini_api_key)
        
        bbc_cookie_file = 'www.bbcgoodfood.com_cookies.txt'
        try:
            if os.path.exists(bbc_cookie_file):
                cookie_jar = http.cookiejar.MozillaCookieJar(bbc_cookie_file)
                cookie_jar.load(ignore_discard=True, ignore_expires=True)
                self.session.cookies.update(cookie_jar)
                print(f"Successfully loaded cookies from {bbc_cookie_file} for requests session.")
            else:
                print(f"Warning: BBC cookie file not found at {bbc_cookie_file}. Scraping may fail.")
        except Exception as e:
            print(f"Warning: Failed to load cookies from {bbc_cookie_file}. Error: {e}")
        
        
        self.storage = storage
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
 
    def is_youtube_url(self, url):
        youtube_patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)',
            r'youtube\.com.*[?&]v=',
            r'youtu\.be/'
        ]
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)
    
    def extract_youtube_transcript(self, url):
        try:
            cookie_file_path = 'youtube_cookies.txt'
            ydl_opts = {
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en', 'en-US', 'en-GB'],
                'skip_download': True,
                'no_warnings': True,
                'cookiefile': cookie_file_path
            }
            if not os.path.exists(cookie_file_path):
                print(f"Warning: Cookie file not found at {cookie_file_path}. Authentication may fail.")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'YouTube Recipe')
                duration = info.get('duration', 0)
                
                subtitles = info.get('subtitles', {}) or info.get('automatic_captions', {})
                transcript_text = ""
                
                for lang in ['en', 'en-US', 'en-GB', 'a.en']:
                    if lang in subtitles:
                        for subtitle in subtitles[lang]:
                            if subtitle.get('ext') == 'vtt':
                                try:
                                    subtitle_response = requests.get(subtitle['url'])
                                    vtt_content = subtitle_response.text
                                    transcript_text = self.parse_vtt_content(vtt_content)
                                    break
                                except:
                                    continue
                            if transcript_text:
                                break
                
                if not transcript_text:
                    transcript_text = info.get('description', '')
                
                return {
                    "url": url,
                    "title": title,
                    "duration": duration,
                    "content": transcript_text,
                    "type": "youtube_video",
                    "scraped_at": datetime.now().isoformat()
                }
                
        except Exception:
            return None
    
    def parse_vtt_content(self, vtt_content):
        lines = vtt_content.split('\n')
        text_lines = []
        
        for line in lines:
            line = line.strip()
            if (not line or 
                line.startswith('WEBVTT') or 
                line.startswith('NOTE') or
                '-->' in line or
                re.match(r'^\d+$', line)):
                continue
            
            line = re.sub(r'<[^>]+>', '', line)
            line = re.sub(r'&\w+;', '', line)
            
            if line:
                text_lines.append(line)
        
        return ' '.join(text_lines)
    
    def extract_recipe_sections(self, content):
        lines = content.split('\n')
        ingredients_section = []
        instructions_section = []
        
        in_ingredients = False
        in_instructions = False
        
        for line in lines:
            line = line.strip()
            
            if re.search(r'\bingredients?\b', line, re.IGNORECASE) and len(line) < 100:
                in_ingredients = True
                in_instructions = False
                continue
            
            if re.search(r'\b(instructions?|method|directions?|steps?)\b', line, re.IGNORECASE) and len(line) < 100:
                in_instructions = True
                in_ingredients = False
                continue
            
            if in_ingredients:
                if re.search(r'\b(method|instructions?|directions?|steps?|nutrition|notes)\b', line, re.IGNORECASE):
                    in_ingredients = False
                    in_instructions = 'instructions' in line.lower() or 'method' in line.lower()
                    continue
                
                if line and not line.startswith(('▢', '•', '-', '*')):
                    if any(indicator in line.lower() for indicator in ['g ', 'ml', 'tbsp', 'tsp', 'cup', 'oz', 'lb', 'clove', 'onion', 'garlic']):
                        ingredients_section.append(line)
                elif line.startswith(('▢', '•', '-', '*')):
                    ingredients_section.append(line[1:].strip())
            
            if in_instructions:
                if re.search(r'\b(nutrition|notes|tips|faq)\b', line, re.IGNORECASE):
                    in_instructions = False
                    continue
                
                if line:
                    if (re.match(r'^\d+\.?\s+', line) or 
                        line.lower().startswith('step') or
                        any(action in line.lower() for action in ['cook', 'add', 'heat', 'stir', 'mix', 'drain', 'serve', 'fry', 'bake'])):
                        instructions_section.append(line)
        
        return {
            'ingredients': ingredients_section,
            'instructions': instructions_section
        }
    
    def scrape_url(self, url):
        if self.is_youtube_url(url):
            return self.extract_youtube_transcript(url)
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            for element in soup(["script", "style", "nav", "header", "footer"]):
                element.decompose()
            
            structured_recipe = self.extract_structured_data(soup)
            
            title = soup.find('title')
            page_title = title.get_text().strip() if title else ""
            
            text_content = soup.get_text()
            lines = (line.strip() for line in text_content.splitlines())
            text_content = '\n'.join(line for line in lines if line)
            
            recipe_sections = self.extract_recipe_sections(text_content)
            
            return {
                "url": url,
                "title": page_title,
                "content": text_content[:15000],
                "structured_data": structured_recipe,
                "recipe_sections": recipe_sections,
                "scraped_at": datetime.now().isoformat()
            }
            
        except Exception:
            return None
    
    def extract_structured_data(self, soup):
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if data.get('@type') == 'Recipe' or 'Recipe' in str(data.get('@type', '')):
                    return data
            except:
                continue
        return None

    def parse_with_ai(self, scraped_data):
        import json

        content_text = scraped_data.get('content', '').strip()

        # Step 1: Inject pre-extracted sections if available
        recipe_sections = scraped_data.get('recipe_sections', {})
        if recipe_sections.get('ingredients') or recipe_sections.get('instructions'):
            sections_text = (
                f"\nPRE-EXTRACTED INGREDIENTS:\n{chr(10).join(recipe_sections.get('ingredients', []))}"
                f"\n\nPRE-EXTRACTED INSTRUCTIONS:\n{chr(10).join(recipe_sections.get('instructions', []))}"
            )
            content_text = sections_text + "\n\nFULL PAGE CONTENT:\n" + content_text

        # Step 2: Add structured data if present
        if scraped_data.get('structured_data'):
            structured_info = json.dumps(scraped_data['structured_data'], indent=2)
            content_text = f"STRUCTURED DATA:\n{structured_info}\n\n{content_text}"

        # Step 3: Contextualize source type
        source_type = scraped_data.get('type')
        if source_type == 'youtube_video':
            video_context = 'This is a transcript from a YouTube cooking video.'
            video_rules = '- For video transcripts: ignore "like and subscribe", introductions, and off-topic chat'
        elif source_type == 'photo_ocr': # Kept for compatibility if old data is processed
            video_context = 'This is OCR text extracted from a photo of a recipe.'
            video_rules = '- For OCR text: ignore any misread characters, focus on extracting the recipe content'
        else:
            video_context = 'This is from a recipe webpage.'
            video_rules = ''

        # Step 4: Build prompt
        prompt = f"""You're a recipe extraction expert. Extract ONLY the essential recipe info from this content.

    {video_context}

    CRITICAL: You MUST include ALL cooking steps. Do not skip any steps, even if they seem minor.

    Return in this EXACT format:
    # [Recipe Name]

    **Ingredients:**
    • [ingredient 1]
    • [ingredient 2]
    ...

    **Method:**
    1. [step 1]
    2. [step 2]
    3. [step 3]
    ...

    EXTRACTION RULES:
    - Convert ALL measurements to METRIC: grams (g), ml, litres, Celsius (°C)
    - Examples: "225g flour", "500ml milk", "180°C", "2 tbsp = 30ml"
    - Keep ingredient format: "225g plain flour" not "flour (225g)"
    - Include EVERY cooking step - do not combine or skip steps
    - Include ESSENTIAL cooking details: temperatures, times, visual cues, doneness indicators
    - Examples: "brown until golden", "rest 30 minutes", "cook until internal temp 74°C", "simmer until thickened"
    - Convert Fahrenheit to Celsius: 375°F = 190°C, 165°F = 74°C
    - Keep steps direct but include critical timing/visual cues
    - Remove fluff, ads, life stories, nutrition info, but keep ALL technical cooking steps
    - Look carefully through the content for ALL method/instructions/steps
    - Pay special attention to pre-extracted ingredients and instructions sections
    - Ignore navigation, comments, ratings, related recipes, subscription offers
    {video_rules}
    - If no clear recipe exists, return only: "NO_RECIPE_FOUND"
    - Don't include URL in output
    - Be thorough - include every step mentioned in the original recipe

    DOUBLE-CHECK: Ensure you haven't missed any cooking steps from the original recipe.

    URL: {scraped_data.get('url', 'N/A')}

    Content:
    {content_text}
    """

        # Step 5: Call AI model (Groq)
        try:
            response = self.ai_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a recipe extraction expert specializing in converting cooking content into clean, minimalist, metric-based recipes. Your priority is capturing ALL cooking steps and ingredients without omission. Focus on thoroughness and accuracy."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0,
                max_tokens=5000,
                stream=False
            )
            ai_response = response.choices[0].message.content.strip()
            return ai_response

        except Exception as e:
            print("AI parsing (text) failed:", str(e))
            return self.fallback_parse(scraped_data)    

    def parse_with_vision(self, image_bytes_list, text_prompt=""):
        if not self.vision_client:
            return "NO_RECIPE_FOUND" # Vision is disabled due to missing key

        try:
            user_messages = []
            
            # 1. Build the prompt (text part)
            main_prompt = f"""You are a recipe extraction expert. Extract ONLY the essential recipe info from these images.
If there are multiple images, combine them to form a single, coherent recipe.

Optional user prompt: '{text_prompt}'

CRITICAL: You MUST include ALL cooking steps. Do not skip any steps.

Return in this EXACT format:
# [Recipe Name]

**Ingredients:**
• [ingredient 1]
• [ingredient 2]
...

**Method:**
1. [step 1]
2. [step 2]
...

EXTRACTION RULES:
- Convert ALL measurements to METRIC: grams (g), ml, litres, Celsius (°C)
- Include EVERY cooking step.
- Convert Fahrenheit to Celsius (e.g., 375°F = 190°C).
- Remove all other text, notes, or stories.
- If no clear recipe exists, return only: "NO_RECIPE_FOUND"
"""
            
            # 2. Prepare the multimodal content list: Process images first.
            content_parts = []
            
            # Add the images first
            for image_bytes in image_bytes_list:
                if not image_bytes:
                    continue
                
                # --- START: ROBUST IMAGE PROCESSING (Handles any format) ---
                processed_image_bytes = None
                mime_type = 'image/jpeg' 
                
                try:
                    from io import BytesIO
                    
                    # Open the image (PIL handles PNG, JPEG, WebP, etc., automatically)
                    img = Image.open(BytesIO(image_bytes))
                    
                    # Fix Orientation (Crucial for mobile photos)
                    img = ImageOps.exif_transpose(img) 

                    # Convert to RGB if necessary (Standardizes color space)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                        
                    # Re-save the image to a standardized format (JPEG)
                    buffer = BytesIO()
                    img.save(buffer, format='JPEG', quality=90) # Re-encode to clean JPEG
                    processed_image_bytes = buffer.getvalue()
                    
                    # The image is now a clean JPEG in standard format
                    
                except Exception as e:
                    # Log the specific image error but continue if possible
                    print(f"Error processing uploaded image file in PIL: {e}")
                    # If we can't process it, we must skip it.
                    continue 
                
                if processed_image_bytes:
                    content_parts.append(
                        types.Part.from_bytes(data=processed_image_bytes, mime_type=mime_type)
                    )
                # --- END: ROBUST IMAGE PROCESSING ---
                
            if not content_parts:
                 return "NO_RECIPE_FOUND" # No valid image files could be processed
                 
            # Add the text prompt
            content_parts.append(main_prompt)


            # 3. Call the Gemini Vision Model
            response = self.vision_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=content_parts
            )
            
            ai_response = response.text.strip()
            return ai_response

        except Exception as e:
            print(f"AI parsing (Gemini vision) failed: {str(e)}")
            traceback.print_exc()
            return "NO_RECIPE_FOUND"


    def fallback_parse(self, scraped_data):
        content = scraped_data['content']
        structured = scraped_data.get('structured_data') or {}
        recipe_sections = scraped_data.get('recipe_sections', {})
        
        title = structured.get('name') or scraped_data['title'].split('|')[0].strip()
        
        ingredients = structured.get('recipeIngredient', [])
        if not ingredients and recipe_sections.get('ingredients'):
            ingredients = recipe_sections['ingredients']
        
        instructions = []
        if structured.get('recipeInstructions'):
            structured_instructions = structured['recipeInstructions']
            if isinstance(structured_instructions, list):
                for inst in structured_instructions:
                    if isinstance(inst, dict):
                        instructions.append(inst.get('text', str(inst)))
                    else:
                        instructions.append(str(inst))
        elif recipe_sections.get('instructions'):
            instructions = recipe_sections['instructions']
        
        if not ingredients and not instructions:
            return "NO_RECIPE_FOUND"
        
        formatted_ingredients = '\n'.join('• ' + ing for ing in ingredients[:20]) if ingredients else '• No ingredients found'
        formatted_instructions = '\n'.join(f'{i+1}. {inst}' for i, inst in enumerate(instructions[:15])) if instructions else '1. No instructions found'
        
        return f"""# {title}

**Ingredients:**
{formatted_ingredients}

**Method:**
{formatted_instructions}"""
    
    def create_markdown(self, ai_response, scraped_data):
        if ai_response.strip() == "NO_RECIPE_FOUND":
            return f"""# No Recipe Found

                **URL:** {scraped_data['url']}

                Could not extract a clear recipe from this URL/Image. The page may not contain a recipe or may be behind a paywall."""
        
        if scraped_data['url'] not in ai_response:
            lines = ai_response.split('\n')
            if lines and not ai_response.strip() == "NO_RECIPE_FOUND":
                title_line = lines[0]
                rest = '\n'.join(lines[1:]) if len(lines) > 1 else ''
                ai_response = f"{title_line}\n\n**URL:** {scraped_data['url']}\n\n{rest}"
        
        return ai_response
    

# In class RecipeScraper:
    # In class RecipeScraper:
    
    def scrape_and_save(self, url, user_id):
        scraped_data = self.scrape_url(url)
        if not scraped_data or not scraped_data.get('content'):
            return {"status": "failed", "error": "Failed to scrape URL", "url": url}

        ai_response = None 
        try:
            ai_response = self.parse_with_ai(scraped_data)
            print("AI Response:", repr(ai_response))
        except Exception as e:
            print(f"An error occurred during AI parsing: {str(e)}")
            traceback.print_exc()
            return {"status": "failed", "error": f"AI parsing failed: {str(e)}", "url": url}

        if not ai_response or ai_response.strip() == "NO_RECIPE_FOUND":
            return {"status": "failed", "error": "AI failed to extract recipe", "url": url}

        markdown_content = self.create_markdown(ai_response, scraped_data)
        if not markdown_content or len(markdown_content.strip()) < 10:
            return {"status": "failed", "error": "Failed to format recipe content", "url": url}

        recipe_name = "Unknown Recipe"
        first_line = markdown_content.split('\n')[0].strip()
        if first_line.startswith('# '):
            recipe_name = first_line[2:].strip()

        domain = urlparse(url).netloc.replace('www.', '').replace('/', '_')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"recipe_{domain}_{timestamp}.md"
        print("Saving to S3:", filename, "for user:", user_id)

        save_success = self.storage.save_recipe(
            filename, 
            markdown_content, 
            recipe_name, 
            user_id  # <--- Passes user_id
        )
        
        if not save_success:
            return {"status": "failed", "error": "Failed to save recipe to S3", "url": url}

        return {
            "status": "success",
            "filename": filename,
            "recipe_name": recipe_name,
            "url": url,
            "content": markdown_content,
            "created": datetime.now().isoformat()
        }
    

try:
    storage = S3Storage()
    scraper = RecipeScraper(storage)
except ValueError as e:
    print(f"Configuration error: {e}")
    exit(1)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    
    
@app.route('/dashboard')
@login_required
def dashboard():
    # Fetch role and username dynamically
    role = current_user.role.strip().lower()
    username = current_user.username
    
    users = User.query.all()
    recipes = []
    user_recipe_counts = {}

    try:
        if role == 'admin':
            # ADMIN: Fetch ALL recipes from S3 across ALL users
            # storage.list_all_recipes_admin returns (recipes, user_recipe_counts)
            recipes, user_recipe_counts = storage.list_all_recipes_admin()
        else:
            # REGULAR USER: Fetch ONLY their recipes from S3
            recipes = storage.list_recipes(current_user.id)
            # For non-admins, their count is just the length of their list
            user_recipe_counts[str(current_user.id)] = len(recipes)
            
        # --- Metrics Calculation (Required by HTML) ---
        total_s3_recipes = sum(user_recipe_counts.values())
        avg_recipes = round(total_s3_recipes / len(users), 2) if users else 0
        total_recipes = len(recipes)
        active_users = User.query.filter_by(is_active=True).count()
        
        # NOTE: We iterate over users here to attach the S3-based count
        for user in users:
             user.recipe_count = user_recipe_counts.get(str(user.id), 0)
        
        # --- CONTEXT PASSED TO TEMPLATE ---
        context = {
            'username': username,
            'total_recipes': total_recipes,
            'active_users': active_users,
            'last_sync_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'top_source': 'youtube.com', 
            'popular_tags': ['Chicken', 'Quick Meals'], 
            'avg_recipes': avg_recipes,
            'recipes': recipes,         # <--- ENSURE THIS LIST CONTAINS ALL ADMIN RECIPES
            'users': users,
        }

        # --- Render the correct template ---
        if role == 'admin':
            # The admin dashboard template needs the 'recipes' variable (all users)
            return render_template('admin_dashboard.html', **context)
        elif role == 'family':
            return render_template('family_dashboard.html', **context)
        elif role == 'user':
            return render_template('user_dashboard.html', **context)
        else:
            return redirect(url_for('auth.login'))
            
    except Exception as e:
        print(f"Error loading dashboard: {e}")
        traceback.print_exc()
        return redirect(url_for('auth.logout'))

@app.route('/auth/login', methods=['POST'])
def login():
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.password == password:
            login_user(user)

            # Normalize and store role from DB
            role = user.role.strip().lower()
            session['role'] = role

            return redirect('/dashboard')

        # Optional: handle login failure
        return redirect('/login')


        # return "Invalid credentials", 401

@app.route('/auth/register', methods=['POST'])
def register():
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'user')

        if User.query.filter_by(username=username).first():
            return "Username already exists", 400

        
        new_user = User(username=username, password=password, role=role)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('auth_page'))

@app.route('/auth/logout', methods=['GET'])
def logout():
    logout_user()
    return redirect(url_for('auth_page'))
    


    
@app.route('/api/update-role', methods=['POST'])
def update_role():
    data = request.get_json()
    user_id = data.get('user_id')
    new_role = data.get('new_role')

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.role = new_role
    db.session.commit()
    return jsonify({'message': 'Role updated successfully'})

@app.route('/api/dashboard-metrics')
def dashboard_metrics():
    total_recipes = Recipe.query.count()
    active_users = User.query.count()
    last_sync_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({
        'total_recipes': total_recipes,
        'active_users': active_users,
        'last_sync_time': last_sync_time
    })

@app.route('/api/usage-analytics')
def usage_analytics():
    # Most scraped source
    top_source = db.session.query(Recipe.source).group_by(Recipe.source).order_by(db.func.count().desc()).first()

    # Average recipes per user
    user_count = User.query.count()
    recipe_count = Recipe.query.count()
    avg_recipes = round(recipe_count / user_count, 2) if user_count else 0

    # Popular tags (placeholder logic)
    popular_tags = ['quick', 'vegan', 'dessert']  # Replace with actual tag aggregation if available

    # Breakdown for charting
    scraped_count = Recipe.query.filter(Recipe.source != None).count()
    manual_count = Recipe.query.filter(Recipe.source == None).count()
    favorites_count = 10  # Replace with actual logic if you track favorites

    return jsonify({
        'top_source': top_source[0] if top_source else 'N/A',
        'avg_recipes': avg_recipes,
        'popular_tags': popular_tags,
        'scraped_count': scraped_count,
        'manual_count': manual_count,
        'favorites_count': favorites_count,
        'total_recipes': recipe_count,
        'total_users': user_count
    })

@app.route('/api/users')
def get_users():
    users = User.query.all()
    return jsonify([
        {
            'id': u.id,
            'username': u.username,
            'recipe_count': len(u.recipes),
            'role': u.role 
        } for u in users
    ])



@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/recipes')
@login_required
def get_recipes():
    """
    Get list of all markdown recipe files from S3 bucket with metadata.
    Includes logic for sharing recipes among users with the 'family' role.
    """
    try:
        role = current_user.role.strip().lower()
        user_ids_to_fetch = []

        if role == 'family':
            # 1. If 'family', fetch IDs of all users with the same role
            family_users = User.query.filter_by(role='family').all()
            # Ensure IDs are strings as S3 keys are based on string IDs
            user_ids_to_fetch = [str(u.id) for u in family_users]
        else:
            # 2. Otherwise, only fetch current user's ID
            user_ids_to_fetch = [str(current_user.id)]

        all_recipes = []
        for user_id in user_ids_to_fetch:
            # list_recipes fetches recipes for the given user_id
            recipes = storage.list_recipes(user_id)
            
            # Augment recipes with the owner's ID for viewing shared recipes later
            for recipe in recipes:
                recipe['owner_id'] = user_id
            
            all_recipes.extend(recipes)

        # Re-sort the combined list by creation time
        all_recipes.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify(all_recipes)

    except Exception as e:
        print(f"Recipe listing failed: {str(e)}")
        traceback.print_exc() # Add this for better debugging
        return jsonify({'error': str(e)}), 500

@app.route('/api/recipe/save', methods=['POST'])
@login_required
def save_recipe():
    try:
        data = request.get_json()
        filename = data.get('filename', '').strip()
        content = data.get('content', '').strip()
        user_id = current_user.id
        
        if not filename or not content:
            return jsonify({'error': 'Filename and content are required'}), 400
        
        if not filename.startswith('recipe_') or not filename.endswith('.md'):
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Parse the recipe name from the content
        recipe_name = "Unknown Recipe"
        if content.startswith('# '):
            recipe_name = content.split('\n')[0][2:].strip()

        # Call save_recipe ONCE with all correct arguments
        if not storage.save_recipe(filename, content, recipe_name, user_id):
            return jsonify({'error': 'Failed to save recipe to S3'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Recipe saved successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

# --- ADD THIS ROUTE TO YOUR FLASK APP (app.py) ---

@app.route('/recipe/<filename>')
def view_public_recipe(filename):
    """
    Public route to view a recipe. This bypasses login_required.
    SECURITY NOTE: This exposes the recipe if a user knows the filename.
    A better approach uses a UUID or short code for security.
    """
    # For simplicity, we assume 'admin' is the owner, as they have access to all
    # For a proper fix, you would need to lookup the recipe in a database 
    # to find the original owner's ID based on the filename.

    # TEMPORARY FIX: Try to guess the owner by checking if it's in the current user's or the first family member's S3 path.
    # THIS IS NOT ROBUST. For now, we just deny unauthorized access.
    
    # We must prevent unauthorized guessing of the owner_id if we don't have a secure lookup.
    # To enable simple public viewing, you need a mechanism to map the filename to a content string 
    # that doesn't require an owner ID. Since S3 is partitioned by user_id, a clean public 
    # view without authentication is complicated.

    # Since the frontend assumes this works, we'll try to find the recipe in the first user's path.
    # --- This fallback is too complex and risky without a proper DB structure. ---
    
    # Let's return the content directly, mimicking the API but without login.
    # You MUST replace this logic with a **secure recipe lookup** if you deploy this publicly.

    # To get this working *for testing*, we will redirect the user to log in if they are not.
    # This maintains the login requirement but gives the link a clear purpose.
    if not current_user.is_authenticated:
        # Redirects to login page if user tries to access a recipe publicly
        return redirect(url_for('auth.login', next=request.path))

    # If logged in, use the existing secured endpoint logic by redirecting to it
    # We need the owner_id, which we don't have here.
    # This is why the frontend logic must be the main focus for now.
    
    # Since the current frontend link is designed to copy an internal path, 
    # we will rely on the user being logged in to click the copied link.
    
    return redirect(url_for('get_recipe_content', filename=filename, owner_id=current_user.id))

# --- DO NOT ADD THIS PUBLIC ROUTE YET, FOCUS ON JAVASCRIPT ---
# The best approach for now is the JavaScript clipboard fix above.

@app.route('/api/recipe/<filename>')
@login_required
def get_recipe_content(filename):
    try:
        if not filename.startswith('recipe_') or not filename.endswith('.md'):
            return jsonify({'error': 'Invalid filename'}), 400
        

        owner_id = request.args.get('owner_id', str(current_user.id))
        current_user_id = str(current_user.id) # Ensure comparison is consistent

        # SECURITY CHECK: If the owner_id is different from the current user, 
        # ensure the current user is authorized.
        if owner_id != current_user_id:
            current_role = current_user.role.strip().lower()
            owner_user = User.query.get(owner_id)
            owner_role = owner_user.role.strip().lower() if owner_user else None

            # --- FIX: Explicitly grant access if the current user is an Admin ---
            is_authorized = False
            if current_role == 'admin':
                is_authorized = True
            # --- Existing Family Sharing Logic ---
            elif current_role == 'family' and owner_role == 'family':
                is_authorized = True
            
            if not is_authorized:
                return jsonify({'error': 'Unauthorized access to this recipe.'}), 403

        # Call get_recipe using the determined owner_id
        content = storage.get_recipe(filename, owner_id) 
        
        if content is None:
            return jsonify({'error': 'Recipe not found'}), 404
        
        return jsonify({'content': content})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recipe/<filename>', methods=['DELETE'])
@login_required
def delete_recipe(filename):
    try:
        if not filename.startswith('recipe_') or not filename.endswith('.md'):
            return jsonify({'error': 'Invalid filename'}), 400
        
        if not storage.delete_recipe(filename, current_user.id): # <--- Pass user_id
            return jsonify({'error': 'Failed to delete recipe from S3'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Recipe deleted successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

# --- ROUTE MODIFIED: /api/ocr -> /api/vision ---
@app.route('/api/vision', methods=['POST'])
@login_required
def process_vision_upload():
    try:
        user_id = current_user.id
        
        # 1. Get files from form data
        images = request.files.getlist('images')
        if not images or all(f.filename == '' for f in images):
             return jsonify({'error': 'No image files provided'}), 400
             
        # 2. Get optional text prompt
        text_prompt = request.form.get('text', '')

        # 3. Read image bytes
        image_bytes_list = []
        for file in images:
            if file:
                image_bytes_list.append(file.read())

        if not image_bytes_list:
            return jsonify({'error': 'Failed to read image files'}), 400

        # 4. Call the new vision parser
        print(f"Sending {len(image_bytes_list)} images to vision model...")
        ai_response = scraper.parse_with_vision(image_bytes_list, text_prompt)

        if ai_response.strip() == "NO_RECIPE_FOUND":
            return jsonify({
                'error': 'Could not extract a clear recipe from the image(s).'
            }), 400

        # 5. Create markdown and save to S3 (similar to before)
        scraped_data = {
            'url': 'Image Upload',
            'title': 'Recipe from Image(s)',
            'content': ai_response, # The AI response is the content
            'type': 'vision_upload',
            'scraped_at': datetime.now().isoformat()
        }
        
        markdown_content = scraper.create_markdown(ai_response, scraped_data)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"recipe_vision_{timestamp}.md"

        recipe_name = "Vision Recipe"
        if markdown_content.startswith('# '):
            recipe_name = markdown_content.split('\n')[0][2:].strip()
            
        if not storage.save_recipe(filename, markdown_content, recipe_name, user_id):
            return jsonify({'error': 'Failed to save recipe to S3'}), 500

        return jsonify({
            'success': True,
            'filename': filename,
            'recipe_name': recipe_name,
            'created': datetime.now().isoformat()
        })
    
    except Exception as e:
        traceback.print_exc() 
        return jsonify({'error': str(e)}), 500




@app.route('/api/scrape', methods=['POST'])
@login_required 
def scrape_recipe():
    try:
        data = request.get_json()
        url = data.get('url', '').strip()

        # Validate URL
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # --- LOGGED-IN USER ---
        # User is logged in, so we scrape AND save to their account
        result = scraper.scrape_and_save(url, current_user.id)

        if not result or result.get("status") == "failed":
            return jsonify({'error': result.get("error", "Unknown scraping error.")}), 400
        
        # Return success response (it's saved)
        return jsonify(result), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Internal error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
