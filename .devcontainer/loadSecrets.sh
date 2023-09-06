#!/bin/bash

# Path to the file containing the environment variables
env_file=".devcontainer/secrets.env"

# Path to .bashrc
bashrc_file="$HOME/.bashrc"

# Check if the env_file exists
if [ ! -f "$env_file" ]; then
    echo "File $env_file does not exist."
    exit 0
fi

# Read each line from the env_file
while IFS= read -r line
do
    echo "export $line" >> $bashrc_file
    echo "Added $line to $bashrc_file"

done < "$env_file"

# Source the .bashrc to apply changes immediately
source $bashrc_file

echo "Environment variables loaded."