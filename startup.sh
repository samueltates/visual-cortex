export PIPENV_VENV_IN_PROJECT=1
pipenv install
pipenv sync
pipenv run python app.py
