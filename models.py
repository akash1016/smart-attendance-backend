
# models.py
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Date, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# ...existing code...


# models.py
from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Date
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    profile = relationship('Profile', back_populates='user', uselist=False)

# Announcement model
class Announcement(Base):
    __tablename__ = 'announcements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    images = Column(String(1000))  # Comma-separated image filenames or paths

class Role(Base):
    __tablename__ = 'roles'
    role_id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(Enum('Student', 'Teacher', 'Admin'), nullable=False)
    profiles = relationship('Profile', back_populates='role')

class Profile(Base):
    __tablename__ = 'profiles'
    profile_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    role_id = Column(Integer, ForeignKey('roles.role_id'))
    first_name = Column(String(50))
    last_name = Column(String(50))
    email_id = Column(String(100), unique=True)
    user = relationship('User', back_populates='profile')
    role = relationship('Role', back_populates='profiles')
    attendance_records = relationship('Attendance', back_populates='student')

class Attendance(Base):
    __tablename__ = 'attendance'
    attendance_id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey('profiles.profile_id'), nullable=False)
    attendance_date = Column(Date, nullable=False)
    status = Column(Enum('Present', 'Absent', 'Leave'), nullable=False)
    remarks = Column(String(255))
    student = relationship('Profile', back_populates='attendance_records')

# Complaint model
class Complaint(Base):
    __tablename__ = 'complaints'
    complaint_id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey('profiles.profile_id'), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum('Open', 'Closed', 'Resolved'), default='Open', nullable=False)
    created_at = Column(Date, nullable=False)
    student = relationship('Profile')