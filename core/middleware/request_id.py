import uuid
from flask import g, request

def before_request_request_id():
    # reuse client request id if provided; else generate
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

def after_request_request_id(resp):
    rid = getattr(g, "request_id", None)
    if rid:
        resp.headers["X-Request-ID"] = rid
    return resp
