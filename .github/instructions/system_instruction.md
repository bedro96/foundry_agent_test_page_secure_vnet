
## Overview
It is 3 tier system, /frontend is nextjs.16 based, /backend is python based. /frontend should provide user interface to login, admin page, chat page(chat with foundry agent), and system monitoring page. In /frontend no api should be made, all api will be created and provided by /backend. /backend needs to leverage sqlalchemy to connect mysql.

## frontend

# reference site for authentication & security, monitoring & logging, ui/ux is https://github.com/bedro96/iothub-controller-public/tree/main/
# main page should have clean factory line image as background, not too big as this web site will be used to detect faults and recommendations on those incidents.

# Admin page 
It should have menu for managing users. Refer to https://github.com/bedro96/iothub-controller-public/tree/main/app/admin

# Foundry Agent Performance page
Should have a place holder for Grafana to be embedded. Plan to embed Azure managed Grafana here to demonstrate.

# MCP validation page
Compose a page for validating mcp functionality. 
MCP URL(Streamable http), authentication(drop box for none, x-api-key) is required and once connected, it should provide tool list for final validation. Purpose is to validate MCP is correctly response to tool call. 
 
# Server Performance page
Refer to https://github.com/bedro96/iothub-controller-public/tree/main/app/server-performance

# Chat page. 
My private repo has best practice : https://github.com/bedro96/flask_AI_Chat/blob/main/templates/chat_new.html 
Chat window to display user prompt, system response in stream. 
Button to attach images, mic icon to record voice and convert the voice to Azure Speech API to retrieve text and send to LLM. 

## backend
Backend has lots of files already in place. Use these files to create /backend apis.

Backend also need to provide user related api for frontend to use. Ex) CRUD on /user
Which /frontend admin page should link to.
Backend should also use sqlalchemy to mysql. Mysql related credentials are located in /backend/.env 
/backend, define required tables, columns, and provide sql execution script to setup mysql.


## Testing
testing should be done flask8, ruff, mypy, bandit against backend. Test file should be kept for on going quality control.
Live smoke test should be done, once initial working piece of pushed to ACA. 
Production will have url in .env files once it is pre-production level.

## All activities should be logged in ~.md file and summarized content needs to be in README.md as well. 
In README.md, Overview of the system, Architecture of the system, network flow, login flow, how to deploy and configure should be demonstrated. Lastly test result should be summarized.

Consult .github/skills for each technology guidelines.
