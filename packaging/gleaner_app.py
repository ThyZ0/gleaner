"""Entry point of Gleaner.exe: double-click opens the app on your usual folders, without a console.
The server stops by itself five minutes after the browser tab is closed."""
import multiprocessing
import sys

from gleaner.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the parallel file readers start copies of this .exe
    main(sys.argv[1:] or ["--quit-when-idle", "5"])
