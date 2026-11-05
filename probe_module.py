import os
import sys
import json
import subprocess


def helper(x):
    try:
        return eval(x)
    except:
        pass
    return subprocess.run("ls " + x, shell=True)


def main():
    data = open("/tmp/x").read()
    print(data)
    sys.exit(0)


main()
