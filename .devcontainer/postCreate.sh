echo "[client]
protocol = tcp
user     = root" >> ~/.my.cnf

bash .devcontainer/loadSecrets.sh

poetry install
pip install --user --upgrade nox-poetry
pip install --user --upgrade nox