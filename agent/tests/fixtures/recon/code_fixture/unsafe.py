import pickle
import requests

def unsafe_load(data):
    return pickle.loads(data)

def fetch(url):
    return requests.get(url)
