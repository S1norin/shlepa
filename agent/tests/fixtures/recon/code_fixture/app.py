import os

from flask import Flask, request

app = Flask(__name__)


@app.route("/run")
def run():
    return str(eval(request.args.get("e")))


@app.route("/ping")
def ping():
    return str(os.system(request.args.get("c")))


@app.route("/info")
def info():
    return "ok"
