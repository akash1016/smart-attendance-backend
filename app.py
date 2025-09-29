from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
import os, datetime, uuid, traceback, io
from PIL import Image
import numpy as np
import cv2
from models import Base, User, Attendance, Role, Profile, Announcement

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANNOUNCEMENT_IMAGE_FOLDER = os.path.join(BASE_DIR, 'announcement_images')
os.makedirs(ANNOUNCEMENT_IMAGE_FOLDER, exist_ok=True)


app = Flask(__name__)
CORS(app)

# DB setup
DB_PATH = os.path.join(BASE_DIR, 'database.db')
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

SessionLocal = sessionmaker(bind=engine)


Base.metadata.create_all(engine)

# Seed users
def seed():
    db = SessionLocal()
    try:
        # Add roles if they don't exist
        roles = ['Student', 'Teacher', 'Admin']
        for role_name in roles:
            if not db.query(Role).filter_by(role_name=role_name).first():
                db.add(Role(role_name=role_name))
        db.flush()  # Ensure roles are available

        # Get the Admin role
        admin_role = db.query(Role).filter_by(role_name='Admin').first()
        if not admin_role:
            db.commit()
            admin_role = db.query(Role).filter_by(role_name='Admin').first()

        # Add admin user and profile if not exists
        if not db.query(User).filter_by(username='admin').first():
            admin_user = User(username='admin', password='admin123')
            db.add(admin_user)
            db.flush()  # Get user_id before committing

            admin_profile = Profile(
                user_id=admin_user.user_id,
                role_id=admin_role.role_id,
                first_name='Admin',
                last_name='User',
                email_id='admin@example.com'
            )
            db.add(admin_profile)
            db.commit()
        else:
            db.commit()
    except Exception as e:
        db.rollback()
        print('Seed error:', e)
    finally:
        db.close()
seed()

# API to delete a student (Admin/Teacher only)
@app.route('/admin/delete-student/<username>', methods=['DELETE'])
def delete_student(username):
    # Token can be sent in header or as query param
    token = request.headers.get('Authorization') or request.args.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name not in ('Teacher', 'Admin'):
            return jsonify({'ok': False, 'msg': 'Only Teacher or Admin can delete students'}), 403
        # Find the user and profile for the student
        user = db.query(User).filter_by(username=username).first()
        if not user:
            return jsonify({'ok': False, 'msg': 'Student user not found'}), 404
        profile = db.query(Profile).filter_by(user_id=user.user_id).first()
        if not profile:
            return jsonify({'ok': False, 'msg': 'Student profile not found'}), 404
        # Check if the profile is actually a student
        student_role = db.query(Role).filter_by(role_name='Student').first()
        if not student_role or profile.role_id != student_role.role_id:
            return jsonify({'ok': False, 'msg': 'User is not a student'}), 400
        # Delete profile and user
        db.delete(profile)
        db.delete(user)
        db.commit()
        # Optionally, delete FaceID directory
        user_dir = os.path.join(UPLOAD_FOLDER, username)
        if os.path.isdir(user_dir):
            try:
                import shutil
                shutil.rmtree(user_dir)
            except Exception as e:
                print(f"Error deleting FaceID directory {user_dir}: {e}")
        return jsonify({'ok': True, 'msg': f'Student {username} deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to get usernames of all students
@app.route('/admin/get-all-student-usernames', methods=['GET'])
def get_all_student_usernames():
    # Token can be sent in header or as query param
    token = request.headers.get('Authorization') or request.args.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = request.headers.get('username')
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name not in ('Teacher', 'Admin'):
            return jsonify({'ok': False, 'msg': 'Only Teacher or Admin can access student usernames'}), 403
        # Get Student role
        student_role = db.query(Role).filter_by(role_name='Student').first()
        if not student_role:
            return jsonify({'ok': False, 'msg': 'Student role not found'}), 500
        # Get all student profiles
        student_profiles = db.query(Profile).filter_by(role_id=student_role.role_id).all()
        usernames = []
        for profile in student_profiles:
            user = db.query(User).filter_by(user_id=profile.user_id).first()
            if user:
                usernames.append(user.username)
        return jsonify({'ok': True, 'usernames': usernames})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to add a new teacher (Admin only)
@app.route('/admin/add-teacher', methods=['POST'])
def add_teacher():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    email_id = data.get('email_id')
    # Token can be sent in header or body
    token = request.headers.get('Authorization') or data.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name != 'Admin':
            return jsonify({'ok': False, 'msg': 'Only Admin can add teachers'}), 403
        if not all([username, password, first_name, last_name, email_id]):
            return jsonify({'ok': False, 'msg': 'All fields are required'}), 400
        # Check if username or email already exists
        if db.query(User).filter_by(username=username).first():
            return jsonify({'ok': False, 'msg': 'Username already exists'}), 400
        if db.query(Profile).filter_by(email_id=email_id).first():
            return jsonify({'ok': False, 'msg': 'Email already exists'}), 400
        # Get Teacher role
        teacher_role = db.query(Role).filter_by(role_name='Teacher').first()
        if not teacher_role:
            return jsonify({'ok': False, 'msg': 'Teacher role not found'}), 500
        # Create user first
        user = User(username=username, password=password)
        db.add(user)
        db.flush()  # get user_id after insert
        # Now create profile for the user
        profile = Profile(
            user_id=user.user_id,
            role_id=teacher_role.role_id,
            first_name=first_name,
            last_name=last_name,
            email_id=email_id
        )
        db.add(profile)
        db.commit()
        return jsonify({'ok': True, 'msg': 'Teacher added successfully', 'username': username, 'password': password})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

# API to delete a teacher (Admin only)
@app.route('/admin/delete-teacher/<username>', methods=['DELETE'])
def delete_teacher(username):
    # Token can be sent in header or as query param
    token = request.headers.get('Authorization') or request.args.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name != 'Admin':
            return jsonify({'ok': False, 'msg': 'Only Admin can delete teachers'}), 403
        # Find the user and profile for the teacher
        user = db.query(User).filter_by(username=username).first()
        if not user:
            return jsonify({'ok': False, 'msg': 'Teacher user not found'}), 404
        profile = db.query(Profile).filter_by(user_id=user.user_id).first()
        if not profile:
            return jsonify({'ok': False, 'msg': 'Teacher profile not found'}), 404
        # Check if the profile is actually a teacher
        teacher_role = db.query(Role).filter_by(role_name='Teacher').first()
        if not teacher_role or profile.role_id != teacher_role.role_id:
            return jsonify({'ok': False, 'msg': 'User is not a teacher'}), 400
        # Delete profile and user
        db.delete(profile)
        db.delete(user)
        db.commit()
        return jsonify({'ok': True, 'msg': f'Teacher {username} deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to mark student attendance manually (admin/teacher only, no faceID)
@app.route('/admin/mark-attendance-manual', methods=['POST'])
def mark_attendance_manual():
    data = request.get_json() or {}
    usernames = data.get('usernames')  # List of usernames
    date_str = data.get('date')  # Expected format: 'YYYY-MM-DD'
    # Token can be sent in header or body
    token = request.headers.get('Authorization') or data.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name not in ('Teacher', 'Admin'):
            return jsonify({'ok': False, 'msg': 'Only Teacher or Admin can mark attendance manually'}), 403
        if not usernames or not isinstance(usernames, list) or not date_str:
            return jsonify({'ok': False, 'msg': 'usernames (list) and date are required'}), 400
        try:
            mark_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            return jsonify({'ok': False, 'msg': 'Invalid date format. Use YYYY-MM-DD'}), 400
        results = []
        for username in usernames:
            # Get the user and profile for the username
            user = db.query(User).filter_by(username=username).first()
            if not user:
                results.append({'username': username, 'msg': 'User not found'})
                continue
            profile = db.query(Profile).filter_by(user_id=user.user_id).first()
            if not profile:
                results.append({'username': username, 'msg': 'Profile not found'})
                continue

            already_marked = db.query(Attendance).filter(
                Attendance.student_id == profile.profile_id,
                Attendance.attendance_date == mark_date
            ).first()
            if already_marked:
                results.append({'username': username, 'msg': 'Already marked present for this date'})
            else:
                att = Attendance(
                    student_id=profile.profile_id,
                    attendance_date=mark_date,
                    status='Present'
                )
                db.add(att)
                results.append({'username': username, 'msg': 'Marked present'})
        db.commit()
        return jsonify({'ok': True, 'results': results})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to get username by email
@app.route('/admin/get-username-by-email/<email>', methods=['GET'])
def get_username_by_email(email):
    db = SessionLocal()
    try:
        profile = db.query(Profile).filter_by(email_id=email).first()
        if not profile:
            return jsonify({'ok': False, 'msg': 'No user found for this email'}), 404
        user = db.query(User).filter_by(user_id=profile.user_id).first()
        if not user:
            return jsonify({'ok': False, 'msg': 'No user found for this email'}), 404
        return jsonify({'ok': True, 'username': user.username})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

# Serve announcement images
@app.route('/announcement_images/<filename>')
def serve_announcement_image(filename):
    return send_from_directory(ANNOUNCEMENT_IMAGE_FOLDER, filename)

# API to get all announcements
@app.route('/admin/get-announcements', methods=['GET'])
def get_announcements():
    db = SessionLocal()
    try:
        announcements = db.query(Announcement).order_by(Announcement.id.desc()).all()
        result = []
        for ann in announcements:
            images = []
            if ann.images:
                for fname in ann.images.split(','):
                    only_fname = os.path.basename(fname.lstrip('/\\'))
                    images.append(f"/announcement_images/{only_fname}")
            result.append({
                'id': ann.id,
                'title': ann.title,
                'description': ann.description,
                'images': images
            })
        return jsonify({'ok': True, 'announcements': result})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to get student list (admin/teacher only, with face ID check)
@app.route('/admin/get-student-list', methods=['GET'])
def get_student_list():
    # Token can be sent in header or as query param
    token = request.headers.get('Authorization') or request.args.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name not in ('Teacher', 'Admin'):
            return jsonify({'ok': False, 'msg': 'Only Teacher or Admin can access student list'}), 403
        # Get Student role
        student_role = db.query(Role).filter_by(role_name='Student').first()
        if not student_role:
            return jsonify({'ok': False, 'msg': 'Student role not found'}), 500
        # Get all students
        students = db.query(Profile).filter_by(role_id=student_role.role_id).all()
        result = []
        for student in students:
            user = db.query(User).filter_by(user_id=student.user_id).first()
            username = user.username if user else None
            # Check if face ID (directory) exists
            has_face_id = False
            face_msg = 'Face ID not added'
            if username:
                user_dir = os.path.join(UPLOAD_FOLDER, username)
                if os.path.isdir(user_dir) and len(os.listdir(user_dir)) > 0:
                    has_face_id = True
                    face_msg = 'Face ID added'
            result.append({
                'profile_id': student.profile_id,
                'username': username,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'email_id': student.email_id,
                'has_face_id': has_face_id,
                'face_msg': face_msg
            })
        return jsonify({'ok': True, 'students': result})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

# API to get teacher list (admin only)
@app.route('/admin/get-teacher-list', methods=['GET'])
def get_teacher_list():
    # Token can be sent in header or as query param
    token = request.headers.get('Authorization') or request.args.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name != 'Admin':
            return jsonify({'ok': False, 'msg': 'Only Admin can access teacher list'}), 403
        # Get Teacher role
        teacher_role = db.query(Role).filter_by(role_name='Teacher').first()
        if not teacher_role:
            return jsonify({'ok': False, 'msg': 'Teacher role not found'}), 500
        # Get all teachers
        teachers = db.query(Profile).filter_by(role_id=teacher_role.role_id).all()
        result = []
        for teacher in teachers:
            user = db.query(User).filter_by(user_id=teacher.user_id).first()
            username = user.username if user else None
            result.append({
                'profile_id': teacher.profile_id,
                'username': username,
                'first_name': teacher.first_name,
                'last_name': teacher.last_name,
                'email_id': teacher.email_id
            })
        return jsonify({'ok': True, 'teachers': result})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to add an announcement
@app.route('/admin/add-announcement', methods=['POST'])
def add_announcement():
    title = request.form.get('title')
    description = request.form.get('description')
    files = request.files.getlist('images')  # Can be empty
    if not title or not description:
        return jsonify({'ok': False, 'msg': 'Title and description are required'}), 400
    image_filenames = []
    # Create directory if not exists (already ensured above)
    for file in files:
        if file and file.filename:
            fname = f"{uuid.uuid4().hex}_{file.filename}"
            path = os.path.join(ANNOUNCEMENT_IMAGE_FOLDER, fname)
            file.save(path)
            image_filenames.append(fname)
    images_str = ','.join(image_filenames) if image_filenames else None
    db = SessionLocal()
    try:
        announcement = Announcement(title=title, description=description, images=images_str)
        db.add(announcement)
        db.commit()
        return jsonify({'ok': True, 'msg': 'Announcement added successfully', 'id': announcement.id})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()


# API to delete an announcement and its images
@app.route('/admin/delete-announcement/<int:announcement_id>', methods=['DELETE'])
def delete_announcement(announcement_id):
    db = SessionLocal()
    try:
        announcement = db.query(Announcement).filter_by(id=announcement_id).first()
        if not announcement:
            return jsonify({'ok': False, 'msg': 'Announcement not found'}), 404
        # Delete associated images from filesystem
        if announcement.images:
            for fname in announcement.images.split(','):
                only_fname = os.path.basename(fname.lstrip('/\\'))
                img_path = os.path.join(ANNOUNCEMENT_IMAGE_FOLDER, only_fname)
                if os.path.isfile(img_path):
                    try:
                        os.remove(img_path)
                    except Exception as e:
                        print(f"Error deleting image {img_path}: {e}")
        db.delete(announcement)
        db.commit()
        return jsonify({'ok': True, 'msg': 'Announcement and images deleted'})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

# API to validate if a directory exists for a student by email
@app.route('/admin/validate-student-directory/<email>', methods=['GET'])
def validate_student_directory(email):
    db = SessionLocal()
    try:
        profile = db.query(Profile).filter_by(email_id=email).first()
        if not profile:
            return jsonify({'ok': False, 'msg': 'No user found for this email'}), 404
        user = db.query(User).filter_by(user_id=profile.user_id).first()
        if not user:
            return jsonify({'ok': False, 'msg': 'No user found for this email'}), 404
        user_dir = os.path.join(UPLOAD_FOLDER, user.username)
        exists = os.path.isdir(user_dir)
        return jsonify({'ok': True, 'username': user.username, 'directory_exists': exists})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

# API to add a new student
@app.route('/admin/add-student', methods=['POST'])
def add_student():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    email_id = data.get('email_id')
    # Token can be sent in header or body
    token = request.headers.get('Authorization') or data.get('token')
    if not token or not token.startswith('demo-'):
        return jsonify({'ok': False, 'msg': 'Missing or invalid token'}), 401
    acting_username = token.replace('demo-', '', 1)
    db = SessionLocal()
    try:
        acting_user = db.query(User).filter_by(username=acting_username).first()
        if not acting_user:
            return jsonify({'ok': False, 'msg': 'Invalid user for token'}), 401
        acting_profile = db.query(Profile).filter_by(user_id=acting_user.user_id).first()
        acting_role = db.query(Role).filter_by(role_id=acting_profile.role_id).first() if acting_profile else None
        if not acting_role or acting_role.role_name not in ('Teacher', 'Admin'):
            return jsonify({'ok': False, 'msg': 'Only Teacher or Admin can add students'}), 403
        if not all([username, password, first_name, last_name, email_id]):
            return jsonify({'ok': False, 'msg': 'All fields are required'}), 400
        # Check if username or email already exists
        if db.query(User).filter_by(username=username).first():
            return jsonify({'ok': False, 'msg': 'Username already exists'}), 400
        if db.query(Profile).filter_by(email_id=email_id).first():
            return jsonify({'ok': False, 'msg': 'Email already exists'}), 400
        # Get Student role
        student_role = db.query(Role).filter_by(role_name='Student').first()
        if not student_role:
            return jsonify({'ok': False, 'msg': 'Student role not found'}), 500
        # Create user first
        user = User(username=username, password=password)
        db.add(user)
        db.flush()  # get user_id after insert
        # Now create profile for the user
        profile = Profile(
            user_id=user.user_id,
            role_id=student_role.role_id,
            first_name=first_name,
            last_name=last_name,
            email_id=email_id
        )
        db.add(profile)
        db.commit()
        return jsonify({'ok': True, 'msg': 'Student added successfully', 'username': username, 'password': password})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'msg': str(e)}), 500
    finally:
        db.close()

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
    profile = db.query(Profile).filter_by(user_id=user.user_id).first()
    role = db.query(Role).filter_by(role_id=profile.role_id).first()
    db.close()
    if not user:
        return jsonify({'ok':False,'msg':'Invalid credentials'}),401
    token = f"demo-{user.username}"
    return jsonify({'ok':True,'token':token,'username':user.username,'role':role.role_name if role else None})

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
    # Accepts 'frame' file (image) and 'username' (both required)
    db = SessionLocal()
    try:
        username = request.form.get('username')
        frame = request.files.get('frame')
        if not username or not frame:
            db.close()
            return jsonify({'ok': False, 'msg': 'Both username and frame are required'}), 400
        # Find user and profile for the selected username
        user = db.query(User).filter_by(username=username).first()
        if not user:
            db.close()
            return jsonify({'ok': False, 'msg': 'User not found'}), 404
        profile = db.query(Profile).filter_by(user_id=user.user_id).first()
        if not profile:
            db.close()
            return jsonify({'ok': False, 'msg': 'Profile not found'}), 404
        today = datetime.date.today()
        # Check if student has added FaceID (directory exists under uploads/username)
        user_dir = os.path.join(UPLOAD_FOLDER, username)
        if not os.path.isdir(user_dir) or len(os.listdir(user_dir)) == 0:
            db.close()
            return jsonify({'ok': False, 'msg': 'Face ID not added for this student. Please add Face ID first.'}), 400
        # Check if already marked for today
        already_marked = db.query(Attendance).filter(
            Attendance.student_id == profile.profile_id,
            Attendance.attendance_date == today
        ).first()
        # load model for face recognition (for confidence only)
        if not os.path.exists(MODEL_PATH):
            db.close()
            return jsonify({'ok': False, 'msg': 'Model not trained yet. Add students first.'}), 400
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.read(MODEL_PATH)
        try:
            img = Image.open(io.BytesIO(frame.read())).convert('L').resize((200,200))
            arr = np.array(img, dtype=np.uint8)
        except Exception as e:
            db.close()
            return jsonify({'ok': False, 'msg': 'Invalid image'}), 400
        label, conf = recognizer.predict(arr)
        if already_marked:
            db.close()
            return jsonify({'ok': False, 'msg': f'Attendance already marked for {username} today', 'conf': float(conf)}), 400
        # Optionally, you can check if label matches selected username, but always mark for selected username
        att = Attendance(
            student_id=profile.profile_id,
            attendance_date=today,
            status='Present'
        )
        db.add(att)
        db.commit()
        db.close()
        return jsonify({'ok': True, 'msg': f'Attendance marked for {username}', 'conf': float(conf)})
    except Exception as e:
        db.rollback()
        db.close()
        return jsonify({'ok': False, 'msg': str(e)}), 500

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
