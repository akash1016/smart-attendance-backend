from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
import os, datetime, uuid, traceback, io
from PIL import Image
import numpy as np
import cv2
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

# DB setup
DB_PATH = os.path.join(BASE_DIR, 'database.db')
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)
class Attendance(Base):
    __tablename__ = 'attendance'
    id = Column(Integer, primary_key=True)
    student_username = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
Base.metadata.create_all(engine)

# Seed users
def seed():
    db = SessionLocal()
    if not db.query(User).filter_by(username='admin').first():
        db.add_all([User(username='admin', password='admin123', role='admin'), User(username='teacher1', password='pass123', role='teacher'), User(username='student1', password='pass123', role='student')])
        db.commit()
    db.close()
seed()

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
MODEL_PATH = os.path.join(BASE_DIR, 'lbph_model.yml')

def get_label_mapping():
    # labels: username -> integer id
    users = [d for d in os.listdir(UPLOAD_FOLDER) if os.path.isdir(os.path.join(UPLOAD_FOLDER,d))]
    users.sort()
    mapping = {user: idx+1 for idx, user in enumerate(users)}
    return mapping

def train_model():
    # Train LBPH from images in uploads/
    mapping = get_label_mapping()
    faces = []
    labels = []
    for user, label in mapping.items():
        user_dir = os.path.join(UPLOAD_FOLDER, user)
        for fname in os.listdir(user_dir):
            path = os.path.join(user_dir, fname)
            try:
                img = Image.open(path).convert('L').resize((200,200))
                arr = np.array(img, dtype=np.uint8)
                faces.append(arr)
                labels.append(label)
            except Exception as e:
                print('skip', path, e)
    if not faces:
        return False, 'no faces to train'
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(faces, np.array(labels))
    recognizer.write(MODEL_PATH)
    return True, f'trained {len(faces)} faces for {len(mapping)} students'

@app.route('/auth/login', methods=['POST'])
def login():
    d = request.get_json() or {}
    db = SessionLocal()
    user = db.query(User).filter_by(username=d.get('username'), password=d.get('password')).first()
    db.close()
    if not user:
        return jsonify({'ok':False,'msg':'Invalid credentials'}),401
    token = f"demo-{user.username}"
    return jsonify({'ok':True,'token':token,'username':user.username,'role':user.role})

@app.route('/admin/add-student-webcam', methods=['POST'])
def add_student_webcam():
    # expects form-data: username, label, image file (image)
    username = request.form.get('username')
    label = request.form.get('label','capture')
    file = request.files.get('image')
    if not username or not file:
        return jsonify({'ok':False,'msg':'username and image required'}),400
    user_dir = os.path.join(UPLOAD_FOLDER, username)
    os.makedirs(user_dir, exist_ok=True)
    fname = f"{label}_{uuid.uuid4().hex[:8]}.jpg"
    path = os.path.join(user_dir, fname)
    file.save(path)
    # after saving, retrain model
    trained, msg = train_model()
    return jsonify({'ok':True,'msg':f'saved {fname}; retrain: {trained} - {msg}'})

@app.route('/attendance/mark', methods=['POST'])
def mark_attendance():
    # accepts 'frame' file (image) or form 'username' for manual
    if 'username' in request.form and not request.files.get('frame'):
        username = request.form.get('username')
        db = SessionLocal()
        db.add(Attendance(student_username=username))
        db.commit()
        db.close()
        return jsonify({'ok':True,'msg':f'Attendance marked for {username} (manual)'})
    frame = request.files.get('frame')
    if not frame:
        return jsonify({'ok':False,'msg':'Send frame or username'}),400
    # load model
    if not os.path.exists(MODEL_PATH):
        return jsonify({'ok':False,'msg':'Model not trained yet. Add students first.'}),400
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(MODEL_PATH)
    # read image
    try:
        img = Image.open(io.BytesIO(frame.read())).convert('L').resize((200,200))
        arr = np.array(img, dtype=np.uint8)
    except Exception as e:
        return jsonify({'ok':False,'msg':'Invalid image'}),400
    label, conf = recognizer.predict(arr)
    # map label back to username
    mapping = get_label_mapping()
    inv = {v:k for k,v in mapping.items()}
    username = inv.get(label)
    if username:
        db = SessionLocal()
        db.add(Attendance(student_username=username))
        db.commit()
        db.close()
        return jsonify({'ok':True,'msg':f'Attendance marked for {username}', 'conf':float(conf)})
    else:
        return jsonify({'ok':False,'msg':'No match found', 'conf':float(conf)}),200

@app.route('/attendance/report', methods=['GET'])
def attendance_report():
    db = SessionLocal()
    rows = db.query(Attendance).order_by(Attendance.timestamp.desc()).all()
    data = [{'student':r.student_username,'timestamp':r.timestamp.isoformat()} for r in rows]
    db.close()
    return jsonify({'ok':True,'rows':data})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__=='__main__':
    print('Starting backend with OpenCV LBPH face recognition (no dlib required).')
    app.run(debug=True)
