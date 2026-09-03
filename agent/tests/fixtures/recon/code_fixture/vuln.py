import subprocess
import os

def run_cmd(user_input):
    # vulnerable: shell=True on user input
    out = subprocess.run(user_input, shell=True, capture_output=True)
    return out.stdout

def load_system(config):
    os.system(f"cat {config}")

def main():
    print(run_cmd("echo hi"))
