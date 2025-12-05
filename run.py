from app import create_app, db
from app.models import Performer, Video, Settings

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'Performer': Performer, 'Video': Video, 'Settings': Settings}

if __name__ == '__main__':
    with app.app_context():
        from flask_migrate import upgrade
        upgrade()
    app.run(debug=True, host='0.0.0.0', port=5000)
