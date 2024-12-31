#!/bin/bash

# export environment variables in a file
# https://stackoverflow.com/questions/27771781/how-can-i-access-docker-set-environment-variables-from-a-cron-job
printenv | grep -v “no_proxy” > /app/.env

exec cron -f

