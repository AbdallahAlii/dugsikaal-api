def after_request_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-XSS-Protection"] = "0"  # deprecated, but explicit
    # You can also add CSP here when you finalize front-end routes
    return resp
