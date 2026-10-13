from waitress import serve
from app import create_app


def server_options(app):
    # Match the app's existing single-proxy HTTPS trust in FjordHub mode.
    # Waitress otherwise strips X-Forwarded-Proto before ProxyFix sees it.
    if app.config['AUTH_MODE'] == 'fjordhub':
        return dict(trusted_proxy='*', trusted_proxy_count=1,
                    trusted_proxy_headers={'x-forwarded-proto'})
    return {}


if __name__ == '__main__':
    app = create_app()
    serve(app, host='0.0.0.0', port=8080, threads=8, **server_options(app))
