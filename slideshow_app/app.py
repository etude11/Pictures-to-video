from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response, send_from_directory
from werkzeug.datastructures import FileStorage
import base64
from moviepy.editor import concatenate_videoclips, ImageClip,ImageSequenceClip
import cv2
import numpy as np
import mysql.connector
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, set_access_cookies
from flask_cors import CORS
from flask_bcrypt import Bcrypt  # Added this import
import os
from moviepy.video.fx.all import fadein, fadeout
from base64 import b64encode
from moviepy.editor import VideoFileClip, AudioFileClip
from connect import *
from time import time

app = Flask(__name__)
CORS(app)
app.config['JWT_SECRET_KEY'] = 'your_jwt_secret_key'  # replace with your actual secret key
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = True
app.secret_key = 'your_secret_key'  # replace with your actual secret key
app.config['ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_CSRF_PROTECT'] = False

jwt = JWTManager(app)
bcrypt = Bcrypt(app)  # Initialize Bcrypt

# Create the database if it doesn't exist
cursor.execute("CREATE DATABASE IF NOT EXISTS slideshow_app")
cursor.execute("USE slideshow_app")
cursor = db.cursor()
print("lol")
# Create tables if they don't exist
cursor.execute("CREATE TABLE IF NOT EXISTS Users (id SERIAL PRIMARY KEY, username VARCHAR(50), email VARCHAR(120), password VARCHAR(80))")
cursor.execute("CREATE TABLE IF NOT EXISTS Audio (id SERIAL PRIMARY KEY, data BYTEA, filename VARCHAR(255) NOT NULL)")

# Read audio files from a predefined directory and store them in the Audio table
# ... (previous code)

# Check if there are existing records in the Audio table
cursor.execute("SELECT COUNT(*) FROM Audio")
existing_audio_count = cursor.fetchone()[0]

# If there are no existing records, then add preloaded audio files
if existing_audio_count == 0:
    # Read audio files from a predefined directory and store them in the Audio table
    audio_dir = r"audio"  # Replace with your actual directory path
    for audio_filename in os.listdir(audio_dir):
        audio_path = os.path.join(audio_dir, audio_filename)
        with open(audio_path, 'rb') as audio_file:
            audio_data = audio_file.read()
            cursor.execute("INSERT INTO Audio (data, filename) VALUES (%s, %s)", (audio_data, audio_filename))

    db.commit()


@app.route('/static/<path:filename>')
def send_static(filename):
    return send_from_directory('static',filename)


# Routes for login, signup, home, upload, logout, create, get_audio_files
@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")
        email = request.form.get("email")

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        cursor.execute("SELECT * FROM Users WHERE username = %s OR email = %s", (username, email))
        existing_user = cursor.fetchone()

        if existing_user:
            return render_template('signup.html', message="Username or email already exists")

        cursor.execute("INSERT INTO Users (username, email, password) VALUES (%s, %s, %s)", (username, email, hashed_password))

        # Create a separate table for images for this user
        create_table_query = f"CREATE TABLE IF NOT EXISTS {username} (id SERIAL PRIMARY KEY, data BYTEA)"
        cursor.execute(create_table_query)
        
        db.commit()

        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")

        cursor.execute("SELECT * FROM Users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user[3], password):
            access_token = create_access_token(identity=username)
            
            # Set the JWT in a cookie for access to multiple routes
            response = redirect(url_for('dashboard'))
            response.set_cookie('access_token_cookie', access_token, path='/')

            # Also set cookies for 'upload_images' and 'video' routes
            response.set_cookie('upload_images_cookie', access_token, path='/upload_images')
            response.set_cookie('video_cookie', access_token, path='/video')

            return response
        else:
            return render_template('login.html', message="Invalid credentials")

    return render_template('login.html')

@app.route('/dashboard')
@jwt_required(locations=['cookies'])  # get the JWT from the cookies
def dashboard():
    current_user = get_jwt_identity()
    print(current_user)
    return render_template('home.html', user=current_user)

@app.route('/upload_images', methods=['POST'])
@jwt_required(locations=['cookies'])
def upload_images():

    try:
        images = request.files.values()
        current_user = get_jwt_identity()
        # Clear all previous records in the current_user table
        clear_query = f"DELETE FROM {current_user}"
        cursor.execute(clear_query)
        db.commit()
        for image in images:
            if isinstance(image, FileStorage):
                image_data = image.read()
                # Insert the image into the user's specific table
                insert_query = f"INSERT INTO {current_user} (data) VALUES (%s)"
                cursor.execute(insert_query, (image_data,))

        db.commit()
        cursor.execute(f"SELECT * FROM {current_user}")
        images = cursor.fetchall()
        img_arrays = []
        img_b64_strings = []
        for i, image in enumerate(images):
            # Convert the BLOB image to a numpy array
            nparr = np.frombuffer(image[1], dtype=np.uint8)
            img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Check if the image was successfully decoded
            if img_np is None:
                print(f"Failed to decode image: {image[0]}")
                continue

            # Convert color space from BGR to RGB
            img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)

            # Resize the image to 1920x1080
            img_resized = resize_image(img_rgb, 1920, 1080)

            img_arrays.append(img_resized)

            # Convert the image to a base64 string
            _, img_encoded = cv2.imencode('.jpg', img_resized)
            img_b64 = b64encode(img_encoded).decode('utf-8')
            img_b64_strings.append(img_b64)

        # Create an ImageSequenceClip from the list of image arrays
        clip = ImageSequenceClip(img_arrays, durations=[1]*len(img_arrays))  # Each image lasts 1 second

        # Apply fade-in and fade-out transitions
        clip = fadein(clip, 0.5)  # 0.5 second fade-in
        clip = fadeout(clip, 0.5)  # 0.5 second fade-out

        # Write the video to a file
        video_path = "static/video.mp4"
        clip.write_videofile(video_path, fps=24)  # 24 frames per second

        cursor.execute("SELECT * FROM Audio")
        audios = cursor.fetchall()
        audio_files = [audio[2] for audio in audios]  # Using index 2 for filename column

        print("lol")
        return redirect(url_for('video',ts=int(time()) ))

        # return render_template('video.html', video_path=video_path, audio_files=audio_files, images=img_b64_strings)
# Remaining routes and code from the second snippet

    except Exception as e:
        print(f"Error in /upload_images: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500






def resize_image(img, width, height):
        # Resize the image while maintaining its aspect ratio
    img_aspect = img.shape[1] / img.shape[0]
    width_aspect = width / height
    if img_aspect > width_aspect:
        scale = width / img.shape[1]
    else:
        scale = height / img.shape[0]
    img = cv2.resize(img, None, fx=scale, fy=scale)

    # Add padding to the image to make it the target size
    top = (height - img.shape[0]) // 2
    bottom = height - img.shape[0] - top
    left = (width - img.shape[1]) // 2
    right = width - img.shape[1] - left
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])

    return img


@app.route('/video')
@jwt_required(locations=['cookies'])
def video():
    print("lol")
    current_user = get_jwt_identity()

    # Retrieve the data from the session
    video_path = "static/video.mp4"
    cursor.execute(f"SELECT * FROM {current_user}")
    images = cursor.fetchall()
    img_arrays = []
    img_b64_strings = []
    for i, image in enumerate(images):

        # Convert the BLOB image to a numpy array
        nparr = np.frombuffer(image[1], dtype=np.uint8)

        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Check if the image was successfully decoded
        if img_np is None:
            print(f"Failed to decode image: {image[0]}")
            continue

        # Convert color space from BGR to RGB
        img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)

        # Resize the image to 1920x1080
        img_resized = resize_image(img_rgb, 1920, 1080)

        img_arrays.append(img_resized)

        # Convert the image to a base64 string
        _, img_encoded = cv2.imencode('.jpg', img_resized)
        img_b64 = b64encode(img_encoded).decode('utf-8')
        img_b64_strings.append(img_b64)

    # Fetch audio data from the Audio table
    cursor.execute("SELECT * FROM Audio")
    audios = cursor.fetchall()
    audio_files = [audio[2] for audio in audios]  # Using index 2 for filename column

    return render_template('video.html', video_path=video_path, images=img_b64_strings, audio_files=audio_files)

# Remaining routes and code from the second snippet
def resize_image(img, width, height):
    # Resize the image while maintaining its aspect ratio
    img_aspect = img.shape[1] / img.shape[0]
    width_aspect = width / height
    if img_aspect > width_aspect:
        scale = width / img.shape[1]
    else:
        scale = height / img.shape[0]
    img = cv2.resize(img, None, fx=scale, fy=scale)

    # Add padding to the image to make it the target size
    top = (height - img.shape[0]) // 2
    bottom = height - img.shape[0] - top
    left = (width - img.shape[1]) // 2
    right = width - img.shape[1] - left
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])

    return img
@app.route('/app/home')
@jwt_required()
def home():
    if 'access_token' in request.cookies:
        # get user id from access token
        user_id = get_jwt_identity()
        # get image_id's, image_metadata, image_metadata from images where user_id matches
        cursor.execute('select * from images where user_id = %s', (user_id))
        images = cursor.fetchall()

        cursor.execute('select user_name, user_email from user_details where user_id = %s', (user_id))
        username, email = cursor.fetchone()

        images_code = ''
        for image in images:
            format_image = image[3].split('.')[-1]
            blob_data = base64.b64encode(image[2]).decode('utf-8')
            # get blob data from image[2] and metadata from image
@app.route('/logout')
@jwt_required()  # This ensures that only authenticated users can access this route
def logout():
    # Clear session data
    session.clear()

    # Get the current user's identity
    current_user = get_jwt_identity()

    # You can perform any necessary cleanup here before logging out the user
    # For example, revoking access tokens, clearing session data, etc.

    # Create a new access token with an empty identity, effectively logging the user out
    access_token = create_access_token(identity="")

    # Create a response
    response = make_response(redirect('/'))
    
    # Set the new access token in the cookie
    response.set_cookie('access_token', access_token, httponly=True, max_age=0)

    return response


@app.route('/update_duration', methods=['POST'])
@jwt_required(locations=['cookies'])  # get the JWT from the cookies
def update_video():
    print("lol");
    current_user = get_jwt_identity()
    cursor.execute(f"SELECT * FROM {current_user}")
    images = cursor.fetchall()
    img_arrays = []
    img_b64_strings = []

    durations = request.json['durations']
    # Convert durations to integers
    durations = [int(duration) for duration in durations]
    print(durations)
    for i, image in enumerate(images):
        # Convert the BLOB image to a numpy array
        nparr = np.frombuffer(image[1], dtype=np.uint8)
        img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Check if the image was successfully decoded
        if img_np is None:
            print(f"Failed to decode image: {image[0]}")
            continue

        # Convert color space from BGR to RGB
        img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)

        # Resize the image to 1920x1080
        img_resized = resize_image(img_rgb, 1920, 1080)

        img_arrays.append(img_resized)

        # Convert the image to a base64 string
        _, img_encoded = cv2.imencode('.jpg', img_resized)
        img_b64 = b64encode(img_encoded).decode('utf-8')
        img_b64_strings.append(img_b64)

    # Create an ImageSequenceClip from the list of image arrays
    clip = ImageSequenceClip(img_arrays, durations=durations)  # Use the durations from the POST request

    # Apply fade-in and fade-out transitions
    clip = fadein(clip, 0.5)  # 0.5 second fade-in
    clip = fadeout(clip, 0.5)  # 0.5 second fade-out

    # Write the video to a file
    video_path = "static/video.mp4"
    clip.write_videofile(video_path, fps=24)  # 24 frames per second

    return redirect(url_for('video',ts=int(time())))
from moviepy.editor import VideoFileClip, AudioFileClip

@app.route('/add_background_music', methods=['POST'])
def add_background_music():
    print("lol4")
    data = request.get_json()
    audio_file = data['audio_file']

    video = VideoFileClip('static/video.mp4')
    audio = AudioFileClip('audio/' + audio_file)

    # Clip the audio to the duration of the video
    audio = audio.subclip(0, video.duration)

    video = video.set_audio(audio)
    video.write_videofile('static/video.mp4')

    return '', 200

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
if __name__ == '__main__':
    app.run(debug=False,host='0.0.0.0',port=80)
