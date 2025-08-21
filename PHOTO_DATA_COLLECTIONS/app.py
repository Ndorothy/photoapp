# app.py
import os
import cv2
import zipfile
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "alinda_secret_key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///alinda.db"
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

# Preset users
USERS = {
    "BRIDGERS": "64149002A",
    "maminda": "641490020",
    "praise": "64149002G"
}

# Models
class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner = db.Column(db.String(50), nullable=False)
    photos = db.relationship("Photo", backref="folder", lazy=True, cascade="all, delete-orphan")

class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    uploader = db.Column(db.String(50), nullable=False)
    faces_detected = db.Column(db.Integer, default=0)
    folder_id = db.Column(db.Integer, db.ForeignKey("folder.id"), nullable=False)

# Utils
def detect_faces(image_path):
    try:
        img = cv2.imread(image_path)
        if img is None:
            return 0
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        return len(faces)
    except Exception as e:
        print(f"Error detecting faces: {e}")
        return 0

def create_zip_for_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    photos = Photo.query.filter_by(folder_id=folder_id).all()
    
    # Create in-memory zip file
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add each photo to the zip
        for photo in photos:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
            if os.path.exists(file_path):
                zf.write(file_path, photo.filename)
        
        # Add a metadata file with descriptions
        metadata_content = f"Folder: {folder.name}\nOwner: {folder.owner}\n\nPhotos:\n"
        for photo in photos:
            metadata_content += f"\nFilename: {photo.filename}\nDescription: {photo.description}\nFaces Detected: {photo.faces_detected}\nUploader: {photo.uploader}\n"
        
        zf.writestr("metadata.txt", metadata_content)
    
    memory_file.seek(0)
    return memory_file

# Routes
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and USERS[username] == password:
            session["user"] = username
            return redirect(url_for("folders"))
        else:
            flash("Invalid username or password", "danger")
    return render_template("login.html")

@app.route("/folders", methods=["GET", "POST"])
def folders():
    if "user" not in session:
        return redirect(url_for("login"))
    
    if request.method == "POST":
        folder_name = request.form.get("folder_name")
        if folder_name:
            folder = Folder(name=folder_name, owner=session["user"])
            db.session.add(folder)
            db.session.commit()
            flash(f"Folder '{folder_name}' created successfully!", "success")
    
    all_folders = Folder.query.filter_by(owner=session["user"]).all()
    return render_template("folders.html", folders=all_folders)

@app.route("/folders/<int:folder_id>", methods=["GET", "POST"])
def gallery(folder_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    folder = Folder.query.get_or_404(folder_id)
    
    # Check if user owns this folder
    if folder.owner != session["user"]:
        flash("You don't have permission to access this folder", "danger")
        return redirect(url_for("folders"))
    
    if request.method == "POST":
        files = request.files.getlist("photos")
        if not files or files[0].filename == '':
            flash("No files selected", "warning")
        else:
            for file in files:
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    # Ensure unique filename
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], filename)):
                        filename = f"{base}_{counter}{ext}"
                        counter += 1
                    
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    file.save(save_path)
                    num_faces = detect_faces(save_path)
                    photo = Photo(
                        filename=filename, 
                        description="", 
                        uploader=session["user"], 
                        folder_id=folder.id, 
                        faces_detected=num_faces
                    )
                    db.session.add(photo)
            db.session.commit()
            flash("Photos uploaded successfully!", "success")
    
    return render_template("gallery.html", folder=folder)

@app.route("/add_caption/<int:photo_id>", methods=["POST"])
def add_caption(photo_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    photo = Photo.query.get_or_404(photo_id)
    
    # Check if user owns this photo
    if photo.uploader != session["user"]:
        flash("You don't have permission to edit this photo", "danger")
        return redirect(url_for("gallery", folder_id=photo.folder_id))
    
    caption = request.form.get("caption")
    photo.description = caption
    db.session.commit()
    flash("Caption added successfully!", "success")
    return redirect(url_for("gallery", folder_id=photo.folder_id))

@app.route("/download_folder/<int:folder_id>")
def download_folder(folder_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    folder = Folder.query.get_or_404(folder_id)
    
    # Check if user owns this folder
    if folder.owner != session["user"]:
        flash("You don't have permission to download this folder", "danger")
        return redirect(url_for("folders"))
    
    zip_file = create_zip_for_folder(folder_id)
    return send_file(
        zip_file,
        as_attachment=True,
        download_name=f"{folder.name}.zip",
        mimetype="application/zip"
    )

@app.route("/delete_photo/<int:photo_id>")
def delete_photo(photo_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    photo = Photo.query.get_or_404(photo_id)
    
    # Check if user owns this photo
    if photo.uploader != session["user"]:
        flash("You don't have permission to delete this photo", "danger")
        return redirect(url_for("gallery", folder_id=photo.folder_id))
    
    # Remove file from filesystem
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    folder_id = photo.folder_id
    db.session.delete(photo)
    db.session.commit()
    flash("Photo deleted successfully!", "success")
    return redirect(url_for("gallery", folder_id=folder_id))

@app.route("/delete_folder/<int:folder_id>")
def delete_folder(folder_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    folder = Folder.query.get_or_404(folder_id)
    
    # Check if user owns this folder
    if folder.owner != session["user"]:
        flash("You don't have permission to delete this folder", "danger")
        return redirect(url_for("folders"))
    
    # Delete all associated photos from filesystem
    for photo in folder.photos:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    
    db.session.delete(folder)
    db.session.commit()
    flash("Folder deleted successfully!", "success")
    return redirect(url_for("folders"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.errorhandler(413)
def too_large(e):
    flash("File too large. Maximum size is 16MB.", "danger")
    return redirect(request.url)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)