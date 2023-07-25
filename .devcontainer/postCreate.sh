touch /home/vscode/.bashrc
echo 'alias psql="psql -h localhost -U postgres"' >> /home/vscode/.bashrc
echo 'eval "$(starship init bash)"' >> /home/vscode/.bashrc

poetry install