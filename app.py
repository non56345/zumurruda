import load_env

load_env.load()

from server import create_app

app = create_app()
app.url_map.strict_slashes = False

if __name__ == "__main__":
    from server.config import Config
    app.run(host=Config.HOST, port=Config.PORT, debug=False)
