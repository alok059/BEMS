from app import app, db, create_default_data
with app.app_context():
    db.create_all()
    create_default_data()
    