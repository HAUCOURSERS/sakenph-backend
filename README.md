# A Commuter Guide Application with Multimodal Transport using A* and Yen's Algorithm

This is a system prototype using a hybrid algorithm used to generate transit routes 
in Angeles and Mabalacat City. It lets users input an origin and destination point
and see what routes they can take from three different modes (jeep, tricycle, walking).

## How to host app

1.  Clone the repo using Git or download it.
2.  From the terminal, change directory to the project folder containing `main.py`.
3.  Create a virtual environment with the command `python -m venv venv`.
4.  Activate the environment with `venv\Scripts\activate` (CMD) or `venv\Scripts\activate.ps1` (PowerShell).
5.  Install the dependencies using `pip install -r requirements.txt`.
6.  Run the app using the command `uvicorn main:app`.

> [!NOTE]
> Frontend app must call this app based on the IP address it is hosting on.