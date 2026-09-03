import hashlib


def main():
    return hashlib.md5(b"x").hexdigest()


if __name__ == "__main__":
    main()
