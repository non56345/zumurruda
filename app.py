import load_env

load_env.load()

from server import create_app

app = create_app()

if __name__ == "__main__":
    from server.config import Config
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
