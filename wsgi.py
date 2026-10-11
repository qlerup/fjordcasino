from waitress import serve
from app import create_app

if __name__ == '__main__':
    serve(create_app(), host='0.0.0.0', port=8080, threads=8)
