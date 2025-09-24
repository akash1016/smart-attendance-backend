Backend with OpenCV LBPH face recognition (no dlib needed)
Run:
cd backend
python -m venv venv311
venv311\Scripts\activate
pip install -r requirements.txt
python app.py
Notes: Upload student images via Admin panel (webcam). The server auto-trains LBPH model on saved images.
